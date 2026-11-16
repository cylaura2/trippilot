"""Validated contracts for the prompt, itinerary, streaming events, and schedule checks."""
from datetime import date, datetime, time, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Activity(Contract):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=400)
    day: date
    start: str | None = None
    start_estimated: bool = False
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    duration_estimated: bool = False
    fixed: bool = False
    suggested: bool = False

    @field_validator('start')
    @classmethod
    def valid_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = time.fromisoformat(value)
        if parsed.tzinfo or parsed.second or parsed.microsecond:
            raise ValueError('Use a local time in HH:MM format.')
        return parsed.strftime('%H:%M')

    def instant(self, timezone_name: str) -> datetime:
        if self.start is None:
            raise ValueError('Add a start time before calculating this activity’s instant.')
        naive = datetime.combine(self.day, time.fromisoformat(self.start))
        zone = ZoneInfo(timezone_name)
        first = naive.replace(tzinfo=zone, fold=0)
        second = naive.replace(tzinfo=zone, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ValueError('A time crosses a daylight-saving transition. Use an unambiguous local time.')
        if first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != naive:
            raise ValueError('This local time does not exist in the selected timezone.')
        return first.astimezone(timezone.utc)


class TripContext(Contract):
    city: str | None = None
    timezone: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class Trip(Contract):
    city: str = Field(min_length=1, max_length=100)
    timezone: str
    start_date: date | None = None
    end_date: date | None = None
    activities: list[Activity] = Field(min_length=1, max_length=120)
    origin: Literal['imported', 'generated'] = 'imported'
    input_text: str = Field(default='', max_length=10000)
    notes: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode='after')
    def valid_trip(self):
        try:
            ZoneInfo(self.timezone)
        except (KeyError, ValueError) as exc:
            raise ValueError('Use a valid IANA timezone, such as Europe/Madrid.') from exc
        if len({activity.id for activity in self.activities}) != len(self.activities):
            raise ValueError('Activities must have unique IDs.')
        self.start_date = self.start_date or min(activity.day for activity in self.activities)
        self.end_date = self.end_date or max(activity.day for activity in self.activities)
        if self.end_date < self.start_date:
            raise ValueError('The trip end date must be on or after the start date.')
        for activity in self.activities:
            if not self.start_date <= activity.day <= self.end_date:
                raise ValueError('Activity dates must fall within the trip’s date range.')
            if activity.start is not None:
                activity.instant(self.timezone)
        return self


class BuildRequest(Contract):
    text: str = Field(min_length=1, max_length=10000)
    reference_date: date
    client_timezone: str = 'America/New_York'

    @field_validator('client_timezone')
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:
            raise ValueError('Your browser timezone is invalid.') from exc
        return value


class Usage(Contract):
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class BuildResult(Contract):
    trip: Trip | None = None
    context: TripContext
    clarification: str | None = None
    usage: Usage
    clarification_kind: Literal['empty_itinerary'] | None = None


class FillDaysRequest(Contract):
    trip: Trip


class ProgressEvent(Contract):
    activity_id: str | None = None
    destination_id: str | None = None
    type: Literal['progress'] = 'progress'
    stage: str
    label: str
    status: Literal['running', 'complete', 'waiting', 'skipped', 'error']
    detail: str
    kind: Literal['ai', 'workflow', 'tool', 'human'] = 'workflow'


class RunRequest(Contract):
    trip: Trip
    day: date | None = None
    previous_run_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')

    @model_validator(mode='after')
    def valid_day(self):
        if self.day is not None and not any(a.day == self.day for a in self.trip.activities):
            raise ValueError('Add an activity to this day before checking it.')
        return self


class ResumeRequest(Contract):
    choices: dict[str, str]


class PlaceCandidate(Contract):
    id: str
    name: str
    address: str
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    confidence: float = Field(default=0, ge=0, le=1)
    categories: list[str] = Field(default_factory=list)
    walk_anchor: bool = False


class PlaceResolution(Contract):
    status: Literal['resolved', 'ambiguous', 'unresolved']
    place: PlaceCandidate | None = None
    candidates: list[PlaceCandidate] = Field(default_factory=list)
    source: str = 'Geoapify / OpenStreetMap'
    reason: str = ''
    proposed: bool = False
    recommended_id: str | None = None


class RouteEstimate(Contract):
    status: Literal['available', 'unavailable']
    minutes: int | None = Field(default=None, ge=0)
    distance_meters: float | None = Field(default=None, ge=0)
    mode: Literal['walk', 'drive', 'approximated_transit'] = 'walk'
    allowance_minutes: int = Field(default=0, ge=0)
    source: str = 'Geoapify walking estimate / OpenStreetMap'
    reason: str = ''


class Finding(Contract):
    source_id: str
    destination_id: str
    status: Literal['conflict', 'fits', 'unknown']
    message: str
    travel_minutes: int | None = None
    travel_mode: Literal['walk', 'drive', 'approximated_transit'] | None = None
    slack_minutes: int | None = None
    evidence: str = 'No verified route estimate available.'


class TimingSuggestion(Contract):
    id: str
    activity_id: str
    day: date
    current_start: str
    proposed_start: str
    message: str
    evidence: str = 'Rechecked against current travel estimates and fixed bookings. Opening hours and ticket availability are not verified.'
