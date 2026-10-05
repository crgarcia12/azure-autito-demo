from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from azure.identity import AzureCliCredential, ClientSecretCredential, ManagedIdentityCredential

ROOT = Path(__file__).resolve().parent.parent


def settings() -> dict[str, Any]:
    config = json.loads((ROOT / "demo.config.json").read_text(encoding="utf-8"))
    deployed = os.environ.get("FLEET_DEPLOYMENT")
    if deployed:
        config.update(json.loads(deployed))
    else:
        state_path = ROOT / ".local" / "deployment.json"
        if not state_path.exists():
            raise RuntimeError("Provision the demo environment before starting the application.")
        config.update(json.loads(state_path.read_text(encoding="utf-8")))
    if config["tenant_id"] != "b6883271-971b-4198-92a5-8ad615765572":
        raise RuntimeError("Only the configured demo tenant is supported.")
    return config


def data_credential():
    if os.environ.get("WEBSITE_INSTANCE_ID"):
        return ManagedIdentityCredential()
    return AzureCliCredential(tenant_id=settings()["tenant_id"], process_timeout=60)


def agent_credential():
    if os.environ.get("FLEET_AGENT_SECRET"):
        config = settings()
        return ClientSecretCredential(
            config["tenant_id"], config["agent_app_id"], os.environ["FLEET_AGENT_SECRET"]
        )
    if os.environ.get("WEBSITE_INSTANCE_ID"):
        raise RuntimeError("FLEET_AGENT_SECRET is required for the Fabric data agent.")
    return data_credential()
