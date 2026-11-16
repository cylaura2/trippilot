"""Generate and verify small schedule edits before an agent can recommend them."""
import re
from .checker import activity_pairs, check_schedule
from .models import TimingSuggestion, Trip


def apply_timing(trip: Trip, suggestion: TimingSuggestion) -> Trip:
    data = trip.model_dump(mode='json')
    activity = next((a for a in data['activities'] if a['id'] == suggestion.activity_id), None)
    if activity is None or activity['fixed'] or activity['start'] != suggestion.current_start or activity['day'] != suggestion.day.isoformat():
        raise ValueError('This suggestion no longer matches a flexible stop. Check the itinerary again.')
    activity['start'] = suggestion.proposed_start
    activity['start_estimated'] = False
    return Trip.model_validate(data)


def timing_options(trip: Trip, places: dict, routes: dict, findings: list[dict]) -> list[TimingSuggestion]:
    activities = {activity.id: activity for activity in trip.activities}
    original_pairs = [(a.id, b.id) for a, b in activity_pairs(trip)]
    options = []
    for finding in findings:
        if finding['status'] != 'conflict' or finding.get('slack_minutes') is None:
            continue
        short = -finding['slack_minutes']
        if short <= 0:
            continue
        for activity_id, shift in ((finding['destination_id'], short), (finding['source_id'], -short)):
            activity = activities[activity_id]
            text = activity.name + ' ' + activity.description
            transport_anchor = (re.search(r'\b(?:airport|terminal|flight|train|station)\b',text,re.I)
                                and re.search(r'\b(?:arriv\w*|depart\w*|flight)\b',text,re.I))
            if activity.fixed or transport_anchor or activity.start is None:
                continue
            hour, minute = map(int, activity.start.split(':'))
            proposed = hour * 60 + minute + shift
            if not 0 <= proposed < 1440 or proposed + (activity.duration_minutes or 0) > 1440:
                continue
            suggestion = TimingSuggestion(id=f'option_{len(options) + 1}', activity_id=activity.id, day=activity.day,
                                          current_start=activity.start, proposed_start=f'{proposed // 60:02d}:{proposed % 60:02d}',
                                          message=f'Move {activity.name} from {activity.start} to {proposed // 60:02d}:{proposed % 60:02d} on {activity.day.isoformat()} to allow travel.')
            try:
                changed = apply_timing(trip, suggestion)
            except ValueError:
                continue
            if [(a.id, b.id) for a, b in activity_pairs(changed)] != original_pairs:
                continue  # Reordering needs different routes; not supported by this repair.
            checked = check_schedule(changed, places, routes)
            if any(new['status'] != 'fits' for new in checked if new['source_id'] == finding['source_id']):
                continue
            # A local fix must not create a conflict or unknown in a previously checked pair.
            if any(old['status'] == 'fits' and new['status'] != 'fits' for old, new in zip(findings, checked)):
                continue
            if any(old['status'] == 'conflict' and new['status'] == 'unknown' for old, new in zip(findings, checked)):
                continue
            options.append(suggestion)
            if len(options) >= 8:
                return options
    return options
