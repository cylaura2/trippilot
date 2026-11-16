"""Bounded, server-only Geoapify tools. No model calls or synthetic fallbacks."""
import json
import math
import os
import re
import time
import unicodedata
from collections import OrderedDict
from hashlib import sha256
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import ValidationError

from .models import PlaceCandidate, PlaceResolution, RouteEstimate

_lock = Lock()
_last_request = 0.0
_cache: OrderedDict = OrderedDict()
SOURCE = 'Geoapify / OpenStreetMap'
CATEGORIES = {'cafe': 'catering.cafe', 'restaurant': 'catering.restaurant',
              'museum': 'entertainment.museum', 'attraction': 'tourism.attraction'}


class GeoapifyError(ValueError):
    """A deliberately safe message; never include a URL, key, or response body."""


def normalize(value: str) -> str:
    value = ''.join(c for c in unicodedata.normalize('NFKD', value.casefold())
                    if not unicodedata.combining(c))
    return ' '.join(re.findall(r'\w+', value))


def distance_km(a: tuple, b: tuple) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2 - lat1, math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(h)))


def place_name(value: str, city: str = '') -> str:
    value = normalize(value)
    value = re.sub(r'^(?:(?:lunch|dinner|breakfast|coffee|check in|arrive|arrival) at|visit|explore|walk to|(?:walk|stroll) (?:along|around|on|through)(?: the)?)\s+', '', value)
    city_words = set(normalize(city).split())
    return ' '.join(word for word in value.split() if word not in city_words)


def specific_place_name(name: str) -> str:
    """Use an explicitly named landmark as the map anchor for a neighborhood walk."""
    match = re.search(r'\b(?:quarter|neighbou?rhood|district|old town|barrio)\b.*?\s+(?:and|&|then|followed by)\s+(?:a visit to\s+|visit\s+|the\s+)?(.+)$', name, re.I)
    if match and re.search(r'\b(?:cathedral|basilica|museum|church|palace|temple|gallery)\b', match[1], re.I):
        return match[1].strip().rstrip('.')
    return name


def is_street_walk(name: str) -> bool:
    """An explicit avenue/street walk, not a venue name or numbered address."""
    text = normalize(name)
    return (bool(re.search(r'\b(street|avenue|boulevard|promenade|passeig|rambla|carrer|calle|avenida|via|rue|quai|road|lane)\b',text))
            and not re.search(r'\d|\b(hotel|restaurant|cafe|museum|shop|bar|pizzeria|station)\b',text))


def confident_place(result: dict, name: str, city: str) -> dict | None:
    """One exact named match, not a claim that a brand has only one branch worldwide."""
    if result.get('proposed'):
        return None
    query = place_name(name, city)
    exact = [p for p in result.get('candidates', []) if query and not p.get('walk_anchor') and place_name(p['name'], city) == query]
    return exact[0] if len(exact) == 1 and exact[0].get('confidence', 0) >= 0.9 else None


class GeoapifyClient:
    def __init__(self, api_key: str | None = None):
        self._key = (api_key if api_key is not None else os.environ.get('GEOAPIFY_API_KEY', '')).strip()

    def _request(self, endpoint: str, **params) -> dict:
        global _last_request
        if not self._key:
            raise GeoapifyError('Add GEOAPIFY_API_KEY to .env and restart the Python backend to check real places.')
        # Shared across workflow instances; no raw credentials enter cache keys or results.
        cache_key = (sha256(self._key.encode()).hexdigest(), endpoint, urlencode(sorted(params.items())))
        with _lock:
            now = time.monotonic()
            cached = _cache.get(cache_key)
            if cached and now - cached[0] < 3600:
                _cache.move_to_end(cache_key)
                return json.loads(cached[1])
            # Four requests/second across local runs, below the free plan's five.
            time.sleep(max(0, 0.25 - (now - _last_request)))
            _last_request = time.monotonic()
            version = 'v2' if endpoint == 'places' else 'v1'
            url = f'https://api.geoapify.com/{version}/' + endpoint + '?' + urlencode({**params, 'apiKey': self._key})
            try:
                request = Request(url, headers={'User-Agent': 'TripPilot/0.3', 'Accept': 'application/json'})
                with urlopen(request, timeout=12) as response:
                    data = json.load(response)
                if not isinstance(data, dict) or not isinstance(data.get('features'), list):
                    raise GeoapifyError('Geoapify returned an unexpected response. Please try again.')
            except HTTPError as error:
                if error.code in (401, 403):
                    message = 'Geoapify rejected the key. Check its permissions and restart after updating .env.'
                elif error.code == 429:
                    message = 'Geoapify usage limit reached. Wait before checking again.'
                else:
                    message = f'Geoapify returned HTTP {error.code}. Please try again later.'
                raise GeoapifyError(message) from None
            except (URLError, TimeoutError, OSError):
                raise GeoapifyError('Could not reach Geoapify. Check your connection and try again.') from None
            except (ValueError, TypeError) as error:
                if isinstance(error, GeoapifyError):
                    raise
                raise GeoapifyError('Geoapify returned an unreadable response. Please try again.') from None
            _cache[cache_key] = (time.monotonic(), json.dumps(data))
            _cache.move_to_end(cache_key)
            while len(_cache) > 512:
                _cache.popitem(last=False)
            return data

    def search_place(self, name: str, city: str) -> dict:
        """Resolve only strong named matches; return alternatives for human choice."""
        center_data = self._request('geocode/search', text=city, type='city', limit=1)
        centers = center_data['features']
        if not centers:
            return PlaceResolution(status='unresolved', reason='Destination city could not be located.').model_dump()
        try:
            center = centers[0]['properties']
            lat, lon = float(center['lat']), float(center['lon'])
            target = specific_place_name(name)
            query = place_name(target, city) or target
            data = self._request('geocode/search', text=f'{query}, {city}', limit=5,
                                 filter=f'circle:{lon},{lat},50000', bias=f'proximity:{lon},{lat}')
            street_walk = is_street_walk(target)
            candidates = {}
            for feature in data['features']:
                props = feature.get('properties', {})
                # A street may be a walk anchor only when explicitly requested and name-matched.
                street_pin = props.get('result_type') == 'street' and street_walk
                if props.get('result_type') not in ('amenity', 'building') and not street_pin:
                    continue
                label = props.get('name') or props.get('street') or props.get('address_line1','')
                if street_walk and place_name(label, city) != query:
                    continue
                if distance_km((lat, lon), (float(props['lat']), float(props['lon']))) > 50:
                    continue
                candidate = PlaceCandidate(id=props['place_id'], name=label, walk_anchor=street_walk,
                                           address=props['formatted'], lat=props['lat'], lng=props['lon'],
                                           confidence=props.get('rank', {}).get('confidence', 0),
                                           categories=props.get('categories') or ([props['category']] if props.get('category') else []))
                candidates[candidate.id] = candidate
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            if isinstance(error, GeoapifyError):
                raise
            raise GeoapifyError('Geoapify returned invalid place details. Please try again.') from None
        choices = list(candidates.values())
        if not choices:
            return PlaceResolution(status='unresolved', reason='Couldn’t match this stop to a specific place. Use one venue name or a street address.').model_dump()
        matched = confident_place({'candidates': [p.model_dump() for p in choices]}, specific_place_name(name), city)
        resolved = matched is not None
        return PlaceResolution(status='resolved' if resolved else 'ambiguous',
                               place=matched, candidates=choices,
                               reason=('Choose a starting point for this walk. The pin represents one point, not the entire walking route.'
                                       if street_walk else 'Matched a specific named location.' if resolved else 'Confirm the intended location from the search results.')).model_dump()

    def search_nearby(self, category: str, anchor: dict) -> dict:
        """Return suggestions around a grounded anchor, never a confirmed booking."""
        if category not in CATEGORIES:
            raise GeoapifyError('Unsupported nearby search category.')
        lat, lon = anchor['lat'], anchor['lng']
        data = self._request('places', categories=CATEGORIES[category], limit=5,
                             filter=f'circle:{lon},{lat},1000', bias=f'proximity:{lon},{lat}')
        candidates = {}
        try:
            for feature in data['features']:
                props = feature['properties']
                categories = props.get('categories', [])
                if not any(value == CATEGORIES[category] or value.startswith(CATEGORIES[category] + '.') for value in categories):
                    continue
                if not props.get('name') or distance_km((lat, lon), (props['lat'], props['lon'])) > 1:
                    continue
                candidate = PlaceCandidate(id=props['place_id'], name=props['name'],
                                           address=props['formatted'], lat=props['lat'], lng=props['lon'], categories=categories)
                candidates[candidate.id] = candidate
        except (KeyError, TypeError, ValueError):
            raise GeoapifyError('Geoapify returned invalid nearby place details. Please try again.') from None
        return PlaceResolution(status='ambiguous' if candidates else 'unresolved',
                               candidates=list(candidates.values()), proposed=True,
                               reason=f'Nearby {category} options within 1 km of {anchor["name"]}; choose one. Hours and availability are unverified.'
                               if candidates else f'No named {category} found within 1 km of {anchor["name"]}.').model_dump()

    def get_route(self, origin: dict, destination: dict) -> dict:
        """Prefer short walks; compare transit and car when walking is lengthy."""
        if origin['lat'] == destination['lat'] and origin['lng'] == destination['lng']:
            return RouteEstimate(status='available', minutes=0, distance_meters=0).model_dump()
        walk = self._route(origin, destination, 'walk')
        if walk['status'] == 'available' and walk['minutes'] <= 25:
            return walk
        alternatives = {}
        for mode in ('approximated_transit', 'drive'):
            try:
                route = self._route(origin, destination, mode)
                if route['status'] == 'available':
                    # Include a small boarding/wait or pickup allowance in motorized travel time.
                    route['minutes'] += 5
                    route['allowance_minutes'] = 5
                    alternatives[mode] = route
            except GeoapifyError:
                # An unavailable optional mode must not discard a valid route.
                continue
        transit, car = alternatives.get('approximated_transit'), alternatives.get('drive')
        selected = (transit if transit and (not car or transit['minutes'] <= car['minutes'] + 10)
                    else car or transit)
        if selected and (walk['status'] != 'available' or selected['minutes'] <= walk['minutes'] - 10):
            return selected
        return walk if walk['status'] == 'available' else selected or walk

    def _route(self, origin: dict, destination: dict, mode: str) -> dict:
        data = self._request('routing', waypoints=f"{origin['lat']},{origin['lng']}|{destination['lat']},{destination['lng']}",
                             mode=mode, units='metric')
        names = {'walk': 'walking', 'drive': 'taxi/car', 'approximated_transit': 'approximate transit'}
        source = f'Geoapify {names[mode]} estimate / OpenStreetMap'
        if not data['features']:
            return RouteEstimate(status='unavailable', mode=mode, source=source,
                                 reason=f'No {names[mode]} route is available for these locations.').model_dump()
        try:
            props = data['features'][0]['properties']
            return RouteEstimate(status='available', mode=mode, source=source,
                                 minutes=math.ceil(float(props['time']) / 60), distance_meters=props['distance']).model_dump()
        except (KeyError, TypeError, ValueError, OverflowError):
            raise GeoapifyError('Geoapify returned invalid route details. Please try again.') from None
