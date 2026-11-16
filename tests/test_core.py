import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import ValidationError

from trippilot.api import app
from trippilot.checker import check_schedule
from tests.fixture_tools import lookup_place, route_minutes
from trippilot.models import Trip
from trippilot.workflow import build_graph


class SampleTools:
    search_place = staticmethod(lookup_place)

    def get_route(self, origin, destination):
        minutes = route_minutes(origin['id'], destination['id'])
        return {'status': 'available' if minutes is not None else 'unavailable',
                'minutes': minutes, 'source': 'Synthetic test fixture'}


@pytest.fixture(autouse=True)
def offline_tools(monkeypatch):
    monkeypatch.setattr('trippilot.workflow.GeoapifyClient', SampleTools)


def sample_routes(trip):
    places = resolved_places(trip)
    return {a.id: SampleTools().get_route(places[a.id]['place'], places[b.id]['place'])
            for a, b in zip(trip.activities, trip.activities[1:])}


def resolved_places(trip):
    places = {activity.id: lookup_place(activity.name, trip.city) for activity in trip.activities}
    if 'activity_3' in places:
        places['activity_3']['place'] = places['activity_3']['candidates'][0]
        places['activity_3']['status'] = 'resolved'
    return places


def test_conflicts_use_duration_and_travel_only(trip):
    findings = check_schedule(trip, resolved_places(trip), sample_routes(trip))
    assert [finding['status'] for finding in findings] == ['conflict','conflict','fits']
    assert [finding['slack_minutes'] for finding in findings] == [-30,-10,52]


def test_missing_inputs_never_invent_routes(trip):
    trip.activities[0].duration_minutes = None
    trip.activities[1].start = None
    findings = check_schedule(trip, {})
    assert all(finding['status'] == 'unknown' for finding in findings)
    assert all(finding['travel_minutes'] is None for finding in findings)


def test_overlap_detected_without_locations(trip):
    trip.activities[0].duration_minutes = 120
    finding = check_schedule(trip, {})[0]
    assert finding['status'] == 'conflict'
    assert 'overlap by 15' in finding['message']


def test_unknown_city_stays_unresolved():
    assert lookup_place('Park Güell','London')['status'] == 'unresolved'


def test_different_days_do_not_create_sightseeing_transfers(trip):
    trip.activities = trip.activities[:2]
    trip.activities[0].start, trip.activities[0].duration_minutes = '23:00',30
    trip.activities[1].day, trip.activities[1].start = date(2026,11,21),'00:30'
    assert check_schedule(trip, resolved_places(trip), sample_routes(trip)) == []


@pytest.mark.parametrize('day',['2026-03-29','2026-10-25'])
def test_dst_transition_requires_correction(trip, day):
    data = trip.model_dump(mode='json')
    data['start_date'], data['end_date'] = day, day
    for activity in data['activities']:
        activity['day'] = day
    data['activities'][0]['start'] = '02:30'
    with pytest.raises(ValidationError, match='daylight-saving'):
        Trip.model_validate(data)


def test_activity_ids_and_date_range_are_validated(trip):
    data = trip.model_dump(mode='json')
    data['activities'][1]['id'] = data['activities'][0]['id']
    with pytest.raises(ValidationError, match='unique IDs'):
        Trip.model_validate(data)
    data = trip.model_dump(mode='json')
    data['end_date'] = '2026-11-19'
    with pytest.raises(ValidationError, match='end date'):
        Trip.model_validate(data)


def test_restart_safe_confirmation_emits_real_handoffs(trip, tmp_path):
    path = str(tmp_path/'checkpoints.sqlite')
    original = trip.model_dump(mode='json')
    config = {'configurable':{'thread_id':'persistent-test'}}
    events = []
    with SqliteSaver.from_conn_string(path) as saver:
        result = build_graph(saver, events.append).invoke({'trip':original,'events':[]},config)
        assert result['__interrupt__']
        assert any(event.get('stage')=='confirmation' and event['status']=='waiting' for event in events)
        assert any(event.get('stage')=='places' and event['status']=='running' for event in events)
        assert 'findings' not in result
    with SqliteSaver.from_conn_string(path) as saver:
        result = build_graph(saver,events.append).invoke(Command(resume={'activity_3':'sol_old'}),config)
        assert result['checked']
        assert result['trip']==original
        assert len(result['findings'])==3
        assert any(event.get('stage')=='confirmation' and event['status']=='complete' for event in events)


def stream_events(response):
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_api_stream_pause_invalid_choice_resume_restore(trip, tmp_path, monkeypatch):
    monkeypatch.setenv('TRIPPILOT_DATA_DIR',str(tmp_path))
    with TestClient(app) as client:
        response = client.post('/api/runs/stream',json={'trip':trip.model_dump(mode='json')})
        assert response.status_code==200
        events = stream_events(response)
        assert events[0]['type']=='run_created'
        paused = events[-1]['run']
        assert paused['status']=='needs_confirmation'
        run_id=paused['id']
        assert client.post(f'/api/runs/{run_id}/resume/stream',json={'choices':{'activity_3':'invented'}}).status_code==422
        resumed = stream_events(client.post(f'/api/runs/{run_id}/resume/stream',json={'choices':{'activity_3':'unresolved'}}))[-1]['run']
        assert resumed['status']=='complete'
        assert resumed['findings'][1]['status']=='unknown'
        assert client.get(f'/api/runs/{run_id}').json()==resumed
        assert client.get('/api/runs/not-a-real-id').status_code==404


def test_route_estimate_survives_missing_duration_and_time(trip):
    places = resolved_places(trip)
    routes = sample_routes(trip)
    trip.activities[0].duration_minutes = None
    finding = check_schedule(trip, places, routes)[0]
    assert finding['status'] == 'unknown'
    assert finding['travel_minutes'] == routes['activity_1']['minutes']
    assert 'Add the duration' in finding['message']
    assert 'min walk' in finding['evidence']
    assert finding['slack_minutes'] is None
    trip.activities[0].start = None
    finding = check_schedule(trip, places, routes)[0]
    assert finding['status'] == 'unknown'
    assert finding['travel_minutes'] is not None
    assert 'both start times' in finding['message']


def test_workflow_requests_routes_without_schedule_inputs(trip):
    from trippilot.workflow import logistics
    calls = []
    class Tools:
        def get_route(self, origin, destination):
            calls.append((origin['id'], destination['id']))
            return {'status': 'available', 'minutes': 20, 'source': 'Test route provider'}
    places = resolved_places(trip)
    for activity in trip.activities:
        activity.duration_minutes = None
        activity.start = None
    result = logistics({'trip': trip.model_dump(mode='json'), 'places': places,
                        'researched': True}, Tools())
    assert len(calls) == 3
    assert all(f['travel_minutes'] == 20 and f['status'] == 'fits' for f in result['findings'])
    assert all(f['slack_minutes'] == 0 for f in result['findings'])
    assert all(a['start_estimated'] and a['duration_estimated'] for a in result['trip']['activities'])


def test_workflow_streams_stop_and_transfer_updates(trip, tmp_path):
    events = []
    trip.activities = trip.activities[:2]
    with SqliteSaver.from_conn_string(str(tmp_path/'live.sqlite')) as saver:
        result = build_graph(saver, events.append, SampleTools()).invoke(
            {'trip': trip.model_dump(mode='json')},
            {'configurable': {'thread_id': 'live-stops'}})
    places = [e for e in events if e['type'] == 'place_update']
    transfers = [e for e in events if e['type'] == 'transfer_update']
    assert {e['activity_id'] for e in places} == {'activity_1', 'activity_2'}
    assert all(e['place']['status'] == 'resolved' for e in places)
    assert transfers[-1]['finding'] == result['findings'][0]
    assert any(e.get('activity_id') == 'activity_1' and e.get('stage') == 'logistics' for e in events)
    assert events.index(places[0]) < events.index(transfers[0])


def test_logistics_checks_proposed_lengths_against_travel_without_moving_starts(trip):
    from trippilot.workflow import logistics
    trip.activities=trip.activities[:2]
    trip.activities[0].name='Airport arrival';trip.activities[0].start='09:20'
    trip.activities[0].duration_minutes=90;trip.activities[0].duration_estimated=True
    trip.activities[1].start='10:30'
    places={a.id:{'status':'resolved','place':{'id':a.id,'name':a.name,'lat':41,'lng':2}} for a in trip.activities}
    class Tools:
        def get_route(self,origin,destination):return {'status':'available','minutes':22,'mode':'drive','source':'Test route'}
    original = trip.model_dump(mode='json')
    events = []
    result=logistics({'trip':original,'places':places,'researched':True},Tools(),events.append)
    assert result['trip'] == original
    assert trip.model_dump(mode='json') == original
    assert result['findings'][0]['status']=='conflict'
    assert result['findings'][0]['travel_minutes']==22
    assert not any(e.get('type') == 'trip_update' for e in events)
