from trippilot.workflow import materialize_suggestions
from trippilot.checker import check_schedule


def test_resolved_meal_replaces_placeholder_and_preserves_other_facts(trip):
    trip.activities[3].name = 'Dinner near the hotel'
    trip.activities[3].description = 'Restaurant TBD. Vegetarian options preferred.'
    before = trip.model_dump(mode='json')
    places = {'activity_4': {'status':'resolved','place': {'name':'Alt Heidelberg'}}}
    result = materialize_suggestions(trip, places)
    assert result.activities[3].name == 'Dinner at Alt Heidelberg'
    assert result.activities[3].description == 'Vegetarian options preferred.'
    assert result.activities[3].suggested
    assert result.activities[3].start == trip.activities[3].start
    assert result.activities[3].day == trip.activities[3].day
    assert result.activities[3].duration_minutes == trip.activities[3].duration_minutes
    assert result.activities[:3] == trip.activities[:3]
    assert trip.model_dump(mode='json') == before
    assert materialize_suggestions(result, places) == result


def test_unresolved_and_fixed_meals_are_not_assigned_a_new_place(trip):
    trip.activities[3].name = 'Dinner near the hotel'
    assert materialize_suggestions(trip, {}) == trip
    trip.activities[3].fixed = True
    assert materialize_suggestions(trip, {'activity_4':{'status':'resolved','place':{'name':'Suggested restaurant'}}}) == trip


def test_unknown_schedule_still_shows_selected_mode_and_time(trip):
    trip.activities = trip.activities[:2]
    trip.activities[0].duration_minutes = None
    places = {a.id:{'place':{'lat':41,'lng':2}} for a in trip.activities}
    route = {'status':'available','minutes':25,'mode':'drive','source':'Test provider'}
    finding = check_schedule(trip,places,{'activity_1':route})[0]
    assert finding['travel_mode'] == 'drive'
    assert '25 min by taxi / car' in finding['message']
    assert finding['status'] == 'unknown' and finding['slack_minutes'] is None


def test_confirmed_edited_restaurant_uses_provider_spelling(trip):
    trip.activities[3].name = 'Dinner at vinutus'
    places = {'activity_4':{'status':'resolved','place':{'name':'Vinitus'}}}
    updated = materialize_suggestions(trip,places).activities[3]
    assert updated.name == 'Dinner at Vinitus'
    assert not updated.suggested
    assert updated.id == trip.activities[3].id


def test_combined_stop_becomes_named_cathedral_without_losing_walk(trip):
    trip.activities[3].name = 'Gothic Quarter and Barcelona Cathedral'
    places = {'activity_4':{'status':'resolved','place':{'name':'Barcelona Cathedral'}}}
    stop = materialize_suggestions(trip,places).activities[3]
    assert stop.name == 'Barcelona Cathedral'
    assert 'Gothic Quarter' in stop.description
    assert stop.start == trip.activities[3].start


def test_old_wrong_apartment_match_does_not_rename_stop_to_cathedral(trip):
    trip.activities[3].name = 'Gothic Quarter and Barcelona Cathedral'
    places = {'activity_4':{'status':'resolved','place':{'name':'Ainb Gothic Cathedral Apartments'}}}
    assert materialize_suggestions(trip,places).activities[3].name == trip.activities[3].name


def test_saved_meal_removes_leftover_empty_parentheses_and_stale_hotel_text(trip):
    trip.activities[3].name = 'Dinner at Vinitus'
    trip.activities[3].description = 'Dinner near the hotel (restaurant TBD). Vegetarian options preferred.'
    trip.activities[3].duration_minutes = None
    updated = materialize_suggestions(trip, {'activity_4':{'status':'resolved','place':{'name':'Vinitus'}}}).activities[3]
    assert updated.description == 'Vegetarian options preferred.'
    assert updated.name == 'Dinner at Vinitus'
    assert updated.duration_minutes is None


def test_old_saved_empty_parentheses_are_cleaned_on_read(trip):
    trip.activities[3].name = 'Dinner at Vinitus'
    trip.activities[3].description = 'Dinner near the hotel ().'
    updated = materialize_suggestions(trip, {'activity_4':{'status':'resolved','place':{'name':'Vinitus'}}})
    assert updated.activities[3].description == ''
    assert materialize_suggestions(updated, {'activity_4':{'status':'resolved','place':{'name':'Vinitus'}}}) == updated
