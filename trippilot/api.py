"""FastAPI endpoints for prompt builds, streamed workflow runs, and restoration."""
import os
import re
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .library import router as library_router
from .geoapify import specific_place_name
from .models import BuildRequest, FillDaysRequest, ResumeRequest, RunRequest, TimingSuggestion, Trip
from .photos import PhotoRequest, photo_for, DestinationPhotoRequest, destination_photo
from .durations import with_proposed_durations, with_proposed_starts
from .checker import check_schedule
from .repairs import timing_options
from .repairs import apply_timing
from .planner import DEFAULT_MODEL, build_itinerary, fill_empty_days
from .streaming import stream_job
from .workflow import build_graph, materialize_suggestions

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
app = FastAPI(title='TripPilot', version='0.3.0')
app.include_router(library_router)


@contextmanager
def graph_session(emit=lambda event: None):
    directory = Path(os.environ.get('TRIPPILOT_DATA_DIR', str(ROOT / '.data')))
    directory.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(directory / 'checkpoints.sqlite')) as saver:
        yield build_graph(saver, emit)


def config(run_id: str) -> dict:
    if not re.fullmatch(r'[0-9a-f]{32}', run_id):
        raise HTTPException(404, 'Analysis not found.')
    return {'configurable': {'thread_id': run_id}, 'recursion_limit': 20}


def present(graph, run_id: str) -> dict:
    snapshot = graph.get_state(config(run_id))
    if not snapshot.values:
        raise HTTPException(404, 'Analysis not found.')
    state = snapshot.values
    raw_trip = dict(state['trip'])
    if raw_trip.get('origin') == 'demo':
        raw_trip['origin'] = 'imported'
    trip = with_proposed_durations(materialize_suggestions(Trip.model_validate(raw_trip), state.get('places', {})))
    if state.get('checked'):
        trip = with_proposed_starts(trip, state.get('routes', {}), state.get('check_day'))
    findings = state.get('findings', [])
    suggestions = state.get('suggestions', [])
    if state.get('checked') and (any(before.get('duration_minutes') != after.duration_minutes or before.get('start') != after.start for before,after in zip(raw_trip['activities'],trip.activities)) or any('min buffer' in f['message'] for f in findings)):
        scoped = trip.model_dump(mode='json')
        if state.get('check_day'):
            scoped['activities'] = [a for a in scoped['activities'] if a['day'] == state['check_day']]
        checked_trip = Trip.model_validate(scoped)
        findings = check_schedule(checked_trip, state.get('places', {}), state.get('routes', {}))
        suggestions = [s.model_dump(mode='json') for s in timing_options(checked_trip,state.get('places',{}),state.get('routes',{}),findings)[:3]]
    questions = [question for task in snapshot.tasks for interruption in task.interrupts
                 for question in interruption.value.get('questions', [])]
    return {'id': run_id, 'trip': trip.model_dump(mode='json'),
            'day': state.get('check_day'),
            'places': state.get('places', {}), 'findings': findings,
            'suggestions': suggestions, 'agent_usage': state.get('agent_usage'),
            'agent_notes': [('This saved check paused automatic place matching. Recheck to use updated matching; confirmed locations will be kept.'
                             if note == 'Place reasoning limit reached or unavailable. Remaining matches were left for your review.' else note)
                            for note in state.get('agent_notes', [])], 'agent_actions': state.get('agent_actions', []),
            'events': state.get('events', []), 'questions': questions,
            'status': 'needs_confirmation' if questions else 'complete' if state.get('checked') else 'incomplete',
            'data_source': state.get('data_source', 'Unknown source on this saved check; recheck to refresh location and route data.')}


def response_for(job):
    return StreamingResponse(stream_job(job), media_type='application/x-ndjson',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.get('/api/config')
def get_config():
    return {'ai_available': bool(os.environ.get('OPENAI_API_KEY')),
            'places_available': bool(os.environ.get('GEOAPIFY_API_KEY')),
            'model': os.environ.get('OPENAI_MODEL', DEFAULT_MODEL)}


@app.post('/api/places/photo')
def place_photo(request: PhotoRequest):
    return photo_for(request)


@app.post('/api/destination/photo')
def destination_background(request: DestinationPhotoRequest):
    return destination_photo(request.city)


@app.get('/api/health')
def health():
    return {'status': 'ok'}


@app.post('/api/build/stream')
def build_plan(request: BuildRequest):
    return response_for(lambda emit: build_itinerary(request, emit).model_dump(mode='json'))


@app.post('/api/build/fill-days/stream')
def fill_days(request: FillDaysRequest):
    return response_for(lambda emit: fill_empty_days(request.trip, emit=emit).model_dump(mode='json'))


@app.post('/api/runs/stream')
def start_run(request: RunRequest):
    places = {}
    if request.previous_run_id:
        with graph_session() as graph:
            try:
                previous = present(graph, request.previous_run_id)
            except HTTPException as error:
                if error.status_code != 404:
                    raise
                previous = None
        if previous and previous['trip']['city'] == request.trip.city:
            old = {a['id']: a for a in previous['trip']['activities']}
            for activity in request.trip.activities:
                before = old.get(activity.id)
                result = previous['places'].get(activity.id, {})
                if (before and specific_place_name(activity.name) == activity.name and result.get('status') == 'resolved' and result.get('place')
                        and (before['name'], before.get('description', ''), before['day']) ==
                        (activity.name, activity.description, activity.day.isoformat())):
                    places[activity.id] = result
    return start_analysis(with_proposed_durations(request.trip), places,
                          day=request.day.isoformat() if request.day else None)


def start_analysis(trip: Trip, places: dict | None = None, day: str | None = None, locations_ready: bool = False):
    def run(emit):
        run_id = uuid4().hex
        emit({'type': 'run_created', 'run_id': run_id})
        with graph_session(emit) as graph:
            graph.invoke({'trip': trip.model_dump(mode='json'),
                          'places': places or {}, 'events': [], 'findings': [], 'researched': locations_ready,
                          'checked': False, 'advised': False, 'requests': [],
                          'data_source': 'Geoapify / OpenStreetMap', 'check_day': day}, config(run_id))
            return {'run': present(graph, run_id)}
    return response_for(run)


@app.post('/api/runs/{run_id}/suggestions/{suggestion_id}/apply/stream')
def apply_suggestion(run_id: str, suggestion_id: str):
    with graph_session() as graph:
        current = present(graph, run_id)
    if current['status'] != 'complete':
        raise HTTPException(409, 'Finish checking the itinerary before applying a suggestion.')
    raw = next((s for s in current['suggestions'] if s['id'] == suggestion_id), None)
    if raw is None:
        raise HTTPException(404, 'Timing suggestion not found.')
    try:
        trip = apply_timing(Trip.model_validate(current['trip']), TimingSuggestion.model_validate(raw))
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    # Only the time changed; retain explicit place choices and fetch fresh/cached routes.
    return start_analysis(trip, current['places'], current.get('day'), locations_ready=True)


@app.get('/api/runs/{run_id}')
def get_run(run_id: str):
    with graph_session() as graph:
        return present(graph, run_id)


@app.post('/api/runs/{run_id}/resume/stream')
def resume_run(run_id: str, request: ResumeRequest):
    config(run_id)
    with graph_session() as graph:
        current = present(graph, run_id)
        if current['status'] != 'needs_confirmation':
            raise HTTPException(409, 'This analysis is not waiting for confirmation.')
        for question in current['questions']:
            allowed = {candidate['id'] for candidate in question['candidates']} | {'unresolved'}
            if request.choices.get(question['activity_id']) not in allowed:
                raise HTTPException(422, 'Choose a listed candidate or keep the location unresolved.')
    def resume(emit):
        with graph_session(emit) as graph:
            graph.invoke(Command(resume=request.choices), config(run_id))
            return {'run': present(graph, run_id)}
    return response_for(resume)


frontend = ROOT / 'frontend' / 'dist'
if frontend.is_dir():
    app.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')
