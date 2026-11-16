"""Optional Wikimedia and Openverse place photos. No LLM or paid API is involved."""
import json
import re
import threading
import time
from collections import OrderedDict
from html import unescape
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from pydantic import Field

from .geoapify import distance_km, place_name
from .models import Contract


class PhotoRequest(Contract):
    name: str = Field(min_length=1, max_length=200)
    matched_name: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


_cache = OrderedDict()
_lock = threading.Lock()
_last_request = 0.0


def fetch_json(url: str) -> dict:
    global _last_request
    # Serialize requests and cap traffic. Hosts are constants supplied only by this module.
    with _lock:
        time.sleep(max(0, 0.3 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
    request = Request(url,
                      headers={'User-Agent': 'TripPilot/0.4 (personal itinerary application)', 'Accept': 'application/json'})
    with urlopen(request, timeout=8) as response:
        return json.load(response)


def request_json(host: str, **params) -> dict:
    return fetch_json(f'https://{host}/w/api.php?' + urlencode({'format': 'json', 'formatversion': 2, **params}))


def request_openverse(query: str, licenses: str = 'by,by-sa,cc0,pdm', wide: bool = False) -> dict:
    return fetch_json('https://api.openverse.org/v1/images/?' + urlencode({
        'q': query[:200], 'page_size': 8, 'mature': 'false', 'license': licenses, **({'aspect_ratio':'wide'} if wide else {})}))


def public_url(value: str) -> bool:
    parsed = urlparse(value)
    host = parsed.hostname or ''
    return (parsed.scheme == 'https' and bool(host) and '.' in host and not parsed.username
            and not re.fullmatch(r'[\d.]+', host) and not host.endswith(('.local', '.localhost', '.internal')))


def openverse_photo(place: PhotoRequest) -> dict:
    # No dates, booking details or itinerary text are shared with image search.
    names = {place_name(value, place.city) for value in (place.name, place.matched_name)} - {''}
    city = place_name(place.city)
    queries = list(dict.fromkeys(re.sub(r'^(?:(?:lunch|dinner|breakfast|coffee|check.in|arrive|arrival) at|visit|explore|walk to)\s+', '', name, flags=re.I) for name in [place.matched_name, place.name]))[:2]
    for name in queries:
        for item in request_openverse(f'"{name}" {place.city}').get('results', []):
            title = plain(item.get('title') or '')
            normalized = ' ' + place_name(title) + ' '
            tags = ' '.join(tag.get('name', '') for tag in item.get('tags') or [])
            context = place_name(title + ' ' + tags)
            if not any(' ' + name + ' ' in normalized for name in names) or city not in context:
                continue
            image = item.get('thumbnail') or ''
            source = item.get('foreign_landing_url') or ''
            license_url = item.get('license_url') or ''
            license_name = item.get('license') or ''
            author = plain(item.get('creator') or '')
            if (item.get('mature') or license_name not in {'by', 'by-sa', 'cc0', 'pdm'}
                    or not all(public_url(url) for url in (image, source, license_url))
                    or not author):
                continue
            return {'status': 'available', 'photo': {'url': image, 'full_url': item.get('url') if public_url(item.get('url') or '') else image, 'source_url': source,
                    'author': author, 'license': (license_name + ' ' + (item.get('license_version') or '')).strip(),
                    'license_url': license_url, 'title': title, 'provider': 'Openverse', 'attribution_required': license_name in {'by','by-sa'}}}
    return {'status': 'missing', 'photo': None}


def plain(value: str) -> str:
    return unescape(re.sub(r'<[^>]*>', '', value)).strip()[:400]


def photo_for(place: PhotoRequest) -> dict:
    key = (place.name, place.matched_name, place.city, round(place.lat, 5) if place.lat is not None else None, round(place.lng, 5) if place.lng is not None else None)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > time.monotonic():
            _cache.move_to_end(key)
            return cached[1]
    failed = False
    try:
        result = find_photo(place)
    except Exception:
        failed = True
        result = {'status': 'missing', 'photo': None}
    if not result['photo']:
        try:
            result = openverse_photo(place)
        except Exception:
            failed = True
    if failed and not result['photo']:
        result = {'status': 'unavailable', 'photo': None}
    with _lock:
        _cache[key] = (time.monotonic() + (300 if result['status'] == 'unavailable' else 86400), result)
        while len(_cache) > 512:
            _cache.popitem(last=False)
    return result


def find_photo(place: PhotoRequest) -> dict:
    missing = {'status': 'missing', 'photo': None}
    if place.lat is None or place.lng is None:
        return missing
    names = {place_name(name, place.city) for name in (place.name, place.matched_name)}
    pages = request_json('en.wikipedia.org', action='query', generator='geosearch',
                         ggscoord=f'{place.lat}|{place.lng}', ggsradius=750, ggslimit=20,
                         prop='coordinates|pageimages', colimit='max', piprop='name').get('query', {}).get('pages', [])
    for page in pages:
        title = re.sub(r'\s*\([^)]*\)', '', page.get('title', ''))
        if place_name(title, place.city) not in names or not page.get('pageimage'):
            continue
        coordinate = next(iter(page.get('coordinates', [])), None)
        if not coordinate or distance_km((place.lat, place.lng), (coordinate['lat'], coordinate['lon'])) > 0.75:
            continue
        files = request_json('commons.wikimedia.org', action='query', titles='File:' + page['pageimage'],
                             prop='imageinfo', iiprop='url|extmetadata', iiurlwidth=360).get('query', {}).get('pages', [])
        for file in files:
            info = next(iter(file.get('imageinfo', [])), {})
            meta = info.get('extmetadata', {})
            author = plain(meta.get('Artist', {}).get('value', ''))
            license_name = plain(meta.get('LicenseShortName', {}).get('value', ''))
            license_url = meta.get('LicenseUrl', {}).get('value', '')
            image = info.get('thumburl', '')
            source = info.get('descriptionurl', '')
            if (urlparse(image).hostname not in {'upload.wikimedia.org', 'thumb.wikimedia.org'}
                    or urlparse(image).scheme != 'https'
                    or urlparse(source).hostname != 'commons.wikimedia.org'
                    or urlparse(source).scheme != 'https'
                    or not author or not license_name):
                continue
            if license_url.startswith('//'):
                license_url = 'https:' + license_url
            if urlparse(license_url).scheme != 'https' or urlparse(license_url).hostname not in {'creativecommons.org', 'commons.wikimedia.org'}:
                license_url = source
            return {'status': 'available', 'photo': {'url': image, 'full_url': info.get('url') if urlparse(info.get('url','')).hostname == 'upload.wikimedia.org' and urlparse(info.get('url','')).scheme == 'https' else image, 'source_url': source,
                    'author': author, 'license': license_name, 'license_url': license_url, 'title': page['title'], 'provider': 'Wikimedia Commons', 'attribution_required': meta.get('AttributionRequired',{}).get('value','true') != 'false' and license_name.lower() not in {'public domain','cc0','cc0 1.0'}}}
    return missing


class DestinationPhotoRequest(Contract):
    city: str = Field(min_length=1, max_length=100)


def destination_photo(city: str) -> dict:
    """Find a city background on demand; prefer images requiring no attribution."""
    key = ('destination', city.casefold().strip())
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > time.monotonic(): return cached[1]
    result = {'status':'missing','photo':None}
    city_name = ' ' + place_name(city) + ' '
    try:
        for licenses in ('cc0,pdm','by,by-sa'):
            items = request_openverse(f'"{city}" skyline',licenses=licenses,wide=True).get('results',[])
            for item in items:
                title = plain(item.get('title') or '')
                context = ' ' + place_name(title + ' ' + ' '.join(t.get('name','') for t in item.get('tags') or [])) + ' '
                license_name = item.get('license') or ''
                image = item.get('url') or item.get('thumbnail') or ''
                source, license_url = item.get('foreign_landing_url') or '', item.get('license_url') or ''
                if (city_name not in context or item.get('mature') or license_name not in licenses.split(',')
                        or not all(public_url(value) for value in (image,source,license_url))): continue
                result = {'status':'available','photo':{'url':image,'source_url':source,'author':plain(item.get('creator') or ''),
                          'license':(license_name+' '+(item.get('license_version') or '')).strip(), 'license_url':license_url,
                          'title':title,'provider':'Openverse','attribution_required':license_name in {'by','by-sa'}}}
                break
            if result['photo']: break
    except Exception:
        result = {'status':'unavailable','photo':None}
    with _lock:
        _cache[key] = (time.monotonic() + (300 if result['status']=='unavailable' else 86400),result)
        while len(_cache)>512: _cache.popitem(last=False)
    return result
