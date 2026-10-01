from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from fleet.config import data_credential, settings
from fleet.storage import StateStore


def morning_wakeup(store: StateStore, now: datetime) -> None:
    config = settings()
    local = now.astimezone(ZoneInfo(config["report_timezone"]))
    resume_at = (config.get("capacity_resume_hour", 7), config.get("capacity_resume_minute", 45))
    if (local.hour, local.minute) < resume_at or local.hour >= 9:
        return
    key = f"capacity-wakeup-{local.date().isoformat()}.json"
    if store.get(key):
        return
    token = data_credential().get_token("https://management.azure.com/.default").token
    url = "https://management.azure.com" + config["fabric_capacity_resource_id"]
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=90) as client:
        current = client.get(url, params={"api-version": "2023-11-01"}, headers=headers)
        current.raise_for_status()
        status = current.json()["properties"]["state"]
        if status == "Paused":
            resumed = client.post(url + "/resume", params={"api-version": "2023-11-01"}, headers=headers)
            resumed.raise_for_status()
            status = "ResumeRequested"
        elif status != "Active":
            raise RuntimeError(f"Fabric capacity is not ready: {status}")
    store.put(key, {"status": status, "requestedAt": now.isoformat()})
