from __future__ import annotations

import json

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig, FixedRatioVersionSelectionRule, PromptAgentDefinition,
    PromptAgentDefinitionTextOptions, ProtocolConfiguration, ResponsesProtocolConfiguration,
    TextResponseFormatJsonObject, VersionSelector,
)

from fleet.customer_agent import customer_prompt
from fleet.demo_case import PHOTO, VEHICLE_DETAILS
from fleet.evidence import safe_image
from fleet.foundry import CUSTOMER_AGENT_INSTRUCTIONS, CUSTOMER_AGENT_NAME, FoundryEvidenceAgent
from tools.cloud import Cloud, ROOT, load_state, save_state


def main():
    cloud, state = Cloud(), load_state()
    with AIProjectClient(endpoint=state["foundry_project_endpoint"], credential=cloud.credential) as project:
        agent = project.agents.create_version(
            agent_name=CUSTOMER_AGENT_NAME,
            definition=PromptAgentDefinition(
                model=state["foundry_model_deployment"], instructions=CUSTOMER_AGENT_INSTRUCTIONS,
                temperature=0.8,
                text=PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonObject()),
            ),
        )
        project.agents.update_details(
            agent_name=CUSTOMER_AGENT_NAME,
            agent_endpoint=AgentEndpointConfig(
                version_selector=VersionSelector(version_selection_rules=[
                    FixedRatioVersionSelectionRule(agent_version=agent.version, traffic_percentage=100),
                ]),
                protocol_configuration=ProtocolConfiguration(responses=ResponsesProtocolConfiguration()),
            ),
        )
    proposed = {"customer_agent_name": agent.name, "customer_agent_version": agent.version, "customer_agent_id": agent.id}
    vehicle = {**VEHICLE_DETAILS, "City": "London"}
    telemetry = {"PeakAccelerationG": 3.7, "DeltaVKmh": 6.0, "SpeedBeforeKmh": 6.0}
    smoke = FoundryEvidenceAgent(state, cloud.credential, agent_name=agent.name, agent_version=agent.version).invoke(
        "Write the customer's incident report. Return the JSON object.", customer_prompt(vehicle, telemetry),
        safe_image(PHOTO.read_bytes())[0],
    )
    if len(str(smoke.data.get("description", "")).strip()) < 15:
        raise RuntimeError("The Foundry customer agent did not return a usable report.")
    state.update(proposed)
    save_state(state)
    print(json.dumps({**proposed, "sample": smoke.data["description"], "response_id": smoke.trace["response_id"]}, indent=2))


if __name__ == "__main__":
    main()
