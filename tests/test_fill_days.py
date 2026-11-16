from datetime import date
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from trippilot.api import app
from trippilot.models import Activity, BuildRequest, Trip
from trippilot.planner import DraftDay, DraftPlan, DraftStop, ParsedRequest, build_itinerary, fill_empty_days


def existing_trip():
    return Trip(city='Barcelona', timezone='Europe/Madrid', start_date=date(2026,11,20), end_date=date(2026,11,24),
                activities=[Activity(id='booked', name='Park Güell', day=date(2026,11,20), start='09:00',
                                     duration_minutes=90, fixed=True),
                            Activity(id='flexible', name='Lunch', day=date(2026,11,20), start='13:00')],
                input_text='Barcelona November 20–24, 2026. Keep November 20 as supplied.')


def draft_for(days):
    return DraftPlan(days=[DraftDay(day=day, activities=[DraftStop(name=f'Stop {i}', description='Suggested visit',
                          start=f'{9+i*3:02}:00', duration_minutes=60) for i in range(3)]) for day in days])


@pytest.fixture
def fake_model(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-placeholder')
    calls = []
    outputs = []
    def call(schema, instructions, text, usage, **kwargs):
        calls.append((schema, instructions, text))
        usage.calls += 1
        return outputs.pop(0)
    monkeypatch.setattr('trippilot.planner.call_model', call)
    return outputs, calls


def test_fill_keeps_all_existing_stops_and_drafts_only_empty_dates(fake_model):
    outputs, calls = fake_model
    trip = existing_trip()
    original = trip.model_dump()
    outputs.append(draft_for([date(2026,11,day) for day in range(21,25)]))
    result = fill_empty_days(trip)
    assert len(calls) == 1
    assert result.trip.activities[:2] == trip.activities
    assert trip.model_dump() == original
    assert len(result.trip.activities) == 14
    assert all(a.suggested and not a.fixed for a in result.trip.activities[2:])
    assert result.trip.start_date == trip.start_date and result.trip.end_date == trip.end_date
    assert len({a.id for a in result.trip.activities}) == 14
    assert result.trip.origin == 'imported'


def test_noncontiguous_empty_days_are_valid(fake_model):
    outputs, _ = fake_model
    trip = existing_trip()
    trip.activities.append(Activity(id='middle', name='Museum', day=date(2026,11,22)))
    outputs.append(draft_for([date(2026,11,day) for day in (21,23,24)]))
    assert len(fill_empty_days(trip).trip.activities) == 12


@pytest.mark.parametrize('days', [(20,21,22,23), (21,22,23), (21,22,23,25)])
def test_model_cannot_replace_existing_day_or_skip_or_add_dates(fake_model, days):
    outputs, _ = fake_model
    outputs.append(draft_for([date(2026,11,day) for day in days]))
    with pytest.raises(ValueError, match='each requested day'):
        fill_empty_days(existing_trip())


def test_no_empty_days_avoids_model_call(fake_model):
    _, calls = fake_model
    trip = existing_trip()
    trip.end_date = trip.start_date
    result = fill_empty_days(trip)
    assert result.trip is None and 'already has activities' in result.clarification
    assert calls == []


def test_fill_limit_checked_before_model_call(fake_model):
    _, calls = fake_model
    trip = existing_trip()
    trip.end_date = date(2026,12,20)
    with pytest.raises(ValueError, match='seven empty days'):
        fill_empty_days(trip)
    assert calls == []


def test_fresh_build_rejects_existing_itinerary_context():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match='existing_trip'):
        BuildRequest(text='Plan a new trip.', reference_date=date(2026,11,14), existing_trip=existing_trip())


def test_fill_stream_returns_preserved_stops_and_progress(fake_model):
    outputs, _ = fake_model
    trip = existing_trip()
    outputs.append(draft_for([date(2026,11,day) for day in range(21,25)]))
    with TestClient(app) as client:
        import json
        events = [json.loads(line) for line in client.post('/api/build/fill-days/stream',
                  json={'trip':trip.model_dump(mode='json')}).text.splitlines()]
    assert events[-1]['type'] == 'result'
    assert events[-1]['trip']['activities'][:2] == trip.model_dump(mode='json')['activities']
    assert any(e.get('stage') == 'planner' and e['status'] == 'running' for e in events)
    assert events[-2]['status'] == 'complete'


def test_default_model_and_reasoning_are_supported(monkeypatch):
    from types import SimpleNamespace
    from trippilot.models import Usage
    from trippilot.planner import DEFAULT_MODEL, call_model
    assert DEFAULT_MODEL == 'gpt-5.4-mini'
    with patch('trippilot.planner.OpenAI') as client:
        parse = client.return_value.__enter__.return_value.responses.parse
        parse.return_value = SimpleNamespace(status='completed', output_parsed='ok', usage=None)
        assert call_model(DraftPlan, 'instructions', 'synthetic input', Usage(model=DEFAULT_MODEL)) == 'ok'
        assert parse.call_args.kwargs['reasoning'] == {'effort':'low'}
        assert parse.call_args.kwargs['model'] == DEFAULT_MODEL
