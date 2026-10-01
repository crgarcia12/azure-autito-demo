from datetime import UTC, date, datetime, timedelta

import pytest

from fleet.domain import RoadRoute, VehicleMotion, day_bounds, fleet_vehicles, previous_day


@pytest.fixture
def motion():
    route = RoadRoute("LON", [(51.5, -.1), (51.51, -.1), (51.5, -.1)], 300)
    return VehicleMotion(fleet_vehicles()[0], route)


def test_fleet_has_unique_registrations_and_identifiers():
    fleet = fleet_vehicles()
    assert len(fleet) == 40
    assert len({v["VehicleId"] for v in fleet}) == len(fleet)
    assert len({v["Registration"] for v in fleet}) == len(fleet)
    assert {v["City"] for v in fleet} == {"London", "Manchester", "Birmingham", "Bristol", "Leeds", "Edinburgh"}


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25), (date(2026, 9, 28), 24)])
def test_calendar_day_respects_dst(day, hours):
    start, end = day_bounds(day, "Europe/Madrid")
    assert (end - start).total_seconds() == hours * 3600


def test_yesterday_is_local_calendar_day_not_last_24_hours():
    day, start, end = previous_day(datetime(2026, 9, 29, 6, tzinfo=UTC), "Europe/Madrid")
    assert day == date(2026, 9, 28)
    assert start == datetime(2026, 9, 27, 22, tzinfo=UTC)
    assert end == datetime(2026, 9, 28, 22, tzinfo=UTC)


def test_restart_and_retry_produce_identical_events(motion):
    start = datetime(2026, 9, 29, 8, tzinfo=UTC)
    assert motion.sample(start, start + timedelta(seconds=15)) == motion.sample(start, start + timedelta(seconds=15))


def test_distance_is_invariant_under_sampling_rate(motion):
    start = datetime(2026, 9, 29, 8, tzinfo=UTC)
    end = start + timedelta(hours=2)
    coarse = motion.sample(start, end).DistanceKm
    total = sum(motion.sample(start + timedelta(seconds=i), start + timedelta(seconds=i + 15)).DistanceKm for i in range(0, 7200, 15))
    assert total == pytest.approx(coarse, abs=1e-6)


def test_parked_vehicles_never_accumulate_distance():
    vehicle = fleet_vehicles()[13]
    motion = VehicleMotion(vehicle, RoadRoute("LON", [(51.5, -.1), (51.51, -.1)], 300))
    start = datetime(2026, 9, 29, 8, tzinfo=UTC)
    event = motion.sample(start, start + timedelta(days=1))
    assert event.DistanceKm == event.SpeedKmh == 0
    assert event.Status == "maintenance"


def test_odometer_never_goes_backwards(motion):
    start = datetime(2026, 9, 29, 8, tzinfo=UTC)
    events = [motion.sample(start + timedelta(minutes=i), start + timedelta(minutes=i + 1)) for i in range(360)]
    assert all(b.OdometerKm >= a.OdometerKm for a, b in zip(events, events[1:]))


def test_invalid_intervals_and_routes_are_rejected(motion):
    instant = datetime(2026, 9, 29, tzinfo=UTC)
    with pytest.raises(ValueError):
        motion.sample(instant, instant)
    with pytest.raises(ValueError):
        RoadRoute("empty", [], 100)
