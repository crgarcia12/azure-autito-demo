"""Prepare a real customer email and leave its hosted reporting form unsubmitted."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import os
import re
import time
from urllib.parse import quote, urlparse
import uuid

import httpx
from playwright.async_api import async_playwright, expect

from fleet.config import agent_credential
from fleet.demo_case import CUSTOMER_EMAIL, CUSTOMER_NAME, VEHICLE_DETAILS, VEHICLE_ID
from fleet.domain import utc_text
from fleet.fabric import FabricData
from fleet.insurance import insurance_config
from fleet.mail import plain_body
from tools.cloud import Cloud, GRAPH, ROOT, load_state
from tools.deploy import app_path


async def main():
    cloud, state = Cloud(), load_state()
    config = insurance_config()
    recipient = config["customer_notification_mailbox"]
    if recipient != "admin@caldova08667473.onmicrosoft.com":
        raise RuntimeError("This verification is authorised only for the selected demo admin inbox.")
    expected_build = (ROOT / ".local" / "build-id.txt").read_text().strip()
    response = httpx.get(state["appUrl"] + "/health/live", timeout=60)
    response.raise_for_status()
    if response.json()["buildId"] != expected_build:
        raise RuntimeError("Wait for the customer-email build to finish deploying before preparing the case.")
    settings = cloud.request("POST", app_path(state) + "/config/appsettings/list?api-version=2023-12-01")["properties"]
    os.environ["FLEET_AGENT_SECRET"] = settings["FLEET_AGENT_SECRET"]
    credential = agent_credential()
    token = await asyncio.to_thread(credential.get_token, "https://graph.microsoft.com/.default")
    receipt_path = ROOT / ".local" / f"live-customer-email-{VEHICLE_ID}-v{VEHICLE_DETAILS['RegisterVersion']}.json"
    data = FabricData()
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        event = receipt["event"]
        case_id = receipt["case_id"]
    else:
        vehicles = data.query(
            "declare query_parameters(vehicle:string); FleetLatest() | where VehicleId == vehicle and Status !in ('incident','maintenance')",
            {"vehicle": VEHICLE_ID},
        )
        if not vehicles:
            raise RuntimeError("The green MINI Cooper is not available for a fresh report. Use its existing incident rather than resetting it.")
        vehicle = vehicles[0]
        event_id = str(uuid.uuid4())
        case_id = "CDI-" + uuid.uuid5(uuid.NAMESPACE_URL, event_id).hex[:10].upper()
        event = {
            "EventId": event_id, "VehicleId": vehicle["VehicleId"], "Timestamp": utc_text(datetime.now(UTC)),
            "PeakAccelerationG": 3.7, "DeltaVKmh": 6.0, "SpeedBeforeKmh": 6.0, "SpeedAfterKmh": 0.0,
            "Latitude": vehicle["Latitude"], "Longitude": vehicle["Longitude"],
            "OdometerKm": vehicle["OdometerKm"], "Source": "vehicle-telemetry",
        }
        receipt = {"case_id": case_id, "event": event, "impact_ingested": False}
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    if not receipt["impact_ingested"]:
        await asyncio.to_thread(data.ingest, "VehicleImpacts", [event])
        receipt["impact_ingested"] = True
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print("Waiting for the detected incident's real customer email:", case_id, event["VehicleId"], flush=True)
    subject = f"[{case_id}] [REPORT] Your secure incident report link"
    folder = GRAPH + "/users/" + quote(config["claims_mailbox"], safe="") + "/mailFolders/sentitems/messages"
    headers = {"Authorization": f"Bearer {token.token}", "Prefer": 'IdType="ImmutableId", outlook.body-content-type="text"'}

    async def sent_messages(client):
        response = await client.get(folder, params={
            "$filter": "subject eq '" + subject + "'", "$top": 2,
            "$select": "id,isDraft,subject,body,from,toRecipients,sentDateTime,internetMessageId,webLink",
        })
        response.raise_for_status()
        return response.json()["value"]

    started = time.monotonic()
    async with httpx.AsyncClient(headers=headers, timeout=90) as graph:
        while time.monotonic() - started < 600:
            messages = await sent_messages(graph)
            if messages:
                break
            await asyncio.sleep(8)
        else:
            raise TimeoutError("The hosted worker did not confirm a customer email within ten minutes.")
        if len(messages) != 1:
            raise RuntimeError("More than one initial notification was sent for this case.")
        email = messages[0]
        if email["isDraft"] or not email.get("internetMessageId") or not email.get("sentDateTime"):
            raise RuntimeError("Exchange has not confirmed a sent notification.")
        if [item["emailAddress"]["address"].casefold() for item in email["toRecipients"]] != [recipient]:
            raise RuntimeError("The customer notification was not addressed to the selected inbox.")
        body = plain_body(email["body"]["content"])
        links = re.findall(re.escape(state["appUrl"]) + rf"/report/{case_id}#[A-Za-z0-9_-]+", body)
        if len(links) != 1:
            raise RuntimeError("The notification does not contain exactly one real reporting link.")
        link = links[0]
        capability = urlparse(link).fragment
        async with httpx.AsyncClient(timeout=60) as customer:
            response = await customer.get(
                state["appUrl"] + "/customer/" + case_id,
                headers={"X-Incident-Token": capability, "X-Caldova-Request": "fleet-app"},
            )
            response.raise_for_status()
            record = response.json()
        if record["status"] != "awaiting_report" or record["report_received"]:
            raise RuntimeError("The customer form has already been submitted; no case was reset.")
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 390, "height": 844})
            await page.goto(link, wait_until="domcontentloaded")
            await page.locator("#content").wait_for(state="visible", timeout=60000)
            if not await page.locator("#photos").count() or not await page.locator("#report-form").count():
                raise RuntimeError("The actual hosted customer form did not load.")
            if "#" in page.url:
                raise RuntimeError("The customer page did not remove the capability from its visible URL.")
            assert await page.locator("#safe").count() == 0
            assert await page.locator("#name").input_value() == CUSTOMER_NAME
            assert await page.locator("#email").input_value() == CUSTOMER_EMAIL
            assert await page.locator("#description").input_value() == ""
            await expect(page.locator("#weather-status")).not_to_have_text(re.compile("Checking"), timeout=45000)
            assert "Stornoway Airport" in await page.locator("#weather-details").inner_text()
            await page.screenshot(path=str(ROOT / ".local" / "customer-email-report-form.png"), full_page=True)
            await browser.close()
        await asyncio.sleep(45)
        if len(await sent_messages(graph)) != 1:
            raise RuntimeError("A repeated worker cycle duplicated the customer notification.")
    receipt.update({
        "recipient": recipient, "subject": subject, "email_id": email["id"], "sent_at": email["sentDateTime"],
        "outlook_url": email["webLink"], "customer_form_verified": True, "report_submitted": False,
        "duplicate_notifications": False, "build_id": expected_build,
    })
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in (
        "case_id", "recipient", "subject", "sent_at", "outlook_url",
        "customer_form_verified", "report_submitted", "duplicate_notifications", "build_id",
    )}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
