from __future__ import annotations

import httpx

from tools.cloud import Cloud, load_state, save_state


def main():
    cloud, state = Cloud(), load_state()
    root = state["dataverse_url"] + "/api/data/v9.2"
    token = cloud.credential.get_token(state["dataverse_url"] + "/.default").token
    with httpx.Client(headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout=90) as client:
        agents = state["studio_agents"]
        for schema, agent in agents.items():
            response = client.patch(root + f"/bots({agent['id']})", json={
                "authenticationmode": 1, "authenticationtrigger": 0,
            })
            response.raise_for_status()
            response = client.post(root + f"/bots({agent['id']})/Microsoft.Dynamics.CRM.PvaPublish", json={})
            response.raise_for_status()
            print(f"Publication requested: {schema}", flush=True)
    save_state(state)


if __name__ == "__main__":
    main()
