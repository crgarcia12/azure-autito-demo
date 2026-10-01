from __future__ import annotations

import argparse
import json
from pathlib import Path

from content_studio.auth import AuthorSession
from content_studio.publish import Publisher, validate_plan, word_document
from content_studio.scenario import build_plan
from tools.cloud import ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description="Create real Caldova Microsoft 365 content for Work IQ demonstrations.")
    commands = parser.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login", help="Connect one approved demo author using delegated sign-in.")
    login.add_argument("--user", required=True)
    commands.add_parser("status", help="Verify connected authors without posting content.")
    commands.add_parser("plan", help="Build the approved rich scenario from current Fabric facts.")
    publish = commands.add_parser("publish", help="Publish a reviewed plan to the real Caldova tenant.")
    publish.add_argument("--plan", type=Path, default=ROOT / ".local" / "content-plan.json")
    publish.add_argument("--approve-run", required=True, help="The runId from the reviewed plan.")
    args = parser.parse_args()
    if args.command == "login":
        AuthorSession(args.user).login()
    elif args.command == "status":
        options = json.loads((ROOT / "content.config.json").read_text(encoding="utf-8"))
        failed = []
        for author in options["authors"]:
            try:
                user = AuthorSession(author["upn"]).verify()
                print(f"Connected: {user['displayName']} ({user['userPrincipalName']})")
            except RuntimeError as error:
                print(str(error))
                failed.append(author["upn"])
        if failed:
            raise SystemExit(1)
    elif args.command == "plan":
        from content_studio.auth import personas
        path = ROOT / ".local" / "content-plan.json"
        if path.exists():
            raise RuntimeError("A content plan already exists. Review it before replacing or publishing it.")
        plan = build_plan()
        validate_plan(plan, personas())
        path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        document_directory = ROOT / ".local" / "content-documents"
        document_directory.mkdir(exist_ok=True)
        for document in plan["documents"]:
            (document_directory / f"{document['id']} - {document['title']}.docx").write_bytes(
                word_document(document, plan["source"])
            )
        print(f"Plan: {path}")
        print(f"Run ID: {plan['runId']}")
        print("8 conversations; 64 persona-authored messages; 5 Teams meetings; 6 shared Word documents.")
        print(f"Grounding: {plan['source']['reportDate']}, {plan['source']['totalKm']:,.1f} km from Fabric.")
        print(f"Six Word documents prepared locally in {document_directory}; nothing has been published.")
    else:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        if args.approve_run != plan["runId"]:
            raise RuntimeError("The approved run ID does not match the plan. Nothing was sent.")
        result = Publisher(plan).publish()
        print(f"Published in Caldova: {len(result['conversations'])} conversations, {len(result['meetings'])} meetings, {len(result['documents'])} documents.")


if __name__ == "__main__":
    main()
