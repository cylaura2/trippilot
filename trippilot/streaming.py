"""Deliver real execution events while blocking model/tool work runs in one worker thread."""
import json
from queue import Empty, Full, Queue
from threading import Event, Thread
from typing import Callable, Iterator

from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import ValidationError


def public_error(error: Exception) -> str:
    if isinstance(error, APITimeoutError):
        return 'The model request timed out. No automatic retry was made.'
    if isinstance(error, APIConnectionError):
        return 'Could not reach the model provider. Please try again.'
    if isinstance(error, APIStatusError):
        return f'The model provider returned HTTP {error.status_code}. Check model access and API billing.'
    if isinstance(error, ValidationError):
        fields = {str(part) for item in error.errors(include_input=False, include_url=False) for part in item['loc']}
        if 'duration_minutes' in fields:
            detail = 'An activity has an invalid duration. Use a positive number of minutes, or leave it blank if unknown.'
        elif 'start' in fields:
            detail = 'An activity has an invalid start time. Use a local time in HH:MM format, or leave it blank if unknown.'
        elif fields & {'day', 'start_date', 'end_date'}:
            detail = 'An itinerary date is invalid. Check the day, month, and year.'
        elif 'description' in fields or 'name' in fields:
            detail = 'An activity name or description is too long or missing. Use a short place name and description.'
        else:
            detail = 'The itinerary data could not be validated. Check the trip details.'
        return detail + ' Your current plan was kept.'
    if isinstance(error, ValueError):
        return str(error)
    return 'This step could not finish. Your current itinerary has been kept.'


def stream_job(job: Callable) -> Iterator[str]:
    queue = Queue(maxsize=64)
    stopped = Event()
    finished = object()

    def emit(event):
        while not stopped.is_set():
            try:
                queue.put(event, timeout=0.25)
                return
            except Full:
                continue
        raise RuntimeError('Client disconnected')

    def work():
        try:
            result = job(emit)
            emit({'type': 'result', **result})
        except Exception as error:
            if not stopped.is_set():
                emit({'type': 'error', 'message': public_error(error)})
        finally:
            if not stopped.is_set():
                emit(finished)

    Thread(target=work, daemon=True, name='trippilot-job').start()
    try:
        while True:
            try:
                event = queue.get(timeout=10)
            except Empty:
                yield json.dumps({'type': 'heartbeat'}) + '\n'
                continue
            if event is finished:
                return
            yield json.dumps(event, ensure_ascii=False) + '\n'
    finally:
        stopped.set()
