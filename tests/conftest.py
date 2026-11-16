from datetime import date

import pytest

from trippilot.models import Activity, Trip


@pytest.fixture(autouse=True)
def offline_agent_budget(monkeypatch):
    # Legacy tests never make unmocked model calls. Agent-specific tests override these.
    monkeypatch.setattr('trippilot.agents.MAX_PLACE_CALLS', 0)
    monkeypatch.setattr('trippilot.agents.MAX_ADVICE_CALLS', 0)


@pytest.fixture
def trip():
    return Trip(city='Barcelona', timezone='Europe/Madrid', start_date=date(2026,11,20), end_date=date(2026,11,20), activities=[
        Activity(id='activity_1', name='Park Güell', day=date(2026,11,20), start='09:00', duration_minutes=90, fixed=True),
        Activity(id='activity_2', name='Casa Batlló', day=date(2026,11,20), start='10:45', duration_minutes=60, fixed=True),
        Activity(id='activity_3', name='Lunch at Sol', day=date(2026,11,20), start='12:00', duration_minutes=60, fixed=True),
        Activity(id='activity_4', name='Barcelona Cathedral', day=date(2026,11,20), start='14:00', duration_minutes=60),
    ])
