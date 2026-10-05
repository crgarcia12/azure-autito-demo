"""Verify corrected MINI photographs and the trimmed customer acknowledgement on the hosted app."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import time

import httpx
import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from tools.cloud import Cloud, ROOT, load_state


def assert_masked(payload: bytes, rectangles: list[tuple[int, int, int, int]]) -> None:
    with Image.open(io.BytesIO(payload)) as image:
        assert image.size == (1536, 1024)
        for rectangle in rectangles:
            pixels = np.asarray(image.crop(rectangle)).astype(np.int16)
            covered = np.max(np.abs(pixels - np.array([20, 39, 31])), axis=2) <= 5
            assert covered.mean() >= .99, f"Identifying region {rectangle} is not fully masked."


def main(case_id: str, *, reprocess: bool = False) -> None:
    if not re.fullmatch(r"CDI-[A-F0-9]{10}", case_id):
        raise ValueError("Invalid case identifier.")
    cloud, config = Cloud(), load_state()
    origin = config["appUrl"]
    token = cloud.credential.get_token(f"api://{config['agent_app_id']}/.default").token
    headers = {"Authorization": "Bearer " + token, "X-Caldova-Request": "fleet-app"}
    with httpx.Client(headers=headers, timeout=120) as client:
        response = client.get(origin + "/health/live")
        response.raise_for_status()
        build = response.json()["buildId"]
        assert build == (ROOT / ".local" / "build-id.txt").read_text().strip()
        path = origin + "/api/incidents/" + case_id
        response = client.get(path)
        response.raise_for_status()
        before = response.json()
        expected_regions = {
            hashlib.sha256((ROOT / "media" / "crash2.png").read_bytes()).hexdigest(): [
                (275, 95, 352, 171), (1230, 160, 1290, 232), (935, 686, 1160, 752),
            ],
            hashlib.sha256((ROOT / "media" / "crash1.png").read_bytes()).hexdigest(): [(1210, 478, 1530, 620)],
        }
        assert set(expected_regions).issubset({photo["sha256"] for photo in before["photos"]})
        already_processed = all(photo.get("face_detector") and photo.get("text_detector")
                                for photo in before.get("repair_report", {}).get("photos", [])) and bool(before.get("repair_report"))
        started = False
        if reprocess and not already_processed:
            if before["status"] != "report_review_required":
                raise RuntimeError("The case is not awaiting evidence review; its existing workflow will not be changed.")
            response = client.post(path + "/reprocess-evidence", json={"version": before["version"]})
            response.raise_for_status()
            started = True
        deadline = time.monotonic() + 360
        while time.monotonic() < deadline:
            response = client.get(path)
            response.raise_for_status()
            case = response.json()
            if case.get("last_error"):
                raise RuntimeError(case["last_error"]["message"])
            report = case.get("repair_report", {})
            if report and all(photo.get("face_detector") and photo.get("text_detector") for photo in report["photos"]):
                break
            time.sleep(5)
        else:
            raise TimeoutError("The hosted evidence reassessment did not complete.")
        assert case["customer_report"] == before["customer_report"]
        assert case["photos"] == before["photos"]
        assert report["privacy_passed"] and all(photo["privacy_verified"] for photo in report["photos"])
        assert report["evidence_agent"]["version"] == config["foundry_agent_version"]
        if started:
            assert case["assessment_history"][-1]["repair_report"] == before["repair_report"]
        for photo in case["photos"]:
            original = client.get(path + "/photos/" + photo["id"] + "?original=true")
            original.raise_for_status()
            assert hashlib.sha256(original.content).hexdigest() == photo["sha256"]
            masked = client.get(path + "/photos/" + photo["id"] + "?redacted=true")
            masked.raise_for_status()
            if photo["sha256"] in expected_regions:
                assert_masked(masked.content, expected_regions[photo["sha256"]])
            if len(expected_regions.get(photo["sha256"], [])) == 3:
                (ROOT / ".local" / "corrected-face-redaction.jpg").write_bytes(masked.content)
        response = client.post(path + "/link", json={})
        response.raise_for_status()
        link = response.json()["url"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(link, wait_until="domcontentloaded")
        expect(page.locator("#complete")).to_be_visible(timeout=60000)
        expect(page.locator("#injuries")).to_have_count(0)
        expect(page.locator("#safe")).to_have_count(0)
        expect(page.locator("#complete .steps")).to_have_count(0)
        assert page.locator("body").inner_text().rstrip().endswith("Your case reference is " + case_id + ".")
        assert "#" not in page.url
        page.screenshot(path=str(ROOT / ".local" / "report-confirmation.png"), full_page=True)
        assert not errors, errors
        browser.close()
    proof = {
        "case_id": case_id, "build_id": build, "faces_masked": 2, "plates_masked": 2,
        "privacy_passed": True, "original_uploads_preserved": True, "customer_report_preserved": True,
        "previous_assessment_preserved": started or bool(case.get("assessment_history")),
        "confirmation_ends_at_case_reference": True, "evidence_agent_version": config["foundry_agent_version"],
    }
    (ROOT / ".local" / "hosted-redaction-verified.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps(proof), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--reprocess", action="store_true")
    args = parser.parse_args()
    main(args.case, reprocess=args.reprocess)
