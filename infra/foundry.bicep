param location string = 'swedencentral'
param accountName string
param projectName string = 'caldova-insurance'
param runtimePrincipalId string
param operatorPrincipalId string

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
  tags: {
    project: 'caldova-drive'
    purpose: 'incident-evidence-agent'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  dependsOn: [
    model
  ]
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Caldova Insurance'
    description: 'Incident evidence assessment, privacy verification and redacted repair reports.'
  }
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: 'incident-vision'
  sku: {
    name: 'Standard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1'
      version: '2025-04-14'
    }
  }
}

resource runtimeAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(project.id, runtimePrincipalId, 'foundry-runtime')
  scope: project
  properties: {
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'eed3b665-ab3a-47b6-8f48-c9382fb1dad6')
  }
}

resource authorAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(project.id, operatorPrincipalId, 'foundry-author')
  scope: project
  properties: {
    principalId: operatorPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'eadc314b-1a2d-4efa-be10-5d325db5065e')
  }
}

output accountId string = foundry.id
output projectId string = project.id
output foundryAccountName string = foundry.name
output foundryProjectName string = project.name
output modelDeployment string = model.name
