import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from trippilot import agents
from trippilot.agents import LogisticsAnalyst, PlaceAction, PlaceResearcher, RankedRepairs
from trippilot.api import app
from trippilot.checker import check_schedule
from trippilot.models import TimingSuggestion, Usage
from trippilot.repairs import apply_timing, timing_options
from trippilot.workflow import build_graph


def candidate(id='park', name='Park Güell', confidence=1):
    return {'id': id, 'name': name, 'address': name + ', Barcelona', 'lat': 41.4, 'lng': 2.1, 'confidence': confidence}


def resolution(status='resolved', candidates=None):
    candidates = [candidate()] if candidates is None else candidates
    return {'status': status, 'place': candidates[0] if status == 'resolved' else None,
            'candidates': candidates, 'source': 'Test provider', 'reason': ''}


def action(kind='finish', **kwargs):
    return PlaceAction(action=kind, query=kwargs.get('query'), category=kwargs.get('category'),
                       anchor_activity_id=kwargs.get('anchor_activity_id'), candidate_id=kwargs.get('candidate_id'))


class Tools:
    def __init__(self):
        self.searches = []
        self.nearby = []

    def search_place(self, query, city):
        self.searches.append((query, city))
        return resolution(candidates=[candidate(query, query, confidence=0.8)])

    def search_nearby(self, category, anchor):
        self.nearby.append((category, anchor))
        cafe = {**candidate('cafe', 'A real café'), 'categories': ['catering.cafe']}
        return {**resolution('ambiguous', [cafe]), 'proposed': True}

    def get_route(self, origin, destination):
        return {'status': 'available', 'minutes': 45, 'source': 'Test walking estimate'}


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'unit-test-placeholder')
    monkeypatch.setattr(agents, 'MAX_PLACE_CALLS', 6)
    monkeypatch.setattr(agents, 'MAX_ADVICE_CALLS', 1)
    outputs, inputs = [], []

    def call(schema, instructions, text, usage, max_output_tokens):
        inputs.append(json.loads(text))
        usage.calls += 1
        usage.input_tokens += 100
        usage.output_tokens += 20
        result = outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(agents, 'call_model', call)
    return outputs, inputs


def test_refinement_observes_tool_results_and_requires_confirmation(trip, model):
    outputs, inputs = model
    trip.activities = trip.activities[:1]
    tools = Tools()
    outputs.extend([action('search', query='Parc Güell'), action(candidate_id='Parc Güell')])
    places = {trip.activities[0].id: resolution('unresolved', [])}
    original = trip.model_dump()
    agent = PlaceResearcher(tools, lambda e: None, Usage(model='test'))
    result = agent.refine(trip, places)[trip.activities[0].id]
    assert tools.searches == [('Parc Güell', 'Barcelona')]
    assert inputs[1]['result']['candidates'][0]['id'] == 'Parc Güell'
    assert result['status'] == 'ambiguous' and result['place'] is None
    assert result['recommended_id'] == 'Parc Güell'
    assert trip.model_dump() == original


def test_nearby_search_uses_confirmed_anchor_and_stays_a_suggestion(trip, model):
    outputs, _ = model
    trip.activities = trip.activities[:2]
    trip.activities[1].name = 'Coffee near Park Güell'
    outputs.extend([action('nearby', category='cafe', anchor_activity_id=trip.activities[0].id), action(candidate_id='cafe')])
    places = {trip.activities[0].id: resolution(), trip.activities[1].id: resolution('unresolved', [])}
    tools = Tools()
    result = PlaceResearcher(tools, lambda e: None, Usage(model='test')).refine(trip, places)[trip.activities[1].id]
    assert tools.nearby[0][1]['id'] == 'park'
    assert result['proposed'] and result['status'] == 'ambiguous'
    assert result['recommended_id'] == 'cafe'


def test_invented_anchor_cannot_trigger_a_search(trip, model):
    outputs, _ = model
    trip.activities = trip.activities[:1]
    outputs.append(action('nearby', category='cafe', anchor_activity_id='invented'))
    tools = Tools()
    agent = PlaceResearcher(tools, lambda e: None, Usage(model='test'))
    places = agent.refine(trip, {trip.activities[0].id: resolution('unresolved', [])})
    assert tools.nearby == [] and tools.searches == []
    assert places[trip.activities[0].id]['status'] == 'unresolved'
    assert agent.actions[-1]['action'] == 'rejected'


def test_invented_candidate_is_not_recommended(trip, model):
    outputs, _ = model
    trip.activities = trip.activities[:1]
    outputs.append(action(candidate_id='invented'))
    result = PlaceResearcher(Tools(), lambda e: None, Usage(model='test')).refine(
        trip, {trip.activities[0].id: resolution('ambiguous')})[trip.activities[0].id]
    assert result.get('recommended_id') is None
    assert result['place'] is None


def test_parking_candidate_cannot_be_recommended_for_coffee(trip, model):
    outputs, inputs = model
    trip.activities = trip.activities[:1]
    trip.activities[0].name = 'Coffee near Park Güell'
    outputs.append(action(candidate_id='parking'))
    parking = {**candidate('parking', 'Parking Park'), 'categories': ['parking']}
    result = PlaceResearcher(Tools(), lambda e: None, Usage(model='test')).refine(
        trip, {trip.activities[0].id: resolution('ambiguous', [parking])})[trip.activities[0].id]
    assert inputs[0]['result']['candidates'] == []
    assert result['status'] == 'unresolved' and not result.get('recommended_id')


def test_explicit_nearby_anchor_cannot_be_replaced_with_another_landmark(trip, model):
    outputs, _ = model
    trip.activities = trip.activities[:2]
    trip.activities[1].name = 'Coffee near the cathedral'
    outputs.append(action('nearby', category='cafe', anchor_activity_id=trip.activities[0].id))
    tools = Tools()
    result = PlaceResearcher(tools, lambda e: None, Usage(model='test')).refine(
        trip, {trip.activities[0].id: resolution(), trip.activities[1].id: resolution('unresolved', [])})
    assert tools.nearby == []
    assert result[trip.activities[1].id]['status'] == 'unresolved'


def test_nearby_constraint_in_description_is_preserved(trip, model):
    outputs, _ = model
    trip.activities = trip.activities[:2]
    trip.activities[1].name = 'coffee'
    trip.activities[1].description = 'coffee near the cathedral'
    outputs.append(action('nearby', category='cafe', anchor_activity_id=trip.activities[0].id))
    tools = Tools()
    result = PlaceResearcher(tools, lambda e: None, Usage(model='test')).refine(
        trip, {trip.activities[0].id: resolution(), trip.activities[1].id: resolution('unresolved', [])})
    assert tools.nearby == []
    assert 'landmark' in result[trip.activities[1].id]['reason']


def test_model_failure_keeps_evidence_and_stops_further_calls(trip, model):
    outputs, inputs = model
    outputs.append(RuntimeError('private provider details'))
    places = {a.id: resolution('ambiguous') for a in trip.activities}
    before = deepcopy(places)
    agent = PlaceResearcher(Tools(), lambda e: None, Usage(model='test'))
    assert agent.refine(trip, places) == before
    assert len(inputs) == 1
    assert 'private provider details' not in str(agent.notes)


def test_run_budget_and_per_stop_turns_are_enforced(trip, model, monkeypatch):
    outputs, inputs = model
    monkeypatch.setattr(agents, 'MAX_PLACE_CALLS', 3)
    outputs.extend([action('search', query='first'), action('search', query='second'), action()])
    tools = Tools()
    agent = PlaceResearcher(tools, lambda e: None, Usage(model='test'))
    agent.refine(trip, {a.id: resolution('unresolved', []) for a in trip.activities})
    assert len(inputs) == 3 and agent.attempts == 3
    assert len(tools.searches) == 2
    assert agent.notes


def test_repeated_tool_action_is_not_executed_twice(trip, model):
    outputs, _ = model
    trip.activities = trip.activities[:1]
    outputs.extend([action('search', query='same'), action('search', query='same')])
    tools = Tools()
    agent = PlaceResearcher(tools, lambda e: None, Usage(model='test'))
    agent.refine(trip, {trip.activities[0].id: resolution('unresolved', [])})
    assert len(tools.searches) == 1


def repair_inputs(trip):
    trip.activities = trip.activities[:2]
    trip.activities[1].fixed = False
    places = {a.id: resolution(candidates=[candidate(a.id, a.name)]) for a in trip.activities}
    routes = {trip.activities[0].id: {'status': 'available', 'minutes': 45, 'source': 'Test walking estimate'}}
    return places, routes, check_schedule(trip, places, routes)


def test_timing_option_fixes_conflict_without_changing_fixed_booking(trip):
    places, routes, findings = repair_inputs(trip)
    options = timing_options(trip, places, routes, findings)
    assert len(options) == 1
    assert options[0].proposed_start == '11:15'
    changed = apply_timing(trip, options[0])
    assert changed.activities[0] == trip.activities[0]
    assert check_schedule(changed, places, routes)[0]['status'] == 'fits'
    assert trip.activities[1].start == '10:45'


def test_fixed_bookings_and_stale_suggestions_cannot_be_applied(trip):
    places, routes, findings = repair_inputs(trip)
    suggestion = timing_options(trip, places, routes, findings)[0]
    trip.activities[1].fixed = True
    with pytest.raises(ValueError, match='flexible stop'):
        apply_timing(trip, suggestion)
    assert timing_options(trip, places, routes, findings) == []
    trip.activities[1].fixed = False
    trip.activities[1].start = '11:00'
    with pytest.raises(ValueError, match='no longer matches'):
        apply_timing(trip, suggestion)


def test_repair_is_rejected_if_it_creates_a_downstream_conflict(trip):
    third = trip.activities[2].model_copy(update={'start': '12:00'})
    places, routes, _ = repair_inputs(trip)
    trip.activities.append(third)
    places[third.id] = resolution(candidates=[candidate(third.id, third.name)])
    routes[trip.activities[1].id] = {'status': 'available', 'minutes': 5, 'source': 'Test walking estimate'}
    findings = check_schedule(trip, places, routes)
    assert findings[1]['status'] == 'fits'
    assert timing_options(trip, places, routes, findings) == []


def test_model_can_only_rank_existing_checked_options(trip, model):
    outputs, _ = model
    outputs.append(RankedRepairs(option_ids=['invented', 'option_1', 'option_1']))
    places, routes, findings = repair_inputs(trip)
    original = trip.model_dump()
    suggestions, _, actions = LogisticsAnalyst(lambda e: None, Usage(model='test')).suggest(trip, places, routes, findings)
    assert [s['id'] for s in suggestions] == ['option_1']
    assert actions[0]['option_ids'] == ['option_1']
    assert trip.model_dump() == original


def test_agent_decisions_survive_confirmation_restart(trip, model, tmp_path):
    outputs, inputs = model
    trip.activities = trip.activities[:2]
    outputs.append(action(candidate_id=trip.activities[1].name))
    tools = Tools()
    tools.search_place = lambda query, city: resolution('resolved' if query == trip.activities[0].name else 'ambiguous', [candidate(query, query, confidence=0.8)])
    config = {'configurable': {'thread_id': 'agent-restart'}}
    path = str(tmp_path / 'agents.sqlite')
    with SqliteSaver.from_conn_string(path) as saver:
        result = build_graph(saver, tools=tools).invoke({'trip': trip.model_dump(mode='json')}, config)
        assert result['__interrupt__']
        assert result['agent_usage']['calls'] == 1
    with SqliteSaver.from_conn_string(path) as saver:
        result = build_graph(saver, tools=tools).invoke(Command(resume={trip.activities[1].id: trip.activities[1].name}), config)
        assert result['advised'] and result['checked']
        assert result['agent_usage']['calls'] == 1
        assert len(inputs) == 1


def test_apply_endpoint_rechecks_preserving_original_and_place_choices(trip, tmp_path, monkeypatch):
    monkeypatch.setenv('TRIPPILOT_DATA_DIR', str(tmp_path))
    tools = Tools()
    monkeypatch.setattr('trippilot.workflow.GeoapifyClient', lambda: tools)
    trip.activities = trip.activities[:2]
    trip.activities[1].fixed = False
    with TestClient(app) as client:
        original = [json.loads(line) for line in client.post('/api/runs/stream', json={'trip': trip.model_dump(mode='json')}).text.splitlines()][-1]['run']
        assert len(original['suggestions']) == 1
        searches = len(tools.searches)
        response = client.post(f"/api/runs/{original['id']}/suggestions/option_1/apply/stream")
        updated = [json.loads(line) for line in response.text.splitlines()][-1]['run']
        assert updated['id'] != original['id']
        assert updated['trip']['activities'][0] == original['trip']['activities'][0]
        assert updated['trip']['activities'][1]['start'] == '11:15'
        assert updated['findings'][0]['status'] == 'fits'
        assert len(tools.searches) == searches
        assert client.get(f"/api/runs/{original['id']}").json() == original
        assert client.post(f"/api/runs/{original['id']}/suggestions/invented/apply/stream").status_code == 404


def test_confirmed_generic_stop_is_not_reopened(trip, model):
    outputs, inputs = model
    trip.activities = trip.activities[:1]
    stop = trip.activities[0]
    stop.name = 'coffee near Park Güell'
    place = {**candidate('cafe', 'Chosen cafe'), 'categories': ['catering.cafe']}
    places = {stop.id: resolution('resolved', [place])}
    before = deepcopy(places)
    result = PlaceResearcher(Tools(), lambda e: None, Usage(model='test')).refine(trip, places, frozenset({stop.id}))
    assert result == before
    assert not inputs


def test_flexible_generic_meal_gets_editable_default_suggestion(trip, model):
    outputs, _ = model
    trip.activities = trip.activities[:2]
    trip.activities[1].name = 'Coffee near Park Güell'
    trip.activities[1].fixed = False
    outputs.extend([action('nearby', category='cafe', anchor_activity_id=trip.activities[0].id), action(candidate_id='cafe')])
    places = {trip.activities[0].id: resolution(), trip.activities[1].id: resolution('unresolved', [])}
    result = PlaceResearcher(Tools(), lambda e: None, Usage(model='test')).refine(trip, places)[trip.activities[1].id]
    assert result['status'] == 'resolved' and result['proposed']
    assert result['place']['name'] == 'A real café'
    assert 'edit' in result['reason']


def test_default_cafe_updates_checkpointed_trip_without_a_confirmation_panel(trip, model, tmp_path):
    outputs, _ = model
    trip.activities = trip.activities[:2]
    trip.activities[1].name = 'Coffee near Park Güell'
    trip.activities[1].description = 'Cafe TBD.'
    trip.activities[1].fixed = False
    original = trip.model_dump(mode='json')
    tools = Tools()
    def search(name, city):
        return resolution() if name == trip.activities[0].name else resolution('unresolved', [])
    tools.search_place = search
    outputs.extend([action('nearby', category='cafe', anchor_activity_id=trip.activities[0].id), action(candidate_id='cafe')])
    events = []
    with SqliteSaver.from_conn_string(str(tmp_path/'defaults.sqlite')) as saver:
        graph = build_graph(saver, events.append, tools)
        result = graph.invoke({'trip':original},{'configurable':{'thread_id':'default-cafe'}})
        assert not result.get('__interrupt__')
        updated = result['trip']['activities'][1]
        assert updated['name'] == 'Coffee at A real café' and updated['suggested']
        assert 'TBD' not in updated['description']
        assert updated['start'] == original['activities'][1]['start']
        assert result['trip']['activities'][0] == original['activities'][0]
        assert any(e['type']=='trip_update' for e in events)


def test_repairs_do_not_propose_moving_a_flight_arrival_earlier(trip):
    trip.activities=trip.activities[:2]
    trip.activities[0].name='Barcelona-El Prat Airport'
    trip.activities[0].description='Arrive at Terminal 1.'
    trip.activities[0].fixed=False
    trip.activities[1].fixed=True
    places,routes,findings=repair_inputs(trip)
    trip.activities[1].fixed=True
    assert timing_options(trip,places,routes,findings)==[]


def test_named_restaurant_is_not_reopened_by_generic_description(trip, model):
    _, inputs = model
    trip.activities = trip.activities[:1]
    trip.activities[0].name = 'vinitus'
    trip.activities[0].description = 'Dinner near the waterfront with a walk along the port afterwards.'
    named = resolution(candidates=[candidate('vinitus', 'Vinitus')])
    tools = Tools()
    result = PlaceResearcher(tools, lambda e: None, Usage(model='test')).refine(
        trip, {trip.activities[0].id:named})
    assert result[trip.activities[0].id] == named
    assert not inputs and not tools.nearby


def test_uncertain_named_restaurant_uses_name_not_old_nearby_description(trip, model):
    outputs, inputs = model
    trip.activities = trip.activities[:2]
    trip.activities[1].name = 'vinitus'
    trip.activities[1].description = 'Dinner near the waterfront with a walk along the port afterwards.'
    outputs.append(action(candidate_id='vinitus'))
    tools = Tools()
    named = resolution('ambiguous', [candidate('vinitus', 'Vinitus')])
    result = PlaceResearcher(tools, lambda e: None, Usage(model='test')).refine(
        trip, {trip.activities[0].id:resolution(),trip.activities[1].id:named})
    assert inputs[0]['required_category'] is None
    assert inputs[0]['available_anchors']
    assert result[trip.activities[1].id]['status'] == 'resolved'
    assert result[trip.activities[1].id]['place']['name'] == 'Vinitus'
    assert not tools.nearby


def test_street_walk_pin_waits_for_human_without_model_search(trip,model):
    _,inputs=model
    trip.activities=trip.activities[:1]
    trip.activities[0].name='Passeig de Gràcia'
    point={**candidate('avenue','Passeig de Gràcia'),'walk_anchor':True}
    initial=resolution('ambiguous',[point])
    tools=Tools()
    result=PlaceResearcher(tools,lambda event:None,Usage(model='test')).refine(trip,{trip.activities[0].id:initial})
    assert result[trip.activities[0].id]==initial
    assert not inputs and not tools.searches and not tools.nearby
