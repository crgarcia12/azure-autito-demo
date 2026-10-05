"""Verify the current hosted MINI journey without uploading or submitting customer evidence."""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx
from playwright.sync_api import expect, sync_playwright

from fleet.demo_case import CUSTOMER_EMAIL, CUSTOMER_NAME, VEHICLE_ID
from fleet.repair_policy import policy_reference
from tools.cloud import Cloud, ROOT, load_state


def main() -> None:
    cloud, config = Cloud(), load_state()
    origin = config["appUrl"]
    token = cloud.credential.get_token(f"api://{config['agent_app_id']}/.default").token
    auth = {"Authorization": "Bearer " + token}
    with httpx.Client(headers={**auth, "X-Caldova-Request": "fleet-app"}, timeout=90) as client:
        health = client.get(origin + "/health/live")
        health.raise_for_status()
        assert health.json()["buildId"] == (ROOT / ".local" / "build-id.txt").read_text().strip()
        response = client.get(origin + "/api/incidents")
        response.raise_for_status()
        cases = response.json()["cases"]
        assert len(cases) == 1 and cases[0]["vehicle_id"] == VEHICLE_ID
        case_id = cases[0]["id"]
        response = client.get(origin + "/api/incidents/" + case_id)
        response.raise_for_status()
        case = response.json()
        assert case["status"] == "awaiting_report" and not case["report_received"]
        assert not case["photos"] and not case["quotes"] and not case["last_error"]
        assert not case.get("agent_actions") and not case.get("work_iq_policy")
        assert case["repair_policy"]["document_url"] == policy_reference()["document_url"]
        messages = case["correspondence"]
        assert len(messages) == 1 and "[REPORT]" in messages[0]["subject"]
        assert messages[0]["internet_message_id"]
        assert messages[0]["to"] == "admin@caldova08667473.onmicrosoft.com"
        assert "We detected a possible impact involving your rental Green MINI Cooper (YK23 LZP)." in messages[0]["body"]
        assert not case.get("approval") and not case.get("booking")
        response = client.get(origin + "/api/fleet")
        response.raise_for_status()
        vehicles = response.json()["vehicles"]
        assert len(vehicles) == 40
        assert sum(v["Status"] == "on-hire" and not v["Alert"] for v in vehicles) == 39
        assert [v["VehicleId"] for v in vehicles if v["Status"] == "incident"] == [VEHICLE_ID]
        response = client.post(origin + f"/api/incidents/{case_id}/link", json={})
        response.raise_for_status()
        link = response.json()["url"]
        blocked = client.post(origin + "/api/demo/reset-mini", json={},
                              headers={"Origin": "https://untrusted.example"})
        assert blocked.status_code == 403
    assert httpx.get(origin + "/api/incidents", follow_redirects=False, timeout=60).status_code in {302, 401}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1512, "height": 1100})

        def authorize_origin(route):
            assert urlparse(route.request.url).netloc == urlparse(origin).netloc
            route.continue_(headers={**route.request.headers, **auth})

        context.route(origin + "/**", authorize_origin)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(origin, wait_until="domcontentloaded")
        expect(page.locator("#total-fleet")).to_have_text("40", timeout=90000)
        expect(page.locator("#on-road")).to_have_text("39")
        expect(page.locator("#alert-count")).to_have_text("1")
        expect(page.locator(".map-vehicle")).to_have_count(40, timeout=90000)
        expect(page.locator("#error-banner")).not_to_be_visible()
        assert not re.search(r"charging|low battery|energy level", page.locator("body").inner_text(), re.IGNORECASE)
        page.locator("#fit-map").click()
        page.screenshot(path=str(ROOT / "docs" / "media" / "insurance-pitch" / "04-fleet-context.png"), animations="disabled")
        page.locator('[data-view="incidents"]').click()
        page.locator(f'[data-case="{case_id}"]').click()
        expect(page.locator("#case-detail")).to_contain_text("The customer has not yet submitted", timeout=60000)
        expect(page.locator("#approve-repair")).to_have_count(0)
        page.locator("details.email-item").filter(has_text="[REPORT]").first.locator("summary").click()
        assert page.get_by_role("link", name="Open the Word policy source").get_attribute("href") == policy_reference()["document_url"]
        page.screenshot(path=str(ROOT / ".local" / "hosted-customer-email.png"), full_page=True, animations="disabled")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        context.close()

        customer = browser.new_context(viewport={"width": 390, "height": 844})
        page = customer.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(link, wait_until="domcontentloaded")
        expect(page.locator("#content")).to_be_visible(timeout=60000)
        expect(page.locator("#name")).to_have_value(CUSTOMER_NAME)
        expect(page.locator("#email")).to_have_value(CUSTOMER_EMAIL)
        expect(page.locator("#description")).to_have_value("")
        expect(page.locator("#safe")).to_have_count(0)
        expect(page.locator("#photos")).to_have_value("")
        expect(page.locator("#weather-status")).not_to_have_text(re.compile("Checking|Searching"), timeout=90000)
        assert "#" not in page.url
        page.screenshot(path=str(ROOT / "docs" / "media" / "insurance-pitch" / "05-customer-report.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        customer.close()

        slides = browser.new_page(viewport={"width": 1600, "height": 900})
        for source, target in [
            ("intro.html", "01-business-process.png"),
            ("agents.html", "02-agent-roles.png"),
            ("flow.html", "03-product-lanes.png"),
        ]:
            slides.goto((ROOT / "docs" / source).as_uri(), wait_until="load")
            expect(slides.locator(".slide")).to_be_visible()
            slides.screenshot(path=str(ROOT / "docs" / "media" / "insurance-pitch" / target), animations="disabled")
        browser.close()
        assert not errors, errors

    result = {
        "case_id": case_id, "build_id": health.json()["buildId"], "on_hire": 39, "incident_detected": 1,
        "controlled_policy_verified": True, "customer_email_receipt_verified": True,
        "customer_report_submitted": False, "map_markers": 40, "mobile_layout": True,
        "subject": messages[0]["subject"],
    }
    (ROOT / ".local" / "fresh-demo-verified.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
