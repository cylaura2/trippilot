"""Grounded inputs + deterministic arithmetic = explainable findings."""
import math

from .models import Finding, Trip


def activity_pairs(trip: Trip):
    """Check each day independently; preserve its input order when times are missing."""
    for day in sorted({activity.day for activity in trip.activities}):
        activities = [activity for activity in trip.activities if activity.day == day]
        if all(activity.start is not None and not activity.start_estimated for activity in activities):
            activities.sort(key=lambda activity: activity.instant(trip.timezone))
        yield from zip(activities, activities[1:])


def check_schedule(trip: Trip, places: dict, routes: dict | None = None) -> list[dict]:
    routes = routes or {}
    findings = []
    for current, following in activity_pairs(trip):
        finding = Finding(source_id=current.id, destination_id=following.id,
                          status="unknown", message="")
        origin = places.get(current.id, {}).get("place")
        destination = places.get(following.id, {}).get("place")
        route = routes.get(current.id, {})
        travel = route.get('minutes') if route.get('status') == 'available' else None
        mode = route.get('mode', 'walk')
        phrase = {'walk': 'walk', 'drive': 'by taxi / car', 'approximated_transit': 'by transit (approx.)'}[mode]
        travel_text = f'About {travel} min {phrase}. ' if origin and destination and travel is not None else ''
        if origin and destination and travel is not None:
            finding.travel_minutes = travel
            finding.travel_mode = mode
            finding.evidence = (route['source'] + f'. {travel} min {phrase}. '
                                'Estimate only; conditions may differ on your travel date.')
        else:
            finding.evidence = ('Route not requested: both locations need confirmation.' if not origin or not destination
                                else route.get('reason') or 'No travel estimate was returned for these locations.')
        if current.start is None or following.start is None:
            finding.message = travel_text + "Add both start times to check this transfer."
            findings.append(finding.model_dump())
            continue
        gap = (following.instant(trip.timezone) - current.instant(trip.timezone)).total_seconds() / 60
        if current.duration_minutes is None:
            finding.message = travel_text + f"Add the duration of {current.name} to check this transfer."
        elif current.duration_minutes > gap:
            overlap = math.ceil(current.duration_minutes - gap)
            finding.status = "conflict"
            finding.message = f"Activities overlap by {overlap} minutes, even before travel."
            finding.evidence = ("Proposed visit length and entered start times. " if current.duration_estimated else "Supplied activity start times and duration. ") + finding.evidence
        elif not origin or not destination:
            finding.message = "Resolve both locations before checking this transfer."
        else:
            if travel is None:
                finding.message = route.get('reason') or 'No travel estimate is available for this pair.'
            else:
                finding.evidence = route['source'] + '. Estimate only; conditions may differ on your travel date.'
                slack = math.floor(gap - current.duration_minutes - travel)
                finding.travel_minutes, finding.slack_minutes = travel, slack
                finding.status = "fits" if slack >= 0 else "conflict"
                finding.message = (
                    f"About {travel} min {phrase}. "
                    + (f"{slack} min to spare." if slack >= 0 else f"Short by {abs(slack)} min.")
                )
        findings.append(finding.model_dump())
    return findings
