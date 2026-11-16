from trippilot.durations import proposed_minutes, with_proposed_durations


def test_missing_lengths_are_proposed_without_changing_known_booking_facts(trip):
    original = trip.model_dump(mode='json')
    trip.activities[-1].name = 'Dinner near the hotel'
    trip.activities[-1].duration_minutes = None
    updated = with_proposed_durations(trip)
    assert updated.activities[-1].duration_minutes == 90
    assert updated.activities[-1].duration_estimated
    assert updated.activities[0].model_dump(mode='json') == original['activities'][0]
    assert updated.activities[-1].start == trip.activities[-1].start
    assert trip.activities[-1].duration_minutes is None
    assert with_proposed_durations(updated) == updated


def test_duration_categories_use_the_activity_name_before_description():
    assert proposed_minutes('Hotel check-in','After airport arrival') == 30
    assert proposed_minutes('Dinner near the hotel') == 90
    assert proposed_minutes('Coffee near Park Güell') == 30



def test_proposals_do_not_rewrite_a_tight_supplied_schedule(trip):
    trip.activities = trip.activities[:2]
    first, second = trip.activities
    first.name = 'Airport arrival'
    first.start = '09:20'
    first.duration_minutes = None
    second.start = '10:30'
    updated = with_proposed_durations(trip)
    assert updated.activities[0].duration_minutes == 90
    assert updated.activities[0].duration_estimated
    assert updated.activities[0].start == '09:20'
    assert updated.activities[1].start == '10:30'


def test_missing_starts_follow_previous_duration_and_real_transit(trip):
    from trippilot.durations import with_proposed_starts
    trip.activities = trip.activities[:3]
    trip.activities[0].start = '10:00'
    trip.activities[0].duration_minutes = 60
    trip.activities[1].start = None
    trip.activities[1].duration_minutes = 30
    trip.activities[2].start = None
    routes = {a.id: {'status':'available', 'minutes':12} for a in trip.activities[:2]}
    result = with_proposed_starts(trip, routes)
    assert [a.start for a in result.activities] == ['10:00','11:12','11:54']
    assert [a.start_estimated for a in result.activities] == [False,True,True]
    assert trip.activities[1].start is None
    # Moving the supplied anchor must recalculate the following proposals in source order.
    result.activities[0].start = '12:00'
    assert [a.start for a in with_proposed_starts(result,routes).activities] == ['12:00','13:12','13:54']


def test_supplied_start_remains_an_anchor_even_if_there_is_a_conflict(trip):
    from trippilot.durations import with_proposed_starts
    trip.activities = trip.activities[:3]
    trip.activities[0].start = '10:00'
    trip.activities[0].duration_minutes = 60
    trip.activities[1].start = None
    trip.activities[2].start = '11:30'
    result = with_proposed_starts(trip, {'activity_1':{'status':'available','minutes':12}})
    assert result.activities[2].start == '11:30'
    assert not result.activities[2].start_estimated


def test_missing_route_does_not_invent_travel_and_day_does_not_overflow(trip):
    from trippilot.durations import with_proposed_starts
    trip.activities = trip.activities[:2]
    trip.activities[0].start = None
    trip.activities[1].start = None
    result = with_proposed_starts(trip,{})
    assert result.activities[0].start == '09:00'
    assert result.activities[0].start_estimated
    assert result.activities[1].start is None
    trip.activities[0].start = '23:30'
    trip.activities[0].duration_minutes = 60
    result = with_proposed_starts(trip, {'activity_1':{'status':'available','minutes':12}})
    assert result.activities[1].start is None


def test_checking_one_day_preserves_proposals_on_other_days(trip):
    from datetime import date
    from trippilot.durations import with_proposed_starts
    trip.activities[2].day = trip.activities[3].day = date(2026,11,21)
    trip.end_date = date(2026,11,21)
    trip.activities[3].start = '15:30'
    trip.activities[3].start_estimated = True
    result = with_proposed_starts(trip, {}, '2026-11-20')
    assert result.activities[3].start == '15:30'
    assert result.activities[3].start_estimated
