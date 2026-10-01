from __future__ import annotations

import json

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig, FixedRatioVersionSelectionRule, PromptAgentDefinition,
    PromptAgentDefinitionTextOptions, ProtocolConfiguration, ResponsesProtocolConfiguration,
    TextResponseFormatJsonObject, VersionSelector,
)

from fleet.foundry import AGENT_INSTRUCTIONS, AGENT_NAME, FoundryEvidenceAgent
from tools.cloud import Cloud, CONFIG, ROOT, az, load_state, save_state


def main():
    cloud, state = Cloud(), load_state()
    account = CONFIG["resource_prefix"] + "-foundry"
    deployment = az(
        "deployment", "group", "create", "--name", "caldova-foundry",
        "--resource-group", CONFIG["resource_group"], "--subscription", CONFIG["subscription_id"],
        "--template-file", str(ROOT / "infra" / "foundry.bicep"),
        "--parameters", f"accountName={account}", f"location={CONFIG['location']}",
        f"runtimePrincipalId={state['appIdentity']}", f"operatorPrincipalId={CONFIG['admin_object_id']}",
    )
    output = {key: item["value"] for key, item in deployment["properties"]["outputs"].items()}
    project_info = az(
        "cognitiveservices", "account", "project", "show", "--name", account,
        "--resource-group", CONFIG["resource_group"], "--subscription", CONFIG["subscription_id"],
        "--project-name", output["foundryProjectName"],
    )
    endpoint = project_info["properties"]["endpoints"]["AI Foundry API"]
    with AIProjectClient(endpoint=endpoint, credential=cloud.credential) as project:
        agent = project.agents.create_version(
            agent_name=AGENT_NAME,
            definition=PromptAgentDefinition(
                model=output["modelDeployment"], instructions=AGENT_INSTRUCTIONS,
                temperature=0,
                text=PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonObject()),
            ),
        )
        project.agents.update_details(
            agent_name=AGENT_NAME,
            agent_endpoint=AgentEndpointConfig(
                version_selector=VersionSelector(version_selection_rules=[
                    FixedRatioVersionSelectionRule(agent_version=agent.version, traffic_percentage=100),
                ]),
                protocol_configuration=ProtocolConfiguration(responses=ResponsesProtocolConfiguration()),
            ),
        )
    proposed = {
        "foundry_account_id": output["accountId"], "foundry_project_id": output["projectId"],
        "foundry_account_name": account, "foundry_project_name": output["foundryProjectName"],
        "foundry_project_endpoint": endpoint, "foundry_model_deployment": output["modelDeployment"],
        "foundry_agent_name": agent.name, "foundry_agent_version": agent.version, "foundry_agent_id": agent.id,
    }
    smoke = FoundryEvidenceAgent(proposed, cloud.credential).invoke(
        'Return a JSON object with ready set to true and provider set to "Microsoft Foundry".',
        "Confirm that the published evidence agent is ready. No customer information is included.",
    )
    if smoke.data.get("ready") is not True:
        raise RuntimeError("The actual Foundry agent did not pass its readiness request.")
    state.update(proposed)
    save_state(state)
    print(json.dumps({**proposed, "verified_response_id": smoke.trace["response_id"]}, indent=2))


if __name__ == "__main__":
    main()
