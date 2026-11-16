import json
from threading import Event

import pytest
from pydantic import ValidationError

from trippilot.models import Activity
from trippilot.streaming import public_error, stream_job


def test_progress_is_delivered_before_work_finishes():
    release=Event()
    def job(emit):
        emit({'type':'progress','stage':'reader','status':'running'})
        if not release.wait(timeout=3):
            raise RuntimeError('The consumer failed to receive progress.')
        return {'ready':True}
    stream=stream_job(job)
    first=json.loads(next(stream))
    assert first['type']=='progress'
    release.set()
    final=json.loads(next(stream))
    assert final=={'type':'result','ready':True}
    assert list(stream)==[]


@pytest.mark.parametrize('change, expected', [
    ({'duration_minutes': 0}, 'invalid duration'),
    ({'start': '25:00'}, 'invalid start time'),
    ({'day': '2026-02-30'}, 'date is invalid'),
    ({'description': 'x' * 401}, 'name or description'),
])
def test_validation_errors_identify_the_field_without_echoing_input(change, expected):
    data = {'id': 'private-id', 'name': 'private activity', 'day': '2026-11-20', **change}
    with pytest.raises(ValidationError) as raised:
        Activity.model_validate(data)
    message = public_error(raised.value)
    assert expected in message
    assert 'private-id' not in message and 'private activity' not in message
    assert 'Your current plan was kept.' in message
