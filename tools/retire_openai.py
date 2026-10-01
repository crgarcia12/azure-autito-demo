from __future__ import annotations

from datetime import UTC, datetime
import json
import time

import httpx

from tools.cloud import ARM, CONFIG, ROOT, Cloud, az, load_state, save_state
from tools.deploy import app_path


def main():
    cloud, state = Cloud(), load_state()
    verified = json.loads((ROOT / ".local" / "secured-hosted-e2e.json").read_text(encoding="utf-8"))
    token = cloud.credential.get_token(f"api://{state['agent_app_id']}/.default").token
    with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=90) as client:
        response = client.get(state["appUrl"] + "/api/incidents/" + verified["case_id"])
        response.raise_for_status()
        case = response.json()
        proof = case.get("repair_report", {}).get("evidence_agent", {})
        if case["status"] != "booked" or proof.get("project_endpoint") != state.get("foundry_project_endpoint") or not proof.get("responses"):
            raise RuntimeError("A real hosted Foundry-backed case must complete before the old account can be removed.")
        response = client.get(state["appUrl"] + "/api/insurance/health")
        response.raise_for_status()
        if response.json()["evidence"]["project_endpoint"] != state["foundry_project_endpoint"]:
            raise RuntimeError("The hosted app is not configured for the verified Foundry project.")
    foundry = cloud.request("GET", ARM + state["foundry_account_id"] + "?api-version=2025-06-01")
    if foundry["kind"] != "AIServices" or not foundry["properties"].get("allowProjectManagement"):
        raise RuntimeError("The replacement is not a project-capable Foundry resource.")
    old_name = "caldovadrive08667473-ai"
    old = az("cognitiveservices", "account", "show", "--name", old_name,
             "--resource-group", CONFIG["resource_group"], "--subscription", CONFIG["subscription_id"])
    if old["kind"] != "OpenAI":
        raise RuntimeError("Refusing to delete an unexpected resource type.")
    deployments = az("cognitiveservices", "account", "deployment", "list", "--name", old_name,
                     "--resource-group", CONFIG["resource_group"], "--subscription", CONFIG["subscription_id"])
    if {item["name"] for item in deployments} != {"incident-vision"}:
        raise RuntimeError("The old account has unexpected deployments; retirement requires review.")
    state["retired_openai_account"] = {"name": old_name, "replaced_by": state["foundry_account_name"], "verified_case": case["id"]}
    save_state(state, remove_keys=("vision_endpoint", "vision_deployment"))
    state = load_state()
    path = app_path(state) + "/config/appsettings"
    app_settings = cloud.request("POST", path + "/list?api-version=2023-12-01")["properties"]
    app_settings["FLEET_DEPLOYMENT"] = json.dumps(state)
    cloud.request("PUT", path + "?api-version=2023-12-01", {"properties": app_settings})
    ready = False
    for _ in range(24):
        try:
            response = httpx.get(state["appUrl"] + "/health/live", timeout=20)
            if response.is_success and response.json().get("service") == "Caldova Drive":
                ready = True
                break
        except (httpx.TimeoutException, httpx.ConnectError):
            print("Waiting for the Foundry-only configuration to become ready.", flush=True)
        time.sleep(10)
    if not ready:
        raise RuntimeError("The Foundry-only app configuration did not become healthy; the old resource was retained.")
    az("cognitiveservices", "account", "delete", "--name", old_name,
       "--resource-group", CONFIG["resource_group"], "--subscription", CONFIG["subscription_id"])
    remaining = az("cognitiveservices", "account", "list", "--resource-group", CONFIG["resource_group"],
                   "--subscription", CONFIG["subscription_id"])
    if any(item["name"] == old_name for item in remaining):
        raise RuntimeError("The old account is still present.")
    state["retired_openai_account"]["retired_at"] = datetime.now(UTC).isoformat()
    save_state(state)
    print(f"Removed {old_name}; the verified Foundry project and all case data remain intact.")


if __name__ == "__main__":
    main()
