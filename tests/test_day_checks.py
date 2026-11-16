import json
from datetime import date

from fastapi.testclient import TestClient

from trippilot.api import app
from trippilot.models import Activity, Trip


class Tools:
    def __init__(self): self.searched=[]
    def search_place(self,name,city):
        self.searched.append(name)
        place={'id':name,'name':name,'address':city,'lat':41.4,'lng':2.1}
        return {'status':'resolved','place':place,'candidates':[place],'source':'Test'}
    def get_route(self,origin,destination):
        return {'status':'available','minutes':45,'source':'Test walking estimate'}


def last(response):
    return json.loads(response.text.splitlines()[-1])['run']


def test_check_day_and_apply_keep_other_days_intact(tmp_path,monkeypatch):
    tools=Tools()
    monkeypatch.setattr('trippilot.workflow.GeoapifyClient',lambda:tools)
    monkeypatch.setenv('TRIPPILOT_DATA_DIR',str(tmp_path))
    trip=Trip(city='Barcelona',timezone='Europe/Madrid',activities=[
        Activity(id='one',name='First day stop',day=date(2026,11,20),start='09:00',duration_minutes=60),
        Activity(id='two',name='Second day fixed stop',day=date(2026,11,21),start='09:00',duration_minutes=90,fixed=True),
        Activity(id='three',name='Second day flexible stop',day=date(2026,11,21),start='10:45',duration_minutes=60)])
    original=trip.model_dump(mode='json')
    with TestClient(app) as client:
        run=last(client.post('/api/runs/stream',json={'trip':original,'day':'2026-11-21'}))
        assert tools.searched==['Second day fixed stop','Second day flexible stop']
        assert run['trip']==original and run['day']=='2026-11-21'
        assert len(run['findings'])==1 and run['findings'][0]['source_id']=='two'
        updated=last(client.post(f"/api/runs/{run['id']}/suggestions/{run['suggestions'][0]['id']}/apply/stream"))
        assert updated['day']=='2026-11-21'
        assert updated['trip']['activities'][:2]==original['activities'][:2]
        assert updated['trip']['activities'][2]['start']=='11:15'
        assert updated['findings'][0]['status']=='fits'
        assert len(tools.searched)==2
        assert client.post('/api/runs/stream',json={'trip':original,'day':'2026-11-22'}).status_code==422


def test_recheck_reuses_only_unchanged_confirmed_locations(tmp_path, monkeypatch, trip):
    tools = Tools()
    monkeypatch.setattr('trippilot.workflow.GeoapifyClient', lambda: tools)
    monkeypatch.setenv('TRIPPILOT_DATA_DIR', str(tmp_path))
    raw = trip.model_dump(mode='json')
    with TestClient(app) as client:
        first = last(client.post('/api/runs/stream', json={'trip': raw}))
        tools.searched.clear()
        second = last(client.post('/api/runs/stream', json={'trip': raw, 'previous_run_id': first['id']}))
        assert not tools.searched
        assert second['places'] == first['places']
        raw['activities'][0]['name'] = 'Changed place'
        last(client.post('/api/runs/stream', json={'trip': raw, 'previous_run_id': second['id']}))
        assert tools.searched == ['Changed place']


def test_changed_restaurant_rechecks_location_and_updates_map_data(tmp_path, monkeypatch, trip):
    tools = Tools()
    def search(name,city):
        tools.searched.append(name)
        changed = name == 'Dinner at Vinitus'
        place={'id':'vinitus' if changed else name,'name':'Vinitus' if changed else name,
               'address':city,'lat':41.39 if changed else 41.4,'lng':2.16 if changed else 2.1}
        return {'status':'resolved','place':place,'candidates':[place],'source':'Test'}
    tools.search_place = search
    monkeypatch.setattr('trippilot.workflow.GeoapifyClient', lambda:tools)
    monkeypatch.setenv('TRIPPILOT_DATA_DIR', str(tmp_path))
    trip.activities[-1].name = 'Dinner at Alt Heidelberg'
    with TestClient(app) as client:
        first=last(client.post('/api/runs/stream', json={'trip':trip.model_dump(mode='json')}))
        tools.searched.clear()
        edited=first['trip']
        edited['activities'][-1]['name']='Dinner at Vinitus'
        second=last(client.post('/api/runs/stream',json={'trip':edited,'previous_run_id':first['id']}))
        assert tools.searched == ['Dinner at Vinitus']
        place=second['places'][trip.activities[-1].id]['place']
        assert place['id']=='vinitus' and place['lat']==41.39
        assert second['status']=='complete' and second['findings']
        assert second['trip']['activities'][-1]['name']=='Dinner at Vinitus'


def test_combined_walk_does_not_reuse_old_apartment_match(tmp_path, monkeypatch, trip):
    tools = Tools()
    current_name = ['Ainb Gothic Cathedral Apartments']
    original_search = tools.search_place
    combined = 'Gothic Quarter and Barcelona Cathedral'
    def search(name, city):
        result = original_search(name, city)
        if name == combined:
            result['place'] = {**result['place'],'id':current_name[0],'name':current_name[0]}
            result['candidates'] = [result['place']]
        return result
    tools.search_place = search
    monkeypatch.setattr('trippilot.workflow.GeoapifyClient',lambda:tools)
    monkeypatch.setenv('TRIPPILOT_DATA_DIR',str(tmp_path))
    trip.activities[-1].name = combined
    with TestClient(app) as client:
        first = last(client.post('/api/runs/stream',json={'trip':trip.model_dump(mode='json')}))
        assert first['trip']['activities'][-1]['name'] == combined
        tools.searched.clear()
        current_name[0] = 'Barcelona Cathedral'
        second = last(client.post('/api/runs/stream',json={'trip':first['trip'],'previous_run_id':first['id']}))
        assert tools.searched == [combined]
        assert second['places'][trip.activities[-1].id]['place']['name'] == 'Barcelona Cathedral'
        assert second['trip']['activities'][-1]['name'] == 'Barcelona Cathedral'


def test_api_fills_missing_visit_lengths_and_has_no_travel_buffer(tmp_path, monkeypatch, trip):
    tools=Tools()
    monkeypatch.setattr('trippilot.workflow.GeoapifyClient',lambda:tools)
    monkeypatch.setenv('TRIPPILOT_DATA_DIR',str(tmp_path))
    trip.activities[-1].duration_minutes=None
    with TestClient(app) as client:
        run=last(client.post('/api/runs/stream',json={'trip':trip.model_dump(mode='json')}))
        assert run['trip']['activities'][-1]['duration_minutes']>0
        assert run['trip']['activities'][-1]['duration_estimated']
        assert 'buffer_minutes' not in run
        assert all('buffer' not in finding['message'] for finding in run['findings'])
        assert client.post('/api/runs/stream',json={'trip':trip.model_dump(mode='json'),'buffer_minutes':10}).status_code==422


def test_saved_legacy_plan_is_upgraded_without_stale_missing_length_messages(trip):
    from types import SimpleNamespace
    from trippilot.api import present
    trip.activities=trip.activities[:2]
    trip.activities[0].duration_minutes=None
    place={'id':'test','name':'Named place','lat':41.4,'lng':2.1}
    state={'trip':trip.model_dump(mode='json'),'checked':True,'places':{a.id:{'status':'resolved','place':place} for a in trip.activities},
           'routes':{'activity_1':{'status':'available','minutes':15,'source':'Test route','mode':'walk'}},
           'findings':[{'message':'15 min walk + 10 min buffer.'}]}
    graph=SimpleNamespace(get_state=lambda config:SimpleNamespace(values=state,tasks=[]))
    run=present(graph,'a'*32)
    assert run['trip']['activities'][0]['duration_estimated']
    assert 'buffer_minutes' not in run
    assert 'Add the duration' not in run['findings'][0]['message']
    assert 'buffer' not in run['findings'][0]['message']
