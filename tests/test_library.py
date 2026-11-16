import pytest
from fastapi.testclient import TestClient
from trippilot.api import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('TRIPPILOT_DATA_DIR',str(tmp_path))
    with TestClient(app) as client:
        yield client


def payload(trip):
    return {'title':'Barcelona weekend','trip':trip.model_dump(mode='json'),
            'prompt':'Barcelona itinerary','run_id':None}


def test_library_roundtrip_duplicate_and_independent_edit(client,trip):
    saved=client.post('/api/trips',json=payload(trip))
    assert saved.status_code==201
    original=saved.json()
    assert original['version']==1
    listing=client.get('/api/trips').json()
    assert len(listing)==1 and listing[0]['stop_count']==4
    assert 'trip' not in listing[0] and 'prompt' not in listing[0]
    loaded=client.get('/api/trips/'+original['id']).json()
    assert loaded['trip']==trip.model_dump(mode='json')
    assert loaded['prompt']=='Barcelona itinerary'
    copy=client.post('/api/trips/'+original['id']+'/duplicate').json()
    assert copy['id']!=original['id'] and copy['title']=='Barcelona weekend (copy)'
    changed=copy['trip']
    changed['activities'][0]['name']='Changed place'
    updated=client.put('/api/trips/'+copy['id'],json={**payload(trip),'trip':changed,'version':copy['version']})
    assert updated.status_code==200 and updated.json()['version']==2
    assert client.get('/api/trips/'+original['id']).json()['trip']['activities'][0]['name']=='Park Güell'


def test_rename_delete_and_restore_without_losing_data(client,trip):
    saved=client.post('/api/trips',json=payload(trip)).json()
    path='/api/trips/'+saved['id']
    renamed=client.patch(path,json={'title':'Spain in November','version':1})
    assert renamed.status_code==200 and renamed.json()['title']=='Spain in November'
    assert client.delete(path).status_code==200
    assert client.get('/api/trips').json()==[]
    assert client.get(path).status_code==404
    restored=client.post(path+'/restore')
    assert restored.status_code==200
    assert restored.json()['title']=='Spain in November'
    assert restored.json()['trip']==trip.model_dump(mode='json')


def test_stale_update_cannot_overwrite_newer_saved_trip(client,trip):
    saved=client.post('/api/trips',json=payload(trip)).json()
    path='/api/trips/'+saved['id']
    client.patch(path,json={'title':'Renamed elsewhere','version':1})
    assert client.put(path,json={**payload(trip),'version':1}).status_code==409
    assert client.patch(path,json={'title':'Stale rename','version':1}).status_code==409
    assert client.get(path).json()['title']=='Renamed elsewhere'


def test_library_validates_inputs_and_uses_parameterized_queries(client,trip):
    assert client.post('/api/trips',json={**payload(trip),'title':'  '}).status_code==422
    assert client.post('/api/trips',json={**payload(trip),'run_id':'not-an-id'}).status_code==422
    assert client.get('/api/trips/not-found').status_code==404
    malicious="Robert'); DROP TABLE trips;--"
    saved=client.post('/api/trips',json={**payload(trip),'title':malicious}).json()
    assert client.get('/api/trips/'+saved['id']).json()['title']==malicious
    assert len(client.get('/api/trips').json())==1


def test_library_persists_across_client_restarts(tmp_path,monkeypatch,trip):
    monkeypatch.setenv('TRIPPILOT_DATA_DIR',str(tmp_path))
    with TestClient(app) as first:
        saved=first.post('/api/trips',json=payload(trip)).json()
    with TestClient(app) as second:
        assert second.get('/api/trips/'+saved['id']).json()['trip']==trip.model_dump(mode='json')
    assert (tmp_path/'workspace.sqlite').exists()


def test_saved_checks_and_confirmed_places_survive_reopening(client,trip):
    point={'id':'place-1','name':'Park Güell','address':'Barcelona','lat':41.4,'lng':2.1}
    places={'activity_1':{'status':'resolved','place':point,'candidates':[point]}}
    saved=client.post('/api/trips',json={**payload(trip),'run_id':'a'*32,'places':places}).json()
    loaded=client.get('/api/trips/'+saved['id']).json()
    assert loaded['run_id']=='a'*32
    assert loaded['places']['activity_1']['place']['name']=='Park Güell'
    assert loaded['trip']['activities'][0]['fixed']
