"""Exercise the deployed site using a real, user-delegated Caldova operator token."""

import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
from playwright.sync_api import sync_playwright

from tools.cloud import Cloud, ROOT, load_state


def main():
    cloud, state = Cloud(), load_state()
    token = cloud.credential.get_token(f"api://{state['agent_app_id']}/.default").token
    origin = state["appUrl"]
    auth = {"Authorization": f"Bearer {token}"}
    with httpx.Client(headers=auth, timeout=90) as client:
        response = client.get(origin + "/api/incidents")
        response.raise_for_status()
        cases = response.json()["cases"]
        ready = next(case for case in cases if case["status"] == "recommendation_ready")
        booked = next(case for case in cases if case["status"] == "booked")
        inspection = next(case for case in cases if case["status"] == "report_review_required")
        assert ready["recommendation"]["agent"]["id"]
        assert ready["recommendation"]["garage_id"] == "metro"
        assert len(ready["quotes"]) == 3
        assert booked["booking"]["email_id"]
        assert inspection["repair_report"]["requires_manual_review"]
        assert not inspection["quotes"] and not inspection["correspondence"]
        cross_origin = client.post(origin + f"/api/incidents/{ready['id']}/approve", json={"version": ready["version"]},
                                   headers={"X-Caldova-Request": "fleet-app", "Origin": "https://untrusted.example"})
        assert cross_origin.status_code == 403
    unauthorized = httpx.get(origin + "/api/incidents", follow_redirects=False, timeout=30)
    assert unauthorized.status_code in {302, 401}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1512, "height": 1100})

        def authorize_only_our_origin(route):
            if urlparse(route.request.url).netloc != urlparse(origin).netloc:
                raise RuntimeError("Refusing to forward the delegated token to another host.")
            route.continue_(headers={**route.request.headers, **auth})

        context.route(origin + "/**", authorize_only_our_origin)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(origin, wait_until="domcontentloaded")
        page.wait_for_function("document.getElementById('total-fleet').textContent === '40'", timeout=90000)
        page.wait_for_function("document.querySelectorAll('.map-vehicle').length === 40", timeout=90000)
        assert not page.locator("#error-banner").is_visible()
        page.locator('[data-view="incidents"]').click()
        page.locator(f'[data-case="{ready["id"]}"]').click()
        page.locator("#approve-repair").wait_for(state="visible", timeout=30000)
        assert page.locator(".quote-card").count() == 3
        assert "Metro" in page.locator(".quote-card.winner").inner_text()
        slider = page.locator("#downtime-sensitivity")
        slider.press("Home")
        assert "Alder" in page.locator("#sensitivity-result").inner_text()
        for _ in range(10):
            slider.press("ArrowRight")
        assert "Metro" in page.locator("#sensitivity-result").inner_text()
        page.screenshot(path=str(ROOT / ".local" / "hosted-recommendation.png"), full_page=True)
        assert page.locator(".email-item").count() >= 6
        page.locator(".email-item").first.locator("summary").click()
        assert page.locator(".email-item").first.locator("pre").is_visible()
        page.locator("#show-customer-link").click()
        page.locator(".phone-shell").wait_for(state="visible")
        assert "999" in page.locator(".sms-bubble").inner_text()
        page.screenshot(path=str(ROOT / ".local" / "hosted-phone-journey.png"), full_page=True)
        page.locator(f'[data-case="{inspection["id"]}"]').click()
        page.get_by_role("button", name="Request clearer evidence").wait_for(state="visible")
        assert page.locator("#approve-repair").count() == 0
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(500)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(ROOT / ".local" / "hosted-incident-mobile.png"), full_page=True)
        assert not errors, errors
        context.close()
        browser.close()
    result = {"cases": {"ready": ready["id"], "booked": booked["id"], "inspection": inspection["id"]}, "checks": [
        "authenticated hosted app", "unauthenticated access blocked", "cross-origin approval blocked",
        "40 real map markers", "three real garage quotes", "cost trade-off slider",
        "original email disclosure", "phone message preview", "inspection blocks approval", "mobile layout",
    ]}
    (ROOT / ".local" / "hosted-browser-results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
