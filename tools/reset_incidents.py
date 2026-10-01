"""Remove every incident so the demo starts clean.

Fleet telemetry, routes, briefings and agent configuration are kept.
Usage (app stopped): python -m tools.reset_incidents --state <state.sqlite3> [--fabric] [--mail]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from urllib.parse import quote

import httpx

from fleet.config import agent_credential
from fleet.insurance import insurance_config

GRAPH = "https://graph.microsoft.com/v1.0"
CASE_KEYS = ("incident-link/%", "repair-error/%", "vehicle-hold/%", "CDI-%")


def reset_state(path: str) -> dict:
    with sqlite3.connect(path) as db:
        counts = {table: db.execute(f"DELETE FROM {table}").rowcount
                  for table in ("incident_events", "incident_operations", "incidents")}
        counts["state"] = sum(db.execute("DELETE FROM state WHERE name LIKE ?", (key,)).rowcount for key in CASE_KEYS)
        db.execute("DELETE FROM state WHERE name IN ('fabric-callback-health', 'repair-worker-health')")
    with sqlite3.connect(path) as db:
        db.execute("VACUUM")
    return counts


def reset_fabric() -> None:
    from fleet.fabric import FabricData
    data = FabricData()
    data.client.execute_mgmt(data.database, ".clear table VehicleImpacts data")
    remaining = data.query("VehicleImpacts | count")[0]["Count"]
    if remaining:
        raise RuntimeError(f"VehicleImpacts still has {remaining} rows.")


def reset_mail() -> dict:
    config = insurance_config()
    boxes = [config["claims_mailbox"], *(garage["mailbox"] for garage in config["garages"])]
    token = agent_credential().get_token("https://graph.microsoft.com/.default").token
    removed = {}
    with httpx.Client(timeout=60, headers={"Authorization": "Bearer " + token}) as client:
        for box in boxes:
            count = 0
            for folder in ("inbox", "sentitems", "drafts"):
                url = f"{GRAPH}/users/{quote(box, safe='')}/mailFolders/{folder}/messages?$top=100&$select=id"
                while True:
                    page = client.get(url)
                    page.raise_for_status()
                    messages = page.json()["value"]
                    if not messages:
                        break
                    for message in messages:
                        client.delete(f"{GRAPH}/users/{quote(box, safe='')}/messages/{quote(message['id'], safe='')}").raise_for_status()
                        count += 1
            removed[box] = count
    return removed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state")
    parser.add_argument("--fabric", action="store_true")
    parser.add_argument("--mail", action="store_true")
    args = parser.parse_args()
    if args.state:
        print("state:", reset_state(args.state))
    if args.fabric:
        reset_fabric()
        print("fabric: VehicleImpacts cleared")
    if args.mail:
        if not os.environ.get("FLEET_AGENT_SECRET"):
            raise SystemExit("Set FLEET_AGENT_SECRET to the App Service agent secret to clean the mailboxes.")
        print("mail moved to Deleted Items:", reset_mail())
