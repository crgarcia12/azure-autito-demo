from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from fleet.config import data_credential, settings
from fleet.domain import BRANCHES, RoadRoute, VehicleMotion, day_bounds, fleet_vehicles, parse_time, utc_text
from fleet.fabric import FabricData
from fleet.storage import StateStore
from fleet.insurance import INACTIVE_STATUSES, Incidents
from fleet.demo_case import POSITION, POSITION_KEY, VEHICLE_ID

LOG = logging.getLogger("caldova.injector")


def load_routes(store: StateStore, *, create: bool = False) -> dict[str, RoadRoute]:
    saved = store.get("routes.json")
    if saved is None:
        if not create:
            raise RuntimeError("Road routes have not been prepared. Run the seed command.")
        config = settings()
        credential = data_credential()
        saved = {}
        with httpx.Client(timeout=90) as client:
            for branch in BRANCHES:
                response = client.get(
                    "https://atlas.microsoft.com/route/directions/json",
                    params={
                        "api-version": "1.0",
                        "query": ":".join(f"{lat},{lon}" for lat, lon in branch["Waypoints"]),
                        "travelMode": "car", "routeType": "fastest", "traffic": "false",
                    },
                    headers={
                        "Authorization": f"Bearer {credential.get_token('https://atlas.microsoft.com/.default').token}",
                        "x-ms-client-id": config["mapsClientId"],
                    },
                )
                response.raise_for_status()
                route = response.json()["routes"][0]
                points = []
                for leg in route["legs"]:
                    for point in leg["points"]:
                        coordinate = [point["latitude"], point["longitude"]]
                        if not points or coordinate != points[-1]:
                            points.append(coordinate)
                saved[branch["BranchId"]] = {
                    "points": points, "travel_seconds": route["summary"]["travelTimeInSeconds"],
                    "length_meters": route["summary"]["lengthInMeters"],
                }
                LOG.info("Prepared %s road route: %.1f km", branch["City"], route["summary"]["lengthInMeters"] / 1000)
        store.put("routes.json", saved)
    return {
        name: RoadRoute(name, [tuple(point) for point in route["points"]], route["travel_seconds"])
        for name, route in saved.items()
    }


def motions(store: StateStore, *, create: bool = False) -> list[VehicleMotion]:
    routes = load_routes(store, create=create)
    return [VehicleMotion(vehicle, routes[vehicle["BranchId"]]) for vehicle in fleet_vehicles()]


def seed() -> None:
    config = settings()
    store = StateStore()
    data = FabricData()
    movement = motions(store, create=True)
    data.initialise_schema()
    vehicles = fleet_vehicles()
    branches = [{key: branch[key] for key in ("BranchId", "BranchName", "City", "Latitude", "Longitude")} for branch in BRANCHES]
    data.ingest("Vehicles", vehicles)
    data.ingest("Branches", branches)
    data.write_table("Vehicles", vehicles)
    data.write_table("Branches", branches)
    data.write_table("Rentals", [
        {
            "RentalId": f"R-{vehicle['Index'] + 10401}",
            "VehicleId": vehicle["VehicleId"], "BranchId": vehicle["BranchId"],
            "AccountName": ["Northstar Consulting", "Meridian Travel", "Atlas Engineering", "Harbour Events"][vehicle["Index"] % 4],
            "DailyRateGBP": vehicle["DailyRateGBP"], "IncludedKmPerDay": 250,
        } for vehicle in vehicles
    ])
    existing = store.get("seed-progress.json")
    if existing and existing.get("completed"):
        LOG.info("Historical data already seeded; keeping existing telemetry.")
        return
    now = datetime.now(UTC).replace(microsecond=0)
    interval = config["history_interval_seconds"]
    now -= timedelta(seconds=now.timestamp() % interval)
    day = now.astimezone(ZoneInfo(config["report_timezone"])).date()
    start, _ = day_bounds(day - timedelta(days=config["history_days"]), config["report_timezone"])
    if existing:
        start = parse_time(existing["next_start"])
        now = parse_time(existing["end"])
    cursor = start
    while cursor < now:
        rows = []
        batch_end = min(cursor + timedelta(hours=2), now)
        while cursor < batch_end:
            end = min(cursor + timedelta(seconds=interval), batch_end)
            rows.extend(motion.sample(cursor, end).model_dump(mode="json") for motion in movement)
            cursor = end
        data.ingest("Telemetry", rows)
        store.put("seed-progress.json", {"next_start": utc_text(cursor), "end": utc_text(now), "completed": False})
        if cursor.minute == 0:
            LOG.info("Ingested telemetry through %s", utc_text(cursor))
    store.put("injector-checkpoint.json", {"through": utc_text(now), "events": 0})
    store.put("seed-progress.json", {"next_start": utc_text(now), "end": utc_text(now), "completed": True})
    LOG.info("Historical telemetry complete; refreshing Lakehouse tables.")
    time.sleep(5)
    store.put("lakehouse-refresh.json", data.refresh_lakehouse())


def tick(data: FabricData, store: StateStore, movement: list[VehicleMotion]) -> dict:
    controls = store.get("injector-control.json") or {"paused": False}
    checkpoint = store.get("injector-checkpoint.json")
    if not checkpoint:
        raise RuntimeError("Missing ingestion checkpoint. Complete historical seeding first.")
    if controls.get("paused"):
        return {"state": "paused", **checkpoint}
    config = settings()
    interval = config["telemetry_interval_seconds"]
    now = datetime.now(UTC).replace(microsecond=0)
    now -= timedelta(seconds=now.timestamp() % interval)
    cursor = parse_time(checkpoint["through"])
    if cursor >= now:
        return {"state": "running", **checkpoint}
    position = store.get(POSITION_KEY)
    if position is None and any(motion.vehicle["VehicleId"] == VEHICLE_ID for motion in movement):
        current = data.query("declare query_parameters(vehicle:string); FleetLatest() | where VehicleId == vehicle", {"vehicle": VEHICLE_ID})
        if len(current) != 1:
            raise RuntimeError("The configured vehicle position needs one existing telemetry record.")
        anchor = current[0]
        position = {
            **POSITION, "effective_at": utc_text(cursor),
            **{key: anchor[key] for key in ("OdometerKm", "Heading", "BatteryPct", "FuelPct", "EngineTempC")},
        }
        store.create(POSITION_KEY, position)
        position = store.get(POSITION_KEY)
    batch_end = min(cursor + timedelta(minutes=15), now)
    holds = {}
    for incident in Incidents(store).list():
        if incident["status"] not in INACTIVE_STATUSES:
            key = f"vehicle-hold/{incident['id']}"
            saved = store.get(key)
            if saved is None:
                stopped = max(parse_time(incident["telemetry"]["Timestamp"]), cursor)
                saved = {"stopped_at": utc_text(stopped)}
                store.create(key, saved)
            holds.setdefault(incident["vehicle_id"], parse_time(saved["stopped_at"]))
    rows = []
    while cursor < batch_end:
        end = min(cursor + timedelta(seconds=interval), batch_end)
        for motion in movement:
            sample = motion.sample(cursor, end)
            stopped = holds.get(motion.vehicle["VehicleId"])
            if stopped:
                if end > stopped:
                    anchor = motion.sample(stopped - timedelta(seconds=1), stopped)
                    sample.Latitude, sample.Longitude = anchor.Latitude, anchor.Longitude
                    sample.OdometerKm, sample.Heading = anchor.OdometerKm, anchor.Heading
                    sample.DistanceKm = motion.sample(cursor, stopped).DistanceKm if cursor < stopped else 0
                    sample.SpeedKmh = 0
                    sample.Status, sample.Alert = "incident", "Incident detected"
            if position and motion.vehicle["VehicleId"] == VEHICLE_ID and end > parse_time(position["effective_at"]):
                sample.Latitude, sample.Longitude = position["Latitude"], position["Longitude"]
                sample.OdometerKm, sample.Heading = position["OdometerKm"], position["Heading"]
                sample.BatteryPct, sample.FuelPct = position["BatteryPct"], position["FuelPct"]
                sample.EngineTempC = position["EngineTempC"]
                sample.DistanceKm = sample.SpeedKmh = 0
                sample.RouteId = position["RouteId"]
                if not stopped:
                    sample.Status, sample.Alert = "on-hire", ""
            rows.append(sample.model_dump(mode="json"))
        cursor = end
    data.ingest("Telemetry", rows)
    checkpoint = {"through": utc_text(cursor), "events": checkpoint.get("events", 0) + len(rows), "lastBatch": len(rows)}
    store.put("injector-checkpoint.json", checkpoint)
    return {"state": "running", **checkpoint}


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject road-following UK vehicle telemetry into Microsoft Fabric.")
    parser.add_argument("command", choices=["seed", "once"])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.command == "seed":
        seed()
    else:
        store = StateStore()
        with store.lease("worker-lease.json"):
            print(json.dumps(tick(FabricData(), store, motions(store))))


if __name__ == "__main__":
    main()
