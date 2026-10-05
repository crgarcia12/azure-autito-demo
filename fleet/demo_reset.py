from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
import shutil
import uuid

from fleet.demo_case import POSITION, VEHICLE_DETAILS, VEHICLE_ID
from fleet.domain import utc_text
from fleet.insurance import IncidentError, Incidents


def prepare_mini_reset(cases: Incidents, reset_id: str, vehicle: dict, operator: str) -> dict:
    reset_id = str(uuid.UUID(reset_id))
    key = "mini-reset/" + reset_id
    if vehicle["VehicleId"] != VEHICLE_ID or any(
        vehicle.get(field) != VEHICLE_DETAILS[field] for field in ("Make", "Model", "Colour", "Registration", "City")
    ):
        raise IncidentError("The reset requires the configured green MINI Cooper in Stornoway.")
    if any(abs(vehicle[field] - POSITION[field]) > .001 for field in ("Latitude", "Longitude")):
        raise IncidentError("The MINI has not reached its configured Stornoway position.")
    now = utc_text(datetime.now(UTC))
    event_id = str(uuid.uuid4())
    event = {
        "EventId": event_id, "VehicleId": VEHICLE_ID, "Timestamp": now,
        "PeakAccelerationG": 3.7, "DeltaVKmh": 6.0, "SpeedBeforeKmh": 6.0, "SpeedAfterKmh": 0.0,
        "Latitude": vehicle["Latitude"], "Longitude": vehicle["Longitude"],
        "OdometerKm": vehicle["OdometerKm"], "Source": "vehicle-telemetry",
    }
    with cases.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = cases.store.get(key, connection=db)
        if existing:
            return existing
        previous = cases.store.get("mini-reset-current", connection=db)
        if previous:
            pending = cases.store.get("mini-reset/" + previous["reset_id"], connection=db)
            if pending and pending["stage"] != "complete":
                raise IncidentError("A previous MINI reset is unfinished. Resume it before starting a new run.")
        uncertain = db.execute(
            "SELECT key FROM incident_operations WHERE state IN ('sending','draft_creating') LIMIT 1"
        ).fetchone()
        if uncertain:
            raise IncidentError("An email has an uncertain delivery outcome. Reconcile it before resetting incidents.")
        records = [cases._row(row) for row in db.execute("SELECT * FROM incidents")]
        deleted, archived = [], []
        for record in records:
            case_id = record["id"]
            if record["vehicle_id"] == VEHICLE_ID:
                if not re.fullmatch(r"CDI-[A-F0-9]{10}", case_id):
                    raise IncidentError("An invalid incident identifier prevents safe cleanup.")
                db.execute("DELETE FROM incident_events WHERE case_id=?", (case_id,))
                db.execute("DELETE FROM incident_operations WHERE case_id=?", (case_id,))
                db.execute("DELETE FROM incidents WHERE id=?", (case_id,))
                db.execute(
                    "DELETE FROM state WHERE name LIKE ? OR name IN (?,?,?,?)",
                    (case_id + "/%", "incident-link/" + case_id, "incident-weather/" + case_id,
                     "repair-error/" + case_id, "vehicle-hold/" + case_id),
                )
                deleted.append(case_id)
            elif record["status"] != "archived":
                data = json.loads(db.execute("SELECT data FROM incidents WHERE id=?", (case_id,)).fetchone()[0])
                data["demo_archive"] = {"at": now, "by": operator, "previous_status": record["status"], "reset_id": reset_id}
                db.execute(
                    "UPDATE incidents SET status='archived',updated_at=?,version=version+1,data=? WHERE id=?",
                    (now, json.dumps(data), case_id),
                )
                cases._event(db, case_id, "demo_run_archived", operator, data["demo_archive"])
                archived.append(case_id)
        receipt = {
            "reset_id": reset_id, "stage": "prepared", "created_at": now,
            "case_id": "CDI-" + uuid.uuid5(uuid.NAMESPACE_URL, event_id).hex[:10].upper(),
            "event": event, "deleted_case_ids": deleted, "archived_case_ids": archived,
        }
        cases.store.put("impact-reset.json", {"not_before": now, "reset_id": reset_id}, connection=db)
        cases.store.put(key, receipt, connection=db)
        cases.store.put("mini-reset-current", {"reset_id": reset_id}, connection=db)
    return receipt


def remove_reset_evidence(root: Path, case_ids: list[str]) -> None:
    root = root.resolve()
    for case_id in case_ids:
        if not re.fullmatch(r"CDI-[A-F0-9]{10}", case_id):
            raise IncidentError("Invalid case identifier in the evidence cleanup manifest.")
        directory = root / case_id
        if directory.is_symlink() or directory.resolve().parent != root:
            raise IncidentError("Evidence cleanup cannot follow a redirected case directory.")
        if directory.exists():
            if not directory.is_dir():
                raise IncidentError("The case evidence path is not a directory.")
            shutil.rmtree(directory)
