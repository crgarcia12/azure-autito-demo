from urllib.parse import urlencode

from tools.cloud import Cloud, FABRIC, load_state


def select_all(cloud: Cloud, base: str, root_id: str | None = None) -> int:
    url = base + (("?" + urlencode({"rootId": root_id})) if root_id else "")
    selected = 0
    for element in cloud.pages(url):
        if not element.get("isSelected"):
            cloud.request("PATCH", base + "?" + urlencode({"id": element["id"]}), {"isSelected": True})
        selected += 1
        if element.get("hasSubElements"):
            selected += select_all(cloud, base, element["id"])
    return selected


def main():
    cloud, state = Cloud(), load_state()
    base = f"{FABRIC}/workspaces/{state['workspace_id']}/dataAgents/{state['data_agent_id']}"
    count = select_all(cloud, base + f"/staging/datasources/{state['lakehouse_id']}/elements")
    print(f"Selected {count} real Lakehouse schema elements.", flush=True)
    cloud.request("POST", base + "/staging/publish", {
        "publishedDescription": "Caldova UK fleet intelligence from governed Fabric tables: vehicles, current state, rentals, branches and exact daily kilometers.",
    })
    print("Published.", flush=True)


if __name__ == "__main__":
    main()
