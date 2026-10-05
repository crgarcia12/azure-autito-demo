param location string = 'swedencentral'
param prefix string
param tenantId string
param agentAppId string

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${prefix}-plan'
  location: location
  kind: 'linux'
  sku: {
    name: 'B1'
    tier: 'Basic'
    capacity: 1
  }
  properties: {
    reserved: true
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: prefix
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: 'Disabled'
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource state 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobs
  name: 'fleet-state'
  properties: {
    publicAccess: 'None'
  }
}

resource maps 'Microsoft.Maps/accounts@2023-06-01' = {
  name: '${prefix}-maps'
  location: 'global'
  kind: 'Gen2'
  sku: {
    name: 'G2'
  }
  properties: {
    disableLocalAuth: true
  }
}

resource app 'Microsoft.Web/sites@2023-12-01' = {
  name: prefix
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    clientAffinityEnabled: false
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      alwaysOn: true
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      appCommandLine: 'python -m fleet.web'
      appSettings: [
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
        {
          name: 'PORT'
          value: '8000'
        }
      ]
    }
  }
}

resource storageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, app.id, 'blob-contributor')
  scope: storage
  properties: {
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}

resource mapsAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(maps.id, app.id, 'maps-reader')
  scope: maps
  properties: {
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '423170ca-a8f6-4b0f-8487-9e4eb8f49bfa')
  }
}

resource bot 'Microsoft.BotService/botServices@2022-09-15' = {
  name: '${prefix}-agent'
  location: 'global'
  kind: 'azurebot'
  sku: {
    name: 'F0'
  }
  properties: {
    displayName: 'Fleet Operations'
    endpoint: 'https://${app.properties.defaultHostName}/api/messages'
    msaAppId: agentAppId
    msaAppType: 'SingleTenant'
    msaAppTenantId: tenantId
    publicNetworkAccess: 'Enabled'
  }
}

resource teams 'Microsoft.BotService/botServices/channels@2022-09-15' = {
  parent: bot
  name: 'MsTeamsChannel'
  location: 'global'
  properties: {
    channelName: 'MsTeamsChannel'
    properties: {
      isEnabled: true
    }
  }
}

output appName string = app.name
output appUrl string = 'https://${app.properties.defaultHostName}'
output appIdentity string = app.identity.principalId
output storageUrl string = storage.properties.primaryEndpoints.blob
output mapsClientId string = maps.properties.uniqueId
output mapsId string = maps.id
output storageId string = storage.id
