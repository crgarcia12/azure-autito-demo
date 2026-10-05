from unittest.mock import Mock

from tools.cloud import CONFIG
from tools.publish_repair_agents import ensure_runtime_permissions


def test_native_runtime_role_is_limited_to_responses_without_secret_or_edit_permissions():
    cloud = Mock()
    state = {"appIdentity": "runtime-principal", "foundry_project_id": "/subscriptions/test/resourceGroups/demo/projects/insurance"}
    ensure_runtime_permissions(cloud, state)
    definition, assignment = cloud.request.call_args_list
    permissions = definition.args[2]["properties"]["permissions"][0]
    assert permissions["actions"] == []
    assert permissions["dataActions"] == [
        "Microsoft.CognitiveServices/accounts/AIServices/agents/read",
        "Microsoft.CognitiveServices/accounts/AIServices/responses/read",
        "Microsoft.CognitiveServices/accounts/AIServices/responses/write",
    ]
    assert definition.args[2]["properties"]["assignableScopes"] == [
        "/subscriptions/" + CONFIG["subscription_id"] + "/resourceGroups/" + CONFIG["resource_group"],
    ]
    assert assignment.args[1].startswith("https://management.azure.com" + state["foundry_project_id"] + "/providers/Microsoft.Authorization/roleAssignments/")
    assert assignment.args[2]["properties"]["principalId"] == state["appIdentity"]
