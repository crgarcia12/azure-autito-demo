"""Run against the real local or deployed demo: python tests\\browser_smoke.py."""

import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1512, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(os.environ.get("FLEET_TEST_URL", "http://127.0.0.1:8097"), wait_until="domcontentloaded")
        page.wait_for_function("document.querySelectorAll('.map-vehicle').length === 40", timeout=90000)
        page.wait_for_timeout(2000)
        assert page.locator("#total-fleet").inner_text() == "40"
        assert not page.locator("#error-banner").is_visible()
        visible = page.evaluate("""() => {
            const map = document.getElementById('fleet-map').getBoundingClientRect();
            return [...document.querySelectorAll('.map-vehicle')].filter(element => {
                const r = element.getBoundingClientRect();
                return r.x >= map.x && r.y >= map.y && r.right <= map.right && r.bottom <= map.bottom;
            }).length;
        }""")
        assert visible == 40, f"Only {visible}/40 vehicle markers are inside the map."
        page.locator('[data-city="London"]').click()
        assert page.locator("#vehicle-list .vehicle-row").count() == 16
        page.locator('[data-city="all"]').click()
        page.locator("#fleet-search").fill("CD-001")
        assert page.locator("#vehicle-list .vehicle-row").count() == 1
        page.locator("#fleet-search").fill("")
        page.locator("#vehicle-list .vehicle-row").first.click()
        assert page.locator("#selected-vehicle").is_visible()
        page.locator("#clear-selection").click()
        page.locator('[data-view="vehicles"]').first.click()
        assert page.locator("#vehicles-table tr").count() == 40
        page.locator('[data-view="intelligence"]').click()
        assert page.locator(".ontology-graph .entity").count() == 5
        page.locator('[data-view="briefings"]').click()
        assert page.locator("#briefing-date").inner_text()
        page.locator('[data-view="injector"]').click()
        assert page.locator("#telemetry-table tr").count() == 40
        page.locator('[data-view="overview"]').click()
        page.locator("#fit-map").click()
        Path(".local").mkdir(exist_ok=True)
        page.screenshot(path=str(Path(".local") / "fleet-dashboard.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(700)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(Path(".local") / "fleet-mobile.png"), full_page=True)
        assert not errors, errors
        browser.close()
        print("Real fleet dashboard, 40 visible map markers, navigation, filters, and mobile layout passed.")


if __name__ == "__main__":
    main()
