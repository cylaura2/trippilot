"""Checkpointed coordination with live place/routing tools and deterministic checks."""
import os
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .checker import activity_pairs, check_schedule
from .durations import with_proposed_starts
from .geoapify import GeoapifyClient, SOURCE, specific_place_name
from .agents import LogisticsAnalyst, PlaceResearcher, generic_category
from .models import ProgressEvent, Trip, Usage
from .planner import DEFAULT_MODEL


class State(TypedDict, total=False):
    trip: dict
    places: dict
    findings: list[dict]
    events: list[dict]
    researched: bool
    checked: bool
    requests: list[str]
    next: str
    routes: dict
    data_source: str
    advised: bool
    suggestions: list[dict]
    agent_usage: dict
    agent_notes: list[str]
    agent_actions: list[dict]
    check_day: str | None


def materialize_suggestions(trip: Trip, places: dict) -> Trip:
    """Turn a selected generic meal/coffee placeholder into an editable named stop."""
    data = trip.model_dump(mode='json')
    for activity in data['activities']:
        target = specific_place_name(activity['name'])
        resolution = places.get(activity['id'], {})
        point = resolution.get('place') if resolution.get('status') == 'resolved' else None
        if (target != activity['name'] and point and not activity['fixed']
                and specific_place_name(point['name']) == point['name']
                and re.search(r'\b(cathedral|basilica|museum|church|palace|temple|gallery)\b', point['name'], re.I)
                and not re.search(r'\b(hotel|apartments?|cafe|restaurant)\b', point['name'], re.I)):
            activity['description'] = (activity['name'] + '. ' + activity['description']).strip()[:400]
            activity['name'] = point['name']
        category = generic_category(activity['name'])
        resolution = places.get(activity['id'], {})
        place = resolution.get('place') if resolution.get('status') == 'resolved' else None
        named_meal = re.match(r'^(breakfast|lunch|dinner|coffee) at .+$', activity['name'], re.I)
        if place and (category or named_meal) and not activity['fixed']:
            description = re.sub(r'(?i)\b(?:restaurant|cafe|place|venue)\s*(?::\s*)?(?:tbd|to be (?:decided|determined))\b[.!]?', '', activity['description'])
            description = re.sub(r'\(\s*\)', '', description)
            description = re.sub(r'\s+([.,;])', r'\1', description).strip()
            description = re.sub(r'(?i)^(?:breakfast|lunch|dinner|coffee|meal)\s+(?:near|around)\s+(?:the\s+)?hotel\s*[.;]?\s*', '', description).strip()
            activity['description'] = description
        if named_meal and place and not activity['fixed']:
            activity['name'] = f"{named_meal[1].title()} at {place['name']}"[:200]
        if not category or not place or activity['fixed']:
            continue
        meal = next((word for word in ('breakfast', 'lunch', 'dinner') if re.search(r'\b' + word + r'\b', activity['name'], re.I)),
                    'Coffee' if category == 'cafe' else 'Meal')
        activity['name'] = f"{meal.title()} at {place['name']}"[:200]
        description = re.sub(r'(?i)\b(?:restaurant|cafe|place|venue)\s*(?::\s*)?(?:tbd|to be (?:decided|determined))\b[.!]?', '', activity['description']).strip()
        activity['description'] = description or f'Suggested {category}. Change this stop if you prefer somewhere else.'
        activity['suggested'] = True
    return Trip.model_validate(data)


def analysis_trip(state: State) -> Trip:
    trip = Trip.model_validate(state['trip'])
    if not state.get('check_day'):
        return trip
    data = trip.model_dump(mode='json')
    data['start_date'] = data['end_date'] = state['check_day']
    data['activities'] = [a for a in data['activities'] if a['day'] == state['check_day']]
    return Trip.model_validate(data)


def event(state: State, worker: str, detail: str) -> list[dict]:
    return [*state.get("events", []), {"worker": worker, "detail": detail}]


def supervisor(state: State) -> dict:
    next_node = ("done" if state.get("advised") else "advice" if state.get("checked")
                 else "places" if state.get("requests") else "logistics")
    return {"next": next_node, "events": event(state, "Supervisor", f"Dispatch → {next_node}")}


def logistics(state: State, tools, emit=lambda event: None) -> dict:
    trip = analysis_trip(state)
    if not state.get("researched"):
        return {"requests": [a.id for a in trip.activities],
                "events": event(state, "Logistics analyst", "Requested place resolution before calculating transfers.")}
    routes = {}
    for current, following in activity_pairs(trip):
        origin = state['places'].get(current.id, {}).get('place')
        destination = state['places'].get(following.id, {}).get('place')
        if not origin or not destination:
            continue
        emit(ProgressEvent(stage='logistics', label='Logistics analyst', status='running', kind='tool',
                           detail=f'Comparing travel options: {current.name} → {following.name}.',
                           activity_id=current.id, destination_id=following.id).model_dump())
        routes[current.id] = tools.get_route(origin, destination)
        finding = next(f for f in check_schedule(trip, state['places'], routes) if f['source_id'] == current.id)
        emit({'type': 'transfer_update', 'activity_id': current.id, 'finding': finding})
    updated = with_proposed_starts(Trip.model_validate(state['trip']), routes, state.get('check_day'))
    if updated.model_dump(mode='json') != state['trip']:
        emit({'type': 'trip_update', 'trip': updated.model_dump(mode='json')})
    trip = analysis_trip({**state, 'trip': updated.model_dump(mode='json')})
    findings = check_schedule(trip, state["places"], routes)
    for finding in findings:
        emit({'type': 'transfer_update', 'activity_id': finding['source_id'], 'finding': finding})
    return {"trip": updated.model_dump(mode='json'), "findings": findings, "routes": routes, "checked": True,
            "events": event(state, "Logistics analyst", f"Checked {len(findings)} transfers; kept unresolved inputs explicit.")}


def research(state: State, tools, emit=lambda event: None) -> dict:
    trip = analysis_trip(state)
    places = {key: value for key, value in state.get('places', {}).items()
              if value.get('status') == 'resolved' and any(a['id'] == key for a in state['trip']['activities'])}
    confirmed_ids = frozenset(places)
    for index, activity in enumerate(trip.activities):
        emit(ProgressEvent(stage='places', label='Place researcher', status='running', kind='tool',
                           detail=f'Searching {index + 1}/{len(trip.activities)}: {activity.name}.', activity_id=activity.id).model_dump())
        if activity.id not in places:
            places[activity.id] = tools.search_place(activity.name, trip.city)
        if activity.id in confirmed_ids or not generic_category(activity.name):
            emit({'type': 'place_update', 'activity_id': activity.id, 'place': places[activity.id]})
    usage = Usage.model_validate(state.get('agent_usage') or {'model': os.environ.get('OPENAI_MODEL', DEFAULT_MODEL)})
    agent = PlaceResearcher(tools, emit, usage)
    places = agent.refine(trip, places, confirmed_ids)
    for activity in trip.activities:
        emit({'type': 'place_update', 'activity_id': activity.id, 'place': places[activity.id]})
    updated = materialize_suggestions(Trip.model_validate(state['trip']), places)
    if updated.model_dump(mode='json') != state['trip']:
        emit({'type': 'trip_update', 'trip': updated.model_dump(mode='json')})
    return {"trip": updated.model_dump(mode='json'), "places": places, "researched": True, "requests": [], "data_source": SOURCE,
            "agent_usage": usage.model_dump(), 'agent_notes': agent.notes, 'agent_actions': agent.actions,
            "events": [*event(state, "Place researcher", f'Searched {len(places)} locations using Geoapify; uncertain matches require confirmation.'),
                       {'worker': 'Place Researcher agent', 'stage': 'place_agent',
                        'status': 'complete' if agent.attempts else 'skipped',
                        'detail': f'{agent.attempts} reasoning attempts; {agent.search_actions} follow-up searches.'}]}


def advice(state: State, emit=lambda event: None) -> dict:
    usage = Usage.model_validate(state.get('agent_usage') or {'model': os.environ.get('OPENAI_MODEL', DEFAULT_MODEL)})
    suggestions, notes, actions = LogisticsAnalyst(emit, usage).suggest(
        analysis_trip(state), state['places'], state.get('routes', {}),
        state['findings'])
    return {'suggestions': suggestions, 'advised': True, 'agent_usage': usage.model_dump(),
            'agent_notes': [*state.get('agent_notes', []), *notes],
            'agent_actions': [*state.get('agent_actions', []), *actions],
            'events': [*state.get('events', []),
                       {'worker': 'Logistics Analyst agent', 'stage': 'logistics_agent',
                        'status': 'complete' if actions else 'skipped',
                        'detail': f'Prepared {len(suggestions)} checked timing alternatives; no bookings changed.'}]}


def needs_clarification(state: State) -> str:
    return "clarify" if any(p["status"] == "ambiguous" for p in state["places"].values()) else "supervisor"


def clarify(state: State, emit=lambda event: None) -> dict:
    activities = {a["id"]: a for a in state["trip"]["activities"]}
    questions = [{"activity_id": key, "name": activities[key]["name"], "candidates": place["candidates"],
                  'reason': place.get('reason', ''), 'proposed': place.get('proposed', False),
                  'recommended_id': place.get('recommended_id')}
                 for key, place in state["places"].items() if place["status"] == "ambiguous"]
    emit(ProgressEvent(stage="confirmation", label="Your confirmation", status="waiting",
                       detail="Confirm the intended locations from the search results.", kind="human").model_dump())
    choices = interrupt({"questions": questions})
    if not isinstance(choices, dict):
        raise ValueError("Submit a choice for each ambiguous location.")
    places = {key: dict(value) for key, value in state["places"].items()}
    for question in questions:
        key = question["activity_id"]
        selection = choices.get(key)
        candidate = next((p for p in question["candidates"] if p["id"] == selection), None)
        if selection != "unresolved" and candidate is None:
            raise ValueError("Choose a listed candidate or keep the location unresolved.")
        places[key] = {**places[key], "status": "resolved" if candidate else "unresolved", "place": candidate,
                       'reason': 'Location confirmed by you.' if candidate else 'Location left unresolved by you.'}
    emit(ProgressEvent(stage="confirmation", label="Your confirmation", status="complete",
                       detail="Your choices were applied. Fixed bookings stayed unchanged.", kind="human").model_dump())
    updated = materialize_suggestions(Trip.model_validate(state['trip']), places)
    emit({'type': 'trip_update', 'trip': updated.model_dump(mode='json')})
    return {"trip": updated.model_dump(mode='json'), "places": places, "events": event(state, "Human confirmation", "Applied location choices; reservation times stayed unchanged.")}


def build_graph(checkpointer, emit=lambda event: None, tools=None):
    tools = tools if tools is not None else GeoapifyClient()
    def observed(stage, label, kind, node):
        def run(state):
            emit(ProgressEvent(stage=stage, label=label, status="running",
                               detail=f"{label} is working.", kind=kind).model_dump())
            update = node(state)
            detail = next((item['detail'] for item in reversed(update['events']) if item['worker'] == label),
                          update['events'][-1]['detail'])
            emit(ProgressEvent(stage=stage, label=label, status="complete",
                               detail=detail, kind=kind).model_dump())
            return update
        return run
    graph = StateGraph(State)
    graph.add_node("supervisor", observed("supervisor", "Supervisor", "workflow", supervisor))
    graph.add_node("logistics", observed("logistics", "Logistics analyst", "workflow", lambda state: logistics(state, tools, emit)))
    graph.add_node("places", observed("places", "Place researcher", "tool", lambda state: research(state, tools, emit)))
    graph.add_node("clarify", lambda state: clarify(state, emit))
    graph.add_node('advice', lambda state: advice(state, emit))
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", lambda state: state["next"],
                                {"done": END, "places": "places", "logistics": "logistics", 'advice': 'advice'})
    graph.add_edge("logistics", "supervisor")
    graph.add_conditional_edges("places", needs_clarification)
    graph.add_edge("clarify", "supervisor")
    graph.add_edge('advice', 'supervisor')
    return graph.compile(checkpointer=checkpointer)
