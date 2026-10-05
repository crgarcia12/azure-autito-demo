from html.parser import HTMLParser
import json
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright, expect
from fleet.config import ROOT
from fleet.demo_case import CUSTOMER_EMAIL, CUSTOMER_NAME, DESCRIPTION, PHOTO, VEHICLE_DETAILS
from fleet.evidence import safe_image


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ids = []

    def handle_data(self, value):
        self.parts.append(value)

    def handle_starttag(self, tag, attrs):
        self.ids.extend(value for key, value in attrs if key == "id")


def test_portal_pages_use_operational_labels_and_retain_required_controls():
    required = {
        "index.html": {"page-title", "page-description", "fleet-map", "vehicles-table", "inject-impact", "case-list", "case-detail", "generate-briefing", "send-briefing"},
        "report.html": {"report-form", "photos", "description", "name", "email", "consent", "submit", "confirmation"},
    }
    for name, ids in required.items():
        page = PageText()
        page.feed((ROOT / "static" / name).read_text(encoding="utf-8"))
        visible = " ".join(page.parts).casefold()
        assert "caldova" not in visible
        assert not any(phrase in visible for phrase in (
            "a better way", "one confident decision", "before your first coffee",
            "your fleet has answers", "a small bump", "a clear next step",
            "every decision has a story", "let the data do the talking",
        ))
        assert ids.issubset(page.ids)
        assert len(page.ids) == len(set(page.ids))
        if name == "report.html":
            assert "safe" not in page.ids and "injuries" not in page.ids
            assert "someone may be injured" not in visible
            assert "i am in a safe place" not in visible and "safety information" not in visible
            assert page.ids.index("name") < page.ids.index("photos")
            assert page.ids.index("email") < page.ids.index("description")
        else:
            assert "on hire" in visible and "incident detected" in visible
            assert not any(label in visible for label in ("charging", "low battery", "battery / fuel"))


def test_supplied_photo_is_the_packaged_upload_source():
    assert PHOTO == ROOT / "media" / "crash1.png"
    data, width, height = safe_image(PHOTO.read_bytes())
    assert (width, height) == (1536, 1024)
    assert data.startswith(b"\xff\xd8")


@pytest.mark.parametrize("weather_available", [True, False])
def test_customer_form_prefills_remain_editable_and_weather_never_rewrites_the_account(weather_available):
    submitted = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = urlparse(route.request.url).path
            if path.startswith("/static/") or path.startswith("/report/"):
                file = ROOT / "static" / ("report.html" if path.startswith("/report/") else path.rsplit("/", 1)[1])
                types = {".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml"}
                headers = {"Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'"} if path.startswith("/report/") else {}
                route.fulfill(body=file.read_bytes(), content_type=types[file.suffix], headers=headers)
            elif path.endswith("/weather"):
                route.fulfill(status=200 if weather_available else 503, content_type="application/json", body=json.dumps({
                    "summary": "No rain reported · No fog reported", "station_name": "Stornoway Airport",
                    "day_summary": "Rain reported earlier that day; no fog was reported.",
                    "observed_at": "2026-10-04T21:50:00Z", "visibility": "10 km or more",
                    "source_url": "https://aviationweather.gov/data/metar/?id=EGPO",
                } if weather_available else {"error": "Weather source unavailable."}))
            elif path.endswith("/photos"):
                route.fulfill(content_type="application/json", body='{"id":"photo-1"}')
            elif path.endswith("/submit"):
                submitted.append(route.request.post_data_json)
                route.fulfill(content_type="application/json", body='{"status":"evidence_received"}')
            else:
                route.fulfill(content_type="application/json", body=json.dumps({
                    "id": "CDI-0000000001", "created_at": "2026-10-04T21:55:00Z",
                    "report_received": False, "photo_count": 0, "vehicle": VEHICLE_DETAILS,
                    "weather_supported": True,
                    "report_defaults": {"customer_name": CUSTOMER_NAME, "customer_email": CUSTOMER_EMAIL, "description": ""},
                }))

        page.route("http://report.test/**", respond)
        page.goto("http://report.test/report/CDI-0000000001#test-capability", wait_until="networkidle")
        page.locator("#content").wait_for(state="visible")
        assert page.locator("#safe").count() == 0 and page.locator(".safety").count() == 0
        assert page.locator("#injuries").count() == 0
        assert page.locator("#name").input_value() == CUSTOMER_NAME
        assert page.locator("#email").input_value() == CUSTOMER_EMAIL
        assert page.locator("#description").input_value() == ""
        assert page.locator("#name").bounding_box()["y"] < page.locator("#photos").locator("..").bounding_box()["y"]
        assert "Checking" not in page.locator("#weather-status").inner_text()
        assert ("No rain reported" if weather_available else "Weather unavailable") in page.locator("#weather-status").inner_text()
        page.locator("#name").fill("Sam Taylor")
        page.locator("#email").fill("sam.taylor@example.com")
        page.locator("#description").fill(DESCRIPTION)
        page.locator("#photos").set_input_files(str(PHOTO))
        expect(page.locator("#upload-status")).to_contain_text("uploaded securely")
        page.locator("#consent").check()
        page.locator("#submit").click()
        page.locator("#complete").wait_for(state="visible")
        assert submitted[0]["customer_name"] == "Sam Taylor"
        assert submitted[0]["customer_email"] == "sam.taylor@example.com"
        assert submitted[0]["description"] == DESCRIPTION and "safe" not in submitted[0] and "injuries" not in submitted[0]
        assert page.locator("body").inner_text().rstrip().endswith("Your case reference is CDI-0000000001.")
        assert page.locator("#complete .steps").count() == 0
        assert not errors, errors
        browser.close()
