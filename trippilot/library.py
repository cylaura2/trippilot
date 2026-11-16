"""A small, persistent library for a single private workspace."""
import json
import os
import sqlite3
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import Field
from .models import Contract, Trip, PlaceResolution

router = APIRouter(prefix='/api/trips')


@contextmanager
def database():
    directory = Path(os.environ.get('TRIPPILOT_DATA_DIR', str(Path(__file__).resolve().parent.parent / '.data')))
    directory.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(directory / 'workspace.sqlite', timeout=15)) as db:
        db.row_factory = sqlite3.Row
        with db:
            db.execute('''CREATE TABLE IF NOT EXISTS trips (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, payload TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1, deleted INTEGER NOT NULL DEFAULT 0)''')
            yield db


class TripSave(Contract):
    title: str = Field(min_length=1, max_length=100)
    trip: Trip
    prompt: str = Field(default='', max_length=10000)
    run_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    places: dict[str, PlaceResolution] = Field(default_factory=dict, max_length=120)


class TripReplace(TripSave):
    version: int = Field(ge=1)


class TripRename(Contract):
    title: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=1)


def now():
    return datetime.now(timezone.utc).isoformat()


def record(row, full=True):
    data = json.loads(row['payload'])
    return {**{key: row[key] for key in ('id','title','created_at','updated_at','version')},
            'city':data['trip']['city'], 'start_date':data['trip']['start_date'],
            'end_date':data['trip']['end_date'], 'stop_count':len(data['trip']['activities']),
            **(data if full else {})}


def find(db, trip_id, deleted=0):
    row = db.execute('SELECT * FROM trips WHERE id=? AND deleted=?', (trip_id,deleted)).fetchone()
    if row is None:
        raise HTTPException(404, 'Saved trip not found.')
    return row


def check_version(row, version):
    if row['version'] != version:
        raise HTTPException(409, 'This trip changed on another device. Reopen it before saving again. Your current draft is still here.')


@router.get('')
def list_trips():
    with database() as db:
        return [record(row,False) for row in db.execute('SELECT * FROM trips WHERE deleted=0 ORDER BY updated_at DESC')]


@router.post('', status_code=201)
def save_trip(request: TripSave):
    data = request.model_dump(mode='json')
    title = data.pop('title').strip()
    if not title:
        raise HTTPException(422,'Give this trip a name.')
    trip_id, stamp = uuid4().hex, now()
    with database() as db:
        db.execute('INSERT INTO trips(id,title,payload,created_at,updated_at) VALUES(?,?,?,?,?)',
                   (trip_id,title,json.dumps(data),stamp,stamp))
        return record(find(db,trip_id))


@router.get('/{trip_id}')
def get_trip(trip_id: str):
    with database() as db:
        return record(find(db,trip_id))


@router.put('/{trip_id}')
def replace_trip(trip_id: str, request: TripReplace):
    data = request.model_dump(mode='json')
    title, version = data.pop('title').strip(), data.pop('version')
    if not title:
        raise HTTPException(422,'Give this trip a name.')
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        check_version(find(db,trip_id),version)
        db.execute('UPDATE trips SET title=?,payload=?,updated_at=?,version=version+1 WHERE id=?',
                   (title,json.dumps(data),now(),trip_id))
        return record(find(db,trip_id))


@router.patch('/{trip_id}')
def rename_trip(trip_id: str, request: TripRename):
    title = request.title.strip()
    if not title:
        raise HTTPException(422,'Give this trip a name.')
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        check_version(find(db,trip_id),request.version)
        db.execute('UPDATE trips SET title=?,updated_at=?,version=version+1 WHERE id=?',(title,now(),trip_id))
        return record(find(db,trip_id))


@router.post('/{trip_id}/duplicate',status_code=201)
def duplicate_trip(trip_id: str):
    with database() as db:
        source = find(db,trip_id)
        data = json.loads(source['payload'])
    return save_trip(TripSave(title=(source['title'][:93]+' (copy)'),**data))


@router.delete('/{trip_id}')
def delete_trip(trip_id: str):
    with database() as db:
        find(db,trip_id)
        db.execute('UPDATE trips SET deleted=1,version=version+1 WHERE id=?',(trip_id,))
    return {'deleted':True}


@router.post('/{trip_id}/restore')
def restore_trip(trip_id: str):
    with database() as db:
        find(db,trip_id,deleted=1)
        db.execute('UPDATE trips SET deleted=0,updated_at=?,version=version+1 WHERE id=?',(now(),trip_id))
        return record(find(db,trip_id))
