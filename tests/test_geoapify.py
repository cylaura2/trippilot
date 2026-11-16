import io
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from trippilot import geoapify
from trippilot.api import app
from trippilot.checker import check_schedule
from trippilot.geoapify import GeoapifyClient, GeoapifyError


def feature(name='Park Güell', place_id='park', confidence=1, result_type='amenity', lat=41.4145):
    return {'properties': {'name': name, 'address_line1': name, 'formatted': name + ', Barcelona, Spain',
                           'place_id': place_id, 'lat': lat, 'lon': 2.1527, 'result_type': result_type,
                           'rank': {'confidence': confidence}}}


@pytest.fixture
def transport(monkeypatch):
    geoapify._cache.clear()
    monkeypatch.setattr(geoapify.time, 'sleep', lambda seconds: None)
    calls = []
    responses = []

    def send(request, timeout):
        calls.append(parse_qs(urlparse(request.full_url).query))
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(json.dumps(response).encode())

    monkeypatch.setattr(geoapify, 'urlopen', send)
    return responses, calls


def city():
    return {'features': [feature(name='Barcelona', result_type='city', lat=41.385)]}


def test_search_resolves_specific_match_and_reuses_cache(transport):
    responses, calls = transport
    responses.extend([city(), {'features': [feature()]}])
    client = GeoapifyClient('test-key')
    result = client.search_place('Park Guell', 'Barcelona')
    assert result['status'] == 'resolved'
    assert result['place']['address'] == 'Park Güell, Barcelona, Spain'
    assert result['source'] == 'Geoapify / OpenStreetMap'
    assert client.search_place('Park Guell', 'Barcelona') == result
    assert len(calls) == 2
    assert calls[1]['filter'][0].startswith('circle:')
    assert 'test-key' not in json.dumps(result)


@pytest.mark.parametrize('matches', [[feature(confidence=0.5)], [feature(), feature(place_id='other')]])
def test_uncertain_search_requires_confirmation(transport, matches):
    responses, _ = transport
    responses.extend([city(), {'features': matches}])
    result = GeoapifyClient('test-key').search_place('Park Güell', 'Barcelona')
    assert result['status'] == 'ambiguous'
    assert result['place'] is None
    assert result['candidates']


@pytest.mark.parametrize('matches', [[], [feature(result_type='city')], [feature(lat=48.85)]])
def test_no_match_centroids_and_wrong_city_stay_unresolved(transport, matches):
    responses, _ = transport
    responses.extend([city(), {'features': matches}])
    result = GeoapifyClient('test-key').search_place('Park Güell', 'Barcelona')
    assert result['status'] == 'unresolved'
    assert result['place'] is None


def test_routes_use_seconds_round_up_and_feed_checker(transport, trip):
    responses, calls = transport
    responses.append({'features': [{'properties': {'time': 1201, 'distance': 1500}}]})
    origin, destination = {'lat': 41.4, 'lng': 2.1}, {'lat': 41.39, 'lng': 2.2}
    route = GeoapifyClient('test-key').get_route(origin, destination)
    assert route['minutes'] == 21
    assert calls[0]['mode'] == ['walk']
    trip.activities = trip.activities[:2]
    places = {trip.activities[0].id: {'place': origin}, trip.activities[1].id: {'place': destination}}
    finding = check_schedule(trip, places, {trip.activities[0].id: route})[0]
    assert finding['slack_minutes'] == -6
    assert finding['status'] == 'conflict'
    assert 'Geoapify' in finding['evidence']


def test_unavailable_route_does_not_become_a_zero_minute_walk(transport):
    responses, _ = transport
    responses.extend([{'features': []}, {'features': []}, {'features': []}])
    result = GeoapifyClient('test-key').get_route({'lat': 41, 'lng': 2}, {'lat': 42, 'lng': 3})
    assert result['status'] == 'unavailable'
    assert result['minutes'] is None


@pytest.mark.parametrize('error, message', [
    (HTTPError('https://example.com/?apiKey=secret', 403, 'secret', {}, None), 'rejected the key'),
    (HTTPError('https://example.com/?apiKey=secret', 429, 'secret', {}, None), 'usage limit'),
    (URLError('secret'), 'Could not reach'),
])
def test_provider_failures_are_safe_and_not_retried(transport, error, message):
    responses, calls = transport
    responses.append(error)
    with pytest.raises(GeoapifyError, match=message) as raised:
        GeoapifyClient('secret').search_place('Park Güell', 'Barcelona')
    assert 'secret' not in str(raised.value)
    assert len(calls) == 1


def test_missing_key_never_calls_provider(transport):
    _, calls = transport
    with pytest.raises(GeoapifyError, match='GEOAPIFY_API_KEY'):
        GeoapifyClient('').search_place('Park Güell', 'Barcelona')
    assert calls == []


def test_nearby_search_is_bounded_and_needs_confirmation(transport):
    responses, calls = transport
    coffee = feature(name='Coffee stop', place_id='coffee')
    coffee['properties']['categories'] = ['catering.cafe']
    far = feature(name='Too far away', place_id='far', lat=48.85)
    far['properties']['categories'] = ['catering.cafe']
    responses.append({'features': [coffee, far, feature(name='Parking Park', place_id='parking')]})
    anchor = {'name': 'Park Güell', 'lat': 41.4145, 'lng': 2.1527}
    result = GeoapifyClient('test-key').search_nearby('cafe', anchor)
    assert result['status'] == 'ambiguous' and result['proposed']
    assert result['place'] is None
    assert [p['id'] for p in result['candidates']] == ['coffee']
    assert calls[0]['categories'] == ['catering.cafe']
    assert calls[0]['filter'][0].endswith(',1000')
    assert calls[0]['limit'] == ['5']


def test_nearby_rejects_unknown_categories_without_a_request(transport):
    _, calls = transport
    with pytest.raises(GeoapifyError, match='Unsupported'):
        GeoapifyClient('test-key').search_nearby('invented', {'lat': 41, 'lng': 2})
    assert calls == []


def test_api_live_adapter_confirmation_resume_and_restore(transport, trip, tmp_path, monkeypatch):
    responses, calls = transport
    monkeypatch.setenv('GEOAPIFY_API_KEY', 'test-key')
    monkeypatch.setenv('TRIPPILOT_DATA_DIR', str(tmp_path))
    trip.activities = trip.activities[:2]
    responses.extend([city(), {'features': [feature()]},
                      {'features': [feature(name='Casa Batlló', place_id='casa', confidence=0.5, lat=41.3917)]},
                      {'features': [{'properties': {'time': 1201, 'distance': 1500}}]}])
    original = trip.model_dump(mode='json')
    with TestClient(app) as client:
        events = [json.loads(line) for line in client.post('/api/runs/stream', json={'trip': original}).text.splitlines()]
        paused = events[-1]['run']
        assert paused['status'] == 'needs_confirmation'
        assert paused['questions'][0]['activity_id'] == trip.activities[1].id
        assert len(calls) == 3  # City search is shared from the first lookup.
        responses_before_resume = len(calls)
        events = [json.loads(line) for line in client.post(f"/api/runs/{paused['id']}/resume/stream",
                  json={'choices': {trip.activities[1].id: 'casa'}}).text.splitlines()]
        complete = events[-1]['run']
        assert len(calls) == responses_before_resume + 1  # Resume does not repeat place research.
        assert complete['status'] == 'complete'
        assert complete['trip'] == original
        assert complete['findings'][0]['travel_minutes'] == 21
        assert 'Geoapify' in complete['data_source']
        assert client.get(f"/api/runs/{paused['id']}").json() == complete


def test_api_provider_error_keeps_credentials_out_of_stream(transport, trip, tmp_path, monkeypatch):
    responses, _ = transport
    monkeypatch.setenv('GEOAPIFY_API_KEY', 'private-value')
    monkeypatch.setenv('TRIPPILOT_DATA_DIR', str(tmp_path))
    responses.append(HTTPError('https://example.com/?apiKey=private-value', 403, 'private-value', {}, None))
    with TestClient(app) as client:
        result = client.post('/api/runs/stream', json={'trip': trip.model_dump(mode='json')})
        assert 'private-value' not in result.text
        event = json.loads(result.text.splitlines()[-1])
        assert event['type'] == 'error'
        assert 'rejected the key' in event['message']


def test_exact_named_match_ignores_unrelated_results(transport):
    responses, calls = transport
    responses.extend([city(), {'features': [feature('El Nacional'), feature('Other restaurant', 'other')]}])
    result = GeoapifyClient('test-key').search_place('Lunch at El Nacional', 'Barcelona')
    assert result['status'] == 'resolved'
    assert result['place']['name'] == 'El Nacional'
    assert 'lunch at' not in calls[1]['text'][0].lower()


def route_response(minutes, meters=1000):
    return {'features': [{'properties': {'time': minutes * 60, 'distance': meters}}]}


def test_long_walk_compares_transit_and_car_with_allowances(transport):
    responses, calls = transport
    responses.extend([route_response(70), route_response(20), route_response(18)])
    result = GeoapifyClient('test-key').get_route({'lat':41.4,'lng':2.1}, {'lat':41.3,'lng':2.2})
    assert result['mode'] == 'approximated_transit'
    assert result['minutes'] == 25 and result['allowance_minutes'] == 5
    assert [c['mode'][0] for c in calls] == ['walk','approximated_transit','drive']


def test_airport_length_trip_prefers_car_when_transit_is_much_slower(transport):
    responses, _ = transport
    responses.extend([route_response(180), route_response(60), route_response(25)])
    result = GeoapifyClient('test-key').get_route({'lat':41.4,'lng':2.1}, {'lat':41.3,'lng':2.2})
    assert result['mode'] == 'drive' and result['minutes'] == 30


def test_small_saving_keeps_a_reasonable_walk(transport):
    responses, _ = transport
    responses.extend([route_response(30), route_response(25), route_response(20)])
    result = GeoapifyClient('test-key').get_route({'lat':41.4,'lng':2.1}, {'lat':41.3,'lng':2.2})
    assert result['mode'] == 'walk' and result['minutes'] == 30


def test_optional_transit_error_does_not_discard_car_route(transport):
    responses, _ = transport
    responses.extend([route_response(120), HTTPError('https://example.com',400,'unsupported',{},None), route_response(25)])
    result = GeoapifyClient('test-key').get_route({'lat':41.4,'lng':2.1}, {'lat':41.3,'lng':2.2})
    assert result['mode'] == 'drive' and result['minutes'] == 30


def test_combined_walk_searches_the_explicit_landmark_not_a_business_string(transport):
    responses, calls = transport
    responses.extend([city(), {'features': [feature('Barcelona Cathedral', 'cathedral')]}])
    result = GeoapifyClient('test-key').search_place('Gothic Quarter and Barcelona Cathedral', 'Barcelona')
    assert result['status'] == 'resolved' and result['place']['id'] == 'cathedral'
    assert 'gothic' not in calls[1]['text'][0].lower()
    assert 'cathedral' in calls[1]['text'][0].lower()


@pytest.mark.parametrize('name', ['Victoria and Albert Museum','Rock and Roll Hall of Fame','Hotel Jazz Barcelona'])
def test_specific_lookup_preserves_single_venue_names(name):
    assert geoapify.specific_place_name(name) == name


def test_explicit_street_walk_requires_confirmation_of_a_starting_pin(transport):
    responses, _ = transport
    responses.extend([city(), {'features':[feature('Passeig de Gràcia','avenue',result_type='street')]}])
    result = GeoapifyClient('test-key').search_place('Passeig de Gràcia, Barcelona','Barcelona')
    assert result['status'] == 'ambiguous' and result['place'] is None
    assert result['candidates'][0]['walk_anchor']
    assert 'starting point' in result['reason']
    assert geoapify.confident_place(result,'Passeig de Gràcia','Barcelona') is None


@pytest.mark.parametrize('query,returned',[
    ('Park Güell','Park Güell'),
    ('Passeig de Gràcia 43','Passeig de Gràcia'),
    ('Passeig de Gràcia','Another Street'),
    ('Oxford Street Museum','Oxford Street Museum'),
])
def test_street_centroid_never_substitutes_for_a_venue_address_or_other_street(transport,query,returned):
    responses, _ = transport
    responses.extend([city(), {'features':[feature(returned,result_type='street')]}])
    assert GeoapifyClient('test-key').search_place(query,'Barcelona')['status'] == 'unresolved'


def test_stroll_prefix_is_removed_for_matching_without_fabricating_a_venue(transport):
    responses,calls=transport
    responses.extend([city(), {'features':[feature('Passeig de Gràcia','avenue',result_type='street')]}])
    result=GeoapifyClient('test-key').search_place('Stroll along the Passeig de Gràcia','Barcelona')
    assert calls[1]['text']==['passeig de gracia, Barcelona']
    assert result['candidates'][0]['walk_anchor']
