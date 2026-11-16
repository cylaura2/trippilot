"""Editable visit-length proposals, kept distinct from supplied booking facts."""
import re
from datetime import timedelta
from zoneinfo import ZoneInfo
from .checker import activity_pairs
from .models import Trip


def proposed_minutes(name: str, description: str = '') -> int:
    if re.search(r'hotel|check.in', name, re.I) and re.search(r'luggage|leave.*bags', description, re.I):
        return 20
    rules = [
        (r'airport|flight|terminal', 90), (r'luggage|bags? drop', 20),
        (r'dinner', 90), (r'lunch|restaurant|tapas', 60), (r'breakfast', 45),
        (r'coffee|café|cafe', 30), (r'hotel|check.in', 30), (r'museum', 120),
        (r'cathedral|basilica|church|temple', 60), (r'park|walk|quarter|palace', 90),
    ]
    for text in (name.lower(), description.lower()):
        for pattern, minutes in rules:
            if re.search(pattern, text): return minutes
    return 60


def with_proposed_durations(trip: Trip) -> Trip:
    data = trip.model_dump(mode='json')
    for activity in data['activities']:
        if activity['duration_minutes'] is None:
            activity['duration_minutes'] = proposed_minutes(activity['name'], activity['description'])
            activity['duration_estimated'] = True
    data['notes'] = [note for note in data['notes'] if not note.startswith('Unspecified durations stayed blank')]
    return Trip.model_validate(data)


def with_proposed_starts(trip: Trip, routes: dict, day: str | None = None) -> Trip:
    """Fill unspecified starts from the previous visit plus a real travel estimate.

    A day with no initial time starts at 09:00. Supplied times remain anchors.
    Rechecks refresh estimated starts when the preceding stop or route changes.
    """
    data = with_proposed_durations(trip).model_dump(mode='json')
    activities = {a['id']: a for a in data['activities']}
    for activity_day in sorted({a.day for a in trip.activities}):
        if day and str(activity_day) != day:
            continue
        daily = [a for a in trip.activities if a.day == activity_day]
        if all(a.start is not None and not a.start_estimated for a in daily):
            daily.sort(key=lambda a: a.instant(trip.timezone))
        first = activities[daily[0].id]
        if first['start'] is None:
            first.update(start='09:00', start_estimated=True)
    for previous, current in activity_pairs(trip):
        if day and str(current.day) != day:
            continue
        target = activities[current.id]
        if target['start'] is not None and not target['start_estimated']:
            continue
        source = activities[previous.id]
        route = routes.get(previous.id, {})
        # Do not present an invented journey duration as an actual route estimate.
        if source['start'] is None or route.get('status') != 'available':
            target.update(start=None, start_estimated=False)
            continue
        departure = previous.model_copy(update={'start': source['start']}).instant(trip.timezone)
        arrival = (departure + timedelta(minutes=source['duration_minutes'] + route['minutes'])).astimezone(ZoneInfo(trip.timezone))
        if arrival.date() != current.day:
            target.update(start=None, start_estimated=False)
            continue
        target.update(start=arrival.strftime('%H:%M'), start_estimated=True)
    return Trip.model_validate(data)
