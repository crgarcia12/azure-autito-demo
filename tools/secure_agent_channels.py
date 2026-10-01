from __future__ import annotations

import argparse
import json
import sys

import httpx
from msal_extensions import FilePersistenceWithDataProtection
from msal_extensions.persistence import PersistenceNotFound

from tools.cloud import Cloud, ROOT, load_state, save_state
from tools.deploy import app_path


def main():
    parser = argparse.ArgumentParser(description="Stage native agent channel credentials under Windows DPAPI and publish them to Azure settings.")
    parser.add_argument("--schema")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--verify-copy", action="store_true", help="Confirm a native page's copied credential matches the already validated agent.")
    args = parser.parse_args()
    cloud, state = Cloud(), load_state()
    persistence = FilePersistenceWithDataProtection(str(ROOT / ".local" / "studio-channel-secrets.bin"))
    try:
        secrets = json.loads(persistence.load())
    except PersistenceNotFound:
        secrets = {}
    if args.schema:
        if args.schema not in state["studio_agents"]:
            raise ValueError("Unknown Caldova agent schema.")
        secret = sys.stdin.read().strip()
        if not 20 <= len(secret) <= 1024 or any(char.isspace() for char in secret):
            raise ValueError("Expected a copied Direct Line channel secret on standard input.")
        if args.verify_copy and secrets.get(args.schema) != secret:
            raise RuntimeError("The visible native page does not match this agent's verified channel credential.")
        response = httpx.post(
            "https://directline.botframework.com/v3/directline/tokens/generate",
            headers={"Authorization": f"Bearer {secret}"}, timeout=60,
        )
        response.raise_for_status()
        if "token" not in response.json():
            raise RuntimeError("Direct Line did not validate the supplied channel secret.")
        if any(value == secret for schema, value in secrets.items() if schema != args.schema):
            raise RuntimeError("This credential was already captured for a different agent. Verify the native page before continuing.")
        secrets[args.schema] = secret
        persistence.save(json.dumps(secrets))
        print(f"Validated and encrypted the channel credential for {args.schema}.")
    if args.publish:
        if set(secrets) != set(state["studio_agents"]):
            raise RuntimeError("All four native agent credentials must be validated before publication.")
        if len(set(secrets.values())) != 4:
            raise RuntimeError("Each native agent must have its own channel credential.")
        path = app_path(state) + "/config/appsettings"
        app_settings = cloud.request("POST", path + "/list?api-version=2023-12-01")["properties"]
        app_settings["FLEET_STUDIO_CHANNEL_SECRETS"] = json.dumps(secrets)
        cloud.request("PUT", path + "?api-version=2023-12-01", {"properties": app_settings})
        state["studio_channel_credentials_configured"] = True
        save_state(state)
        print("All four native channel credentials are now stored only in protected Azure application configuration.")


if __name__ == "__main__":
    main()
