from __future__ import annotations

import json
import time

from fleet.demo_case import VEHICLE_DETAILS, VEHICLE_ID
from fleet.fabric import FabricData
from tools.cloud import Cloud, ROOT


def main() -> None:
    Cloud()
    data = FabricData()
    data.initialise_schema()
    before = data.query("Vehicles | summarize arg_max(RegisterVersion, *) by VehicleId")
    vehicle = next(row for row in before if row["VehicleId"] == VEHICLE_ID)
    latest = next(row for row in data.latest() if row["VehicleId"] == VEHICLE_ID)
    changed = any(vehicle.get(key) != value for key, value in VEHICLE_DETAILS.items())
    if changed and latest["Status"] == "incident":
        raise RuntimeError("The selected vehicle already has an incident. Its recorded identity will not be replaced.")
    if changed:
        cleared = data.query(".clear table Vehicles cache streamingingestion schema")
        if not cleared or any(row["Status"] != "Succeeded" for row in cleared):
            raise RuntimeError("The streaming-ingestion nodes did not confirm the new vehicle schema.")
        data.ingest("Vehicles", [{**vehicle, **VEHICLE_DETAILS}])
    for _ in range(15):
        after = data.query("Vehicles | summarize arg_max(RegisterVersion, *) by VehicleId")
        current = next(row for row in after if row["VehicleId"] == VEHICLE_ID)
        if all(current.get(key) == value for key, value in VEHICLE_DETAILS.items()):
            break
        time.sleep(2)
    else:
        raise RuntimeError("The MINI vehicle-register revision is not visible.")
    if len(after) != len(before) or len({row["VehicleId"] for row in after}) != 40:
        raise RuntimeError("The vehicle-register update changed the fleet shape.")
    originals = {row["VehicleId"]: row for row in before}
    for row in after:
        if row["VehicleId"] == VEHICLE_ID:
            if any(row.get(key) != value for key, value in VEHICLE_DETAILS.items()):
                raise RuntimeError("The MINI vehicle-register revision is not visible.")
        elif any(row.get(key) != value for key, value in originals[row["VehicleId"]].items()):
            raise RuntimeError("An unrelated vehicle record changed during synchronization.")
    data.write_table("Vehicles", after)
    verified = next(row for row in data.latest() if row["VehicleId"] == VEHICLE_ID)
    result = {key: verified[key] for key in ("VehicleId", *VEHICLE_DETAILS)}
    (ROOT / ".local" / "mini-vehicle-sync.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
