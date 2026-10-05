from datetime import UTC, datetime, timedelta

from fleet.demo_case import POSITION, POSITION_KEY, VEHICLE_ID
from fleet.domain import RoadRoute, VehicleMotion, fleet_vehicles, utc_text
from fleet.simulator import tick
from fleet.storage import StateStore


def test_stornoway_position_change_does_not_add_distance_or_change_other_cars(tmp_path, monkeypatch):
    start = datetime(2026, 10, 4, 22, tzinfo=UTC)

    class Clock(datetime):
        current = start + timedelta(seconds=30)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    route = RoadRoute("LON", [(51.5, -.1), (51.51, -.1)], 300)
    vehicles = fleet_vehicles()
    mini = VehicleMotion(next(row for row in vehicles if row["VehicleId"] == VEHICLE_ID), route)
    other = VehicleMotion(vehicles[0], route)
    baseline = mini.sample(start - timedelta(seconds=15), start).model_dump(mode="json")

    class Data:
        rows = []
        lookups = 0

        def query(self, query, parameters):
            self.lookups += 1
            assert parameters == {"vehicle": VEHICLE_ID}
            return [baseline]

        def ingest(self, table, rows):
            assert table == "Telemetry"
            self.rows.extend(rows)

    data = Data()
    store = StateStore(tmp_path / "state.sqlite3")
    store.put("injector-checkpoint.json", {"through": utc_text(start), "events": 0})
    monkeypatch.setattr("fleet.simulator.datetime", Clock)
    monkeypatch.setattr("fleet.simulator.settings", lambda: {"telemetry_interval_seconds": 15})
    tick(data, store, [mini, other])
    Clock.current += timedelta(seconds=15)
    tick(data, store, [mini, other])
    assert data.lookups == 1
    assert store.get(POSITION_KEY)["OdometerKm"] == baseline["OdometerKm"]
    for row in data.rows:
        if row["VehicleId"] == VEHICLE_ID:
            assert row["Latitude"] == POSITION["Latitude"] and row["Longitude"] == POSITION["Longitude"]
            assert row["DistanceKm"] == row["SpeedKmh"] == 0
            assert row["OdometerKm"] == baseline["OdometerKm"]
            assert row["RouteId"] == "STY-PARKED" and row["Status"] == "on-hire"
        else:
            a = datetime.fromisoformat(row["IntervalStart"].replace("Z", "+00:00"))
            b = datetime.fromisoformat(row["Timestamp"].replace("Z", "+00:00"))
            assert row == other.sample(a, b).model_dump(mode="json")
