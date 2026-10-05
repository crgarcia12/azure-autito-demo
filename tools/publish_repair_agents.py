from __future__ import annotations

import json
import uuid

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig, FixedRatioVersionSelectionRule, FunctionTool, PromptAgentDefinition,
    PromptAgentDefinitionTextOptions, ProtocolConfiguration, ResponsesProtocolConfiguration,
    TextResponseFormatJsonObject, VersionSelector,
)

from fleet.repair_agents import TOOL_DEFINITIONS, agent_instructions
from tools.cloud import ARM, CONFIG, Cloud, load_state, save_state

AGENTS = {
    "cdv_repaircoordinator": ("caldova-repair-coordinator", "Repair coordinator"),
    "cdv_alderrepairs": ("caldova-alder-repairs", "Alder Bodyworks"),
    "cdv_metrorepairs": ("caldova-metro-repairs", "Metro Rapid Repair"),
    "cdv_riversiderepairs": ("caldova-riverside-repairs", "Riverside Auto Care"),
}


def ensure_runtime_permissions(cloud: Cloud, state: dict) -> None:
    subscription = "/subscriptions/" + CONFIG["subscription_id"]
    role_id = str(uuid.uuid5(uuid.NAMESPACE_URL, subscription + "/fleet-repair-agent-responses"))
    role_path = subscription + "/providers/Microsoft.Authorization/roleDefinitions/" + role_id
    cloud.request("PUT", ARM + role_path + "?api-version=2022-04-01", {"properties": {
        "roleName": "Fleet Repair Agent Responses",
        "description": "Read native repair agents and execute Responses; no agent editing or connection-secret access.",
        "type": "CustomRole",
        "permissions": [{"actions": [], "notActions": [], "dataActions": [
            "Microsoft.CognitiveServices/accounts/AIServices/agents/read",
            "Microsoft.CognitiveServices/accounts/AIServices/responses/read",
            "Microsoft.CognitiveServices/accounts/AIServices/responses/write",
        ], "notDataActions": []}],
        "assignableScopes": [subscription + "/resourceGroups/" + CONFIG["resource_group"]],
    }})
    assignment = str(uuid.uuid5(uuid.NAMESPACE_URL, role_id + state["appIdentity"]))
    cloud.request("PUT", ARM + state["foundry_project_id"] + "/providers/Microsoft.Authorization/roleAssignments/" + assignment + "?api-version=2022-04-01", {
        "properties": {"roleDefinitionId": role_path, "principalId": state["appIdentity"], "principalType": "ServicePrincipal"},
    })
    print("App runtime may read agents and execute Responses in this Foundry project only.", flush=True)


def main() -> None:
    cloud, state = Cloud(), load_state()
    if not state.get("workiq_app_id"):
        raise RuntimeError("Provision and sign in to the delegated Work IQ connection first.")
    ensure_runtime_permissions(cloud, state)
    agents = {}
    with AIProjectClient(endpoint=state["foundry_project_endpoint"], credential=cloud.credential) as project:
        for schema, (name, display_name) in AGENTS.items():
            agent = project.agents.create_version(
                agent_name=name,
                definition=PromptAgentDefinition(
                    model=state["foundry_model_deployment"], instructions=agent_instructions(schema),
                    temperature=0.2, tools=[FunctionTool(**definition) for definition in TOOL_DEFINITIONS],
                    text=PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonObject()),
                ),
            )
            project.agents.update_details(
                agent_name=name,
                agent_endpoint=AgentEndpointConfig(
                    version_selector=VersionSelector(version_selection_rules=[
                        FixedRatioVersionSelectionRule(agent_version=agent.version, traffic_percentage=100),
                    ]),
                    protocol_configuration=ProtocolConfiguration(responses=ResponsesProtocolConfiguration()),
                ),
            )
            agents[schema] = {"name": agent.name, "id": agent.id, "version": agent.version, "display_name": display_name}
            state["repair_tool_agents"] = {**state.get("repair_tool_agents", {}), **agents}
            save_state(state)
            print(json.dumps(agents[schema]), flush=True)


if __name__ == "__main__":
    main()
