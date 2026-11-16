from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from trippilot import photos
from trippilot.api import app


@pytest.fixture
def transport(monkeypatch):
    photos._cache.clear()
    monkeypatch.setattr(photos, 'request_openverse', lambda query: {'results': []})
    calls = []
    pages = {'query': {'pages': [{'title': 'Casa Batlló', 'coordinates': [{'lat': 41.3917, 'lon': 2.1649}], 'pageimage': 'Casa.jpg'}]}}
    image = {'query': {'pages': [{'imageinfo': [{'thumburl': 'https://thumb.wikimedia.org/casa.jpg',
        'descriptionurl': 'https://commons.wikimedia.org/wiki/File:Casa.jpg',
        'extmetadata': {'Artist': {'value': '<a>Photographer &amp; friend</a>'}, 'LicenseShortName': {'value': 'CC BY-SA 4.0'},
                        'LicenseUrl': {'value': 'https://creativecommons.org/licenses/by-sa/4.0/'}}}]}]}}
    responses = [pages, image]
    def request(host, **params):
        calls.append((host, params))
        value = responses.pop(0)
        if isinstance(value, Exception): raise value
        return deepcopy(value)
    monkeypatch.setattr(photos, 'request_json', request)
    return responses, calls


def place(**kwargs):
    return photos.PhotoRequest(**{'name': 'Visit Casa Batlló', 'matched_name': 'Casa Batlló', 'city': 'Barcelona',
                                 'lat': 41.3917, 'lng': 2.1649, **kwargs})


def test_grounded_photo_credit_and_cache(transport):
    _, calls = transport
    result = photos.photo_for(place())
    assert result['status'] == 'available'
    assert result['photo']['author'] == 'Photographer & friend'
    assert photos.photo_for(place()) == result
    assert len(calls) == 2


@pytest.mark.parametrize('change', ['name', 'coordinates'])
def test_does_not_use_unrelated_or_distant_photo(transport, change):
    responses, calls = transport
    page = responses[0]['query']['pages'][0]
    if change == 'name': page['title'] = 'Other building'
    else: page['coordinates'][0]['lat'] = 48.85
    assert photos.photo_for(place())['photo'] is None
    assert len(calls) == 1


def test_provider_failure_is_optional_and_cached(transport):
    responses, calls = transport
    responses[:] = [TimeoutError()]
    assert photos.photo_for(place()) == {'status': 'unavailable', 'photo': None}
    assert photos.photo_for(place())['status'] == 'unavailable'
    assert len(calls) == 1


def test_untrusted_image_url_is_rejected(transport):
    responses, _ = transport
    responses[1]['query']['pages'][0]['imageinfo'][0]['thumburl'] = 'https://example.com/wrong.jpg'
    assert photos.photo_for(place())['status'] == 'missing'


def test_photo_endpoint_validation_and_response(transport):
    with TestClient(app) as client:
        assert client.post('/api/places/photo', json=place().model_dump()).json()['status'] == 'available'
        assert client.post('/api/places/photo', json={**place().model_dump(), 'lat': 200}).status_code == 422


def openverse_result(**changes):
    return {**{'title': 'Casa Batlló Barcelona', 'creator': 'Photographer', 'license': 'by', 'license_version': '4.0',
        'license_url': 'https://creativecommons.org/licenses/by/4.0/', 'mature': False, 'tags': [],
        'thumbnail': 'https://images.example.com/casa.jpg', 'foreign_landing_url': 'https://example.com/casa'}, **changes}


def test_openverse_fallback_keeps_license_credit_and_place_match(transport, monkeypatch):
    responses, _ = transport
    responses[0] = {'query': {'pages': []}}
    queries = []
    def search(query):
        queries.append(query)
        return {'results': [openverse_result(title='Other building Barcelona'), openverse_result()]}
    monkeypatch.setattr(photos, 'request_openverse', search)
    result = photos.photo_for(place())
    assert result['status'] == 'available'
    assert result['photo']['provider'] == 'Openverse'
    assert result['photo']['author'] == 'Photographer'
    assert result['photo']['license'] == 'by 4.0'
    assert queries == ['"Casa Batlló" Barcelona']
    assert photos.photo_for(place()) == result
    assert len(queries) == 1


@pytest.mark.parametrize('changes', [
    {'title': 'Unrelated building Barcelona'}, {'title': 'Casa Batlló elsewhere'},
    {'license': 'by-nc'}, {'license': 'by-nd'}, {'mature': True},
    {'thumbnail': 'https://127.0.0.1/image.jpg'}, {'thumbnail': 'http://example.com/image.jpg'},
    {'foreign_landing_url': 'https://localhost/private'}, {'creator': None},
])
def test_openverse_rejects_unmatched_or_unusable_results(transport, monkeypatch, changes):
    responses, _ = transport
    responses[0] = {'query': {'pages': []}}
    monkeypatch.setattr(photos, 'request_openverse', lambda query: {'results': [openverse_result(**changes)]})
    assert photos.photo_for(place())['photo'] is None


def test_openverse_can_recover_from_wikipedia_failure(transport, monkeypatch):
    responses, _ = transport
    responses[:] = [TimeoutError()]
    monkeypatch.setattr(photos, 'request_openverse', lambda query: {'results': [openverse_result()]})
    assert photos.photo_for(place())['status'] == 'available'


def test_openverse_unavailable_does_not_break_planning(transport, monkeypatch):
    responses, _ = transport
    responses[0] = {'query': {'pages': []}}
    def fail(query): raise TimeoutError()
    monkeypatch.setattr(photos, 'request_openverse', fail)
    assert photos.photo_for(place()) == {'status': 'unavailable', 'photo': None}


def test_destination_background_is_searched_on_demand_and_prefers_public_domain(transport, monkeypatch):
    calls = []
    def search(query, licenses, wide):
        calls.append((query,licenses,wide))
        return {'results':[openverse_result(title='Barcelona skyline',license='cc0',license_version='1.0')]}
    monkeypatch.setattr(photos,'request_openverse',search)
    result=photos.destination_photo('Barcelona')
    assert result['photo']['attribution_required'] is False
    assert calls == [('"Barcelona" skyline','cc0,pdm',True)]
    assert photos.destination_photo('Barcelona') == result and len(calls)==1


def test_destination_search_rejects_wrong_city_and_keeps_required_credit(transport, monkeypatch):
    def search(query, licenses, wide):
        return {'results':[openverse_result(title='Paris skyline'),openverse_result(title='Barcelona skyline')]}
    monkeypatch.setattr(photos,'request_openverse',search)
    result=photos.destination_photo('Barcelona')
    assert result['photo']['title']=='Barcelona skyline'
    assert result['photo']['attribution_required'] is True


def test_missing_destination_photo_keeps_a_generic_background(transport, monkeypatch):
    monkeypatch.setattr(photos,'request_openverse',lambda *args,**kwargs:{'results':[]})
    with TestClient(app) as client:
        assert client.post('/api/destination/photo',json={'city':'Unknown place'}).json()=={'status':'missing','photo':None}


def test_name_only_search_starts_before_location_confirmation(transport, monkeypatch):
    monkeypatch.setattr(photos, 'request_json', lambda *args, **kwargs: pytest.fail('No coordinate search before location confirmation'))
    monkeypatch.setattr(photos, 'request_openverse', lambda query: {'results':[openverse_result()]})
    request = place().model_dump()
    request.pop('lat'); request.pop('lng')
    result = photos.photo_for(photos.PhotoRequest(**request))
    assert result['status'] == 'available'
    assert result['photo']['provider'] == 'Openverse'


@pytest.mark.parametrize('original,expected',[
    ('https://images.example.com/original.jpg','https://images.example.com/original.jpg'),
    ('http://localhost/private.jpg','https://images.example.com/casa.jpg'),
])
def test_openverse_original_photo_must_be_a_public_https_url(transport,monkeypatch,original,expected):
    responses,_=transport
    responses[0]={'query':{'pages':[]}}
    monkeypatch.setattr(photos,'request_openverse',lambda query:{'results':[openverse_result(url=original)]})
    assert photos.photo_for(place())['photo']['full_url']==expected


@pytest.mark.parametrize('original,expected',[
    ('https://upload.wikimedia.org/original.jpg','https://upload.wikimedia.org/original.jpg'),
    ('https://untrusted.example.com/original.jpg','https://thumb.wikimedia.org/casa.jpg'),
])
def test_wikimedia_original_is_restricted_to_its_image_host(transport,original,expected):
    responses,_=transport
    responses[1]['query']['pages'][0]['imageinfo'][0]['url']=original
    assert photos.photo_for(place())['photo']['full_url']==expected
