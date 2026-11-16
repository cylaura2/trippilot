import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from trippilot.api import app
from trippilot.models import BuildRequest
from trippilot.planner import DraftDay, DraftPlan, DraftStop, ExtractedActivity, ParsedRequest, build_itinerary, resolve_context


def activity(name='Park Güell', start='09:00', duration=60, day=date(2026,11,20), evidence=None, duration_evidence=None):
    return ExtractedActivity(name=name,description=None,day=day,start=start,duration_minutes=duration,
                             duration_evidence=duration_evidence or evidence,
                             reservation='fixed' if evidence else 'flexible',reservation_evidence=evidence)


def parsed(activities=(), intent='import', start=date(2026,11,20), end=date(2026,11,20), city='Barcelona'):
    return ParsedRequest(intent=intent,city=city,timezone='Europe/Madrid',start_date=start,end_date=end,
                         activities=list(activities),question=None)


def draft(activities):
    days=sorted({item.day for item in activities})
    return DraftPlan(days=[DraftDay(day=day,activities=[DraftStop(name=item.name,description=item.description or '',start=item.start,duration_minutes=item.duration_minutes) for item in activities if item.day==day]) for day in days])


@pytest.fixture
def responses(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','unit-test-placeholder')
    client=MagicMock()
    monkeypatch.setattr('trippilot.planner.OpenAI',lambda **kwargs:client)
    parse=client.__enter__.return_value.responses.parse
    def supply(*outputs):
        parse.side_effect=[SimpleNamespace(status='completed',output_parsed=output,usage=SimpleNamespace(input_tokens=100,output_tokens=50)) for output in outputs]
        return parse
    return supply


def request(text='Barcelona November 20, 2026. Visit Park Güell.'):
    return BuildRequest(text=text,reference_date=date(2026,11,14))


def test_import_infers_context_and_preserves_missing_time(responses):
    text='Park Güell is booked. Casa Batlló at 2pm in Barcelona on November 20, 2026.'
    responses(parsed([activity(start=None,duration=None,evidence='Park Güell is booked.'),activity(name='Casa Batlló',start='14:00')]))
    events=[]
    result=build_itinerary(request(text),events.append)
    assert result.trip.activities[0].start is None
    assert result.trip.activities[0].duration_estimated and result.trip.activities[0].duration_minutes > 0
    assert result.trip.activities[0].fixed
    assert not result.trip.activities[1].fixed
    assert result.trip.origin=='imported'
    assert result.context.city=='Barcelona'
    assert result.trip.start_date==date(2026,11,20)
    assert result.usage.calls==1
    assert [event.get('stage') for event in events if event['type']=='progress' and event['status']=='running']==['reader','validation']


def test_import_zero_duration_placeholder_gets_a_proposed_length(responses):
    responses(parsed([activity(name='Airport arrival', duration=0), activity(name='Hotel check-in', start='15:00', duration=None)]))
    result = build_itinerary(request('Barcelona November 20, 2026: airport arrival at 9am; hotel check-in at 3pm.'))
    assert result.trip.activities[0].duration_estimated and result.trip.activities[0].duration_minutes > 0
    assert result.trip.activities[1].duration_estimated and result.trip.activities[1].duration_minutes > 0


def test_import_requires_source_evidence_for_positive_durations(responses):
    text = 'Barcelona November 20, 2026. Park Güell at 9am for 90 minutes. Hotel check-in at 3pm.'
    evidence = 'Park Güell at 9am for 90 minutes.'
    responses(parsed([activity(duration=90, duration_evidence=evidence),
                      activity(name='Hotel check-in', start='15:00', duration=30)]))
    result = build_itinerary(request(text))
    assert result.trip.activities[0].duration_minutes == 90
    assert result.trip.activities[1].duration_estimated and result.trip.activities[1].duration_minutes > 0
    assert not result.trip.activities[0].duration_estimated
    assert result.trip.activities[1].duration_estimated


def test_invented_duration_quote_is_not_accepted(responses):
    responses(parsed([activity(duration=90, duration_evidence='Visit for 90 minutes.')]))
    result = build_itinerary(request('Barcelona November 20, 2026. Visit Park Güell at 9am.'))
    assert result.trip.activities[0].duration_estimated and result.trip.activities[0].duration_minutes > 0


def test_start_time_quote_alone_does_not_justify_a_duration(responses):
    text = 'Barcelona November 20, 2026. Park Güell at 9am.'
    responses(parsed([activity(duration=90, duration_evidence='Park Güell at 9am.')]))
    assert build_itinerary(request(text)).trip.activities[0].duration_estimated


@pytest.mark.parametrize('evidence, duration', [('Park Güell for an hour.', 60),
                                            ('Park Güell: 90-minute visit.', 90),
                                            ('Park Güell 09:00–10:30.', 90),
                                            ('Park Güell from 9am to 10am.', 60)])
def test_explicit_duration_or_time_range_is_preserved(responses, evidence, duration):
    responses(parsed([activity(duration=duration, duration_evidence=evidence)]))
    result = build_itinerary(request('Barcelona November 20, 2026. ' + evidence))
    assert result.trip.activities[0].duration_minutes == duration


def test_stray_activity_year_is_rejected_without_automatic_repair(responses):
    responses(parsed([activity(day=date(1202,11,20), duration=0)], end=date(2026,11,24)))
    with pytest.raises(ValueError, match='falls outside'):
        build_itinerary(request('Barcelona November 20–24, 2026. Day 1, November 20: Park Güell at 9am.'))


def test_explicit_conflicting_year_is_not_silently_changed(responses):
    responses(parsed([activity(day=date(2027,11,20))]))
    with pytest.raises(ValueError, match='Please clarify'):
        build_itinerary(request('Barcelona November 20, 2026. Park Güell is booked for November 20, 2027.'))


@pytest.mark.parametrize('day', [date(1202,12,20), date(2026,11,21)])
def test_out_of_range_month_or_day_is_not_repaired(responses, day):
    responses(parsed([activity(day=day)]))
    with pytest.raises(ValueError, match='falls outside'):
        build_itinerary(request())


def test_ambiguous_year_repair_requires_clarification(responses):
    responses(parsed([activity(day=date(1202,11,20))], end=date(2027,11,21)))
    with pytest.raises(ValueError, match='Please clarify'):
        build_itinerary(request('Barcelona November 20, 2026 through November 21, 2027. Park Güell November 20.'))


def test_missing_dates_asks_instead_of_assuming_today(responses):
    parse=responses(parsed(intent='generate',start=None,end=None))
    events=[]
    result=build_itinerary(request("I'm going to Barcelona for a day"),events.append)
    assert result.trip is None
    assert 'date' in result.clarification
    assert result.context.city=='Barcelona'
    assert parse.call_count==1
    assert events[-1]['status']=='waiting'


def test_destination_timezone_overrides_browser_timezone():
    value=parsed()
    value.timezone='America/New_York'
    context,question=resolve_context(value)
    assert context.timezone=='Europe/Madrid'
    assert question is None


def test_disambiguated_city_is_not_given_the_wrong_known_timezone():
    value=parsed(city='Paris, Texas')
    value.timezone='America/Chicago'
    context,question=resolve_context(value)
    assert context.timezone=='America/Chicago'
    assert question is None


def test_long_import_is_not_truncated_to_draft_stop_limit(responses):
    responses(parsed([activity(name=f'Stop {index}') for index in range(40)]))
    result=build_itinerary(request())
    assert len(result.trip.activities)==40


def test_two_day_generation_covers_range_and_tracks_both_calls(responses):
    slots=[activity(name=f'Stop {day}-{index}',start=f'{9+index*3:02}:00',day=date(2026,11,day)) for day in (20,21) for index in range(3)]
    parse=responses(parsed(intent='generate',end=date(2026,11,21)),draft(slots))
    events=[]
    result=build_itinerary(request('Plan Barcelona November 20–21, 2026'),events.append)
    assert result.trip.origin=='generated'
    assert result.trip.end_date==date(2026,11,21)
    assert len(result.trip.activities)==6
    assert all(item.suggested and not item.fixed for item in result.trip.activities)
    assert result.usage.calls==2
    assert result.usage.input_tokens==200
    assert parse.call_count==2
    assert any(event.get('stage')=='planner' and event['status']=='running' for event in events)


def test_unbooked_ideas_do_not_become_required_draft_anchors(responses):
    slots=[activity(name=f'Stop {day}-{index}',start=f'{9+index*3:02}:00',day=date(2026,11,day)) for day in (20,21) for index in range(3)]
    responses(parsed([activity(name='Neighborhood walk',start=None,day=None)],intent='generate',end=date(2026,11,21)),draft(slots))
    result=build_itinerary(request('Plan relaxed neighborhood walks in Barcelona November 20–21, 2026'))
    assert result.trip is not None
    assert len(result.trip.activities)==6


def test_textual_null_is_not_a_valid_model_time():
    with pytest.raises(ValidationError):
        activity(start='null')


def test_generated_overlap_is_rejected(responses):
    responses(parsed(intent='generate'),draft([activity(start='09:00',duration=120),activity(start='10:00'),activity(start='13:00')]))
    with pytest.raises(ValueError,match='overlapping'):
        build_itinerary(request())


def test_fixed_booking_cannot_be_moved_by_planner(responses):
    text='Park Güell booked at 09:00 for 90 minutes. Plan around it in Barcelona November 20, 2026.'
    anchor=activity(start='09:00',duration=90,evidence='Park Güell booked at 09:00 for 90 minutes.')
    responses(parsed([anchor],intent='generate'),draft([activity(start='10:00',duration=90),activity(name='Lunch',start='13:00'),activity(name='Cathedral',start='15:00')]))
    with pytest.raises(ValueError,match='fixed booking'):
        build_itinerary(request(text))


def test_multiday_import_requires_activity_date(responses):
    responses(parsed([activity(day=None)],end=date(2026,11,21)))
    with pytest.raises(ValueError,match='add the date'):
        build_itinerary(request())


def test_missing_key_fails_before_model_call(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    with pytest.raises(ValueError,match='OPENAI_API_KEY'):
        build_itinerary(request())


def test_removed_template_fields_are_not_accepted():
    with pytest.raises(ValidationError):
        BuildRequest(text='Barcelona',reference_date=date(2026,11,14),use_ai=False,mode='template')


def test_build_stream_emits_progress_context_and_result(responses):
    responses(parsed([activity()]))
    with TestClient(app) as client:
        response=client.post('/api/build/stream',json={'text':'Barcelona November 20, 2026: Park Güell at 9am for 1 hour.','reference_date':'2026-11-14'})
        events=[json.loads(line) for line in response.text.splitlines() if line]
        assert events[0]['type']=='progress' and events[0]['status']=='running'
        assert any(event['type']=='context' for event in events)
        assert events[-1]['type']=='result'
        assert events[-1]['trip']['city']=='Barcelona'
        assert events[-1]['trip']['start_date']=='2026-11-20'


def test_error_stream_has_no_success_result(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    with TestClient(app) as client:
        response=client.post('/api/build/stream',json={'text':'Barcelona','reference_date':'2026-11-14'})
        events=[json.loads(line) for line in response.text.splitlines() if line]
        assert events[-1]['type']=='error'
        assert not any(event['type']=='result' for event in events)


def test_empty_import_requests_explicit_plan_instead_of_error(responses):
    responses(parsed([]))
    result = build_itinerary(request('Barcelona November 20, 2026. Travelers: 2.'))
    assert result.trip is None
    assert result.clarification_kind == 'empty_itinerary'
    assert 'draft' in result.clarification


def test_combined_neighborhood_walk_gets_one_explicit_landmark_anchor(responses):
    responses(parsed([activity(name='Gothic Quarter and Barcelona Cathedral', duration=None)]))
    result = build_itinerary(request('Barcelona November 20, 2026. At 5pm walk around the Gothic Quarter and Barcelona Cathedral.'))
    stop = result.trip.activities[0]
    assert stop.name == 'Barcelona Cathedral'
    assert 'Gothic Quarter' in stop.description
    assert stop.duration_estimated and stop.duration_minutes > 0


def test_combined_fixed_booking_name_stays_exact(responses):
    name = 'Gothic Quarter and Barcelona Cathedral'
    text = name + ' tour booked in Barcelona November 20, 2026 at 5pm.'
    responses(parsed([activity(name=name, duration=None, evidence=name + ' tour booked')]))
    stop = build_itinerary(request(text)).trip.activities[0]
    assert stop.name == name and stop.fixed


def test_build_request_cannot_carry_previous_plan_or_location_context():
    with TestClient(app) as client:
        result=client.post('/api/build/stream',json={'text':'Plan Barcelona November 20, 2026.',
            'reference_date':'2026-11-15','existing_trip':{'saved_restaurant':'Vinitus'}})
    assert result.status_code == 422
