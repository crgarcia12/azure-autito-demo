from __future__ import annotations

import base64
import json
import argparse

import httpx
from playwright.sync_api import sync_playwright

from tools.cloud import Cloud, ROOT, load_state


def remote_read(code: str) -> str:
    cloud = Cloud()
    token = cloud.credential.get_token("https://management.azure.com/.default").token
    encoded = base64.b64encode(code.encode()).decode()
    response = httpx.post(
        "https://caldovadrive08667473.scm.azurewebsites.net/api/command",
        headers={"Authorization": f"Bearer {token}"},
        json={"command": f'python3 -c "import base64;exec(base64.b64decode(\'{encoded}\'))"', "dir": "/home"},
        timeout=90,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("ExitCode") not in (0, None) or result.get("Error"):
        raise RuntimeError("The authorized hosted-state read failed: " + result.get("Error", "")[:500])
    return result["Output"]


def main(case_id: str | None = None, photo: str = "bumper-dent.jpg"):
    if case_id is not None and not __import__("re").fullmatch(r"CDI-[A-F0-9]{10}", case_id):
        raise ValueError("Invalid verification case ID.")
    selector = f"AND id='{case_id}'" if case_id else ""
    values = json.loads(remote_read(
        "import sqlite3,json\n"
        "db=sqlite3.connect('/home/data/caldova/state.sqlite3')\n"
        f"row=db.execute(\"SELECT id FROM incidents WHERE status='awaiting_report' {selector} ORDER BY created_at DESC LIMIT 1\").fetchone()\n"
        "assert row is not None, 'No pending hosted customer incident'\n"
        "token=json.loads(db.execute('SELECT value FROM state WHERE name=?',('incident-link/'+row[0],)).fetchone()[0])['token']\n"
        "print(json.dumps({'id':row[0],'token':token}))"
    ))
    state = load_state()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(state["appUrl"] + f"/report/{values['id']}#{values['token']}", wait_until="domcontentloaded")
        page.locator("#content").wait_for(state="visible", timeout=60000)
        assert "#" not in page.url
        assert values["id"] in page.locator("#vehicle").inner_text()
        page.locator("#safe").check()
        page.locator("#photos").set_input_files(str(ROOT / "static" / "demo-assets" / photo))
        page.wait_for_function("document.getElementById('upload-status').textContent.includes('uploaded securely')", timeout=60000)
        page.locator("#description").fill(
            "The rear bumper contacted a low bollard while reversing into a parking space. "
            "There is a dent and paint scuffing on the plastic bumper. Nobody was injured and no other vehicle was involved."
        )
        page.locator("#name").fill("Taylor Example")
        page.locator("#email").fill("taylor.example@caldova08667473.onmicrosoft.com")
        page.locator("#consent").check()
        page.screenshot(path=str(ROOT / ".local" / "customer-report-mobile.png"), full_page=True)
        page.locator("#submit").click()
        page.locator("#complete").wait_for(state="visible", timeout=60000)
        assert values["id"] in page.locator("#confirmation").inner_text()
        assert not errors, errors
        page.screenshot(path=str(ROOT / ".local" / "customer-report-received.png"), full_page=True)
        browser.close()
    (ROOT / ".local" / "hosted-verification.json").write_text(json.dumps({"case_id": values["id"]}), encoding="utf-8")
    print(f"Hosted mobile report submitted successfully: {values['id']}. No token was logged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case")
    parser.add_argument("--photo", choices=["bumper-dent.jpg", "bumper-detail.jpg", "bumper-overview.jpg"], default="bumper-dent.jpg")
    args = parser.parse_args()
    main(args.case, args.photo)
