targetScope = 'resourceGroup'

@minLength(3)
@maxLength(7)
param namePrefix string = 'regula'
param location string = resourceGroup().location
@description('Explicit operator CIDRs for the data plane. Empty means deny public access.')
param operatorCidrs array = []
var suffix = uniqueString(resourceGroup().id)
var compact = '${namePrefix}${suffix}'
var tags = { application: 'regula', managedBy: 'bicep' }

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-worker'
  location: location
  tags: tags
}
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-logs-${suffix}'
  location: location
  tags: tags
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}
resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${namePrefix}-insights-${suffix}'
  location: location
  kind: 'web'
  tags: tags
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id, DisableLocalAuth: true }
}
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: compact
  location: location
  tags: tags
  sku: { name: 'Standard_ZRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: empty(operatorCidrs) ? 'Disabled' : 'Enabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'None', ipRules: [for cidr in operatorCidrs: { value: cidr, action: 'Allow' }] }
  }
}
resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: { deleteRetentionPolicy: { enabled: true, days: 30 }, isVersioningEnabled: true }
}
resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for name in ['sources', 'passages', 'reports', 'manifests']: {
  parent: blobs
  name: name
  properties: { publicAccess: 'None' }
}]
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: '${namePrefix}-cosmos-${suffix}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    disableLocalAuth: true
    minimalTlsVersion: 'Tls12'
    publicNetworkAccess: empty(operatorCidrs) ? 'Disabled' : 'Enabled'
    ipRules: [for cidr in operatorCidrs: { ipAddressOrRange: cidr }]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [{ locationName: location, failoverPriority: 0, isZoneRedundant: false }]
    backupPolicy: { type: 'Continuous', continuousModeProperties: { tier: 'Continuous7Days' } }
  }
}
resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmos
  name: 'research'
  properties: { resource: { id: 'research' }, options: { throughput: 400 } }
}
resource records 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: 'records'
  properties: { resource: { id: 'records', partitionKey: { paths: ['/project_scope'], kind: 'Hash', version: 2 } } }
}
resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: '${namePrefix}-search-${suffix}'
  location: location
  tags: tags
  sku: { name: 'standard' }
  properties: {
    replicaCount: 2
    partitionCount: 1
    hostingMode: 'default'
    disableLocalAuth: true
    publicNetworkAccess: empty(operatorCidrs) ? 'disabled' : 'enabled'
    networkRuleSet: { ipRules: [for cidr in operatorCidrs: { value: cidr }] }
  }
}
resource bus 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: '${namePrefix}-bus-${suffix}'
  location: location
  tags: tags
  sku: { name: 'Premium', tier: 'Premium', capacity: 1 }
  properties: { disableLocalAuth: true, minimumTlsVersion: '1.2', publicNetworkAccess: 'Disabled' }
}
resource queues 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' = [for name in ['research', 'review', 'release-outbox']: {
  parent: bus
  name: name
  properties: {
    requiresDuplicateDetection: true
    duplicateDetectionHistoryTimeWindow: 'PT10M'
    deadLetteringOnMessageExpiration: true
    maxDeliveryCount: 5
    lockDuration: 'PT5M'
  }
}]
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${namePrefix}-kv-${suffix}'
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enablePurgeProtection: true
    softDeleteRetentionInDays: 90
    publicNetworkAccess: 'Disabled'
  }
}
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: '${namePrefix}-foundry-${suffix}'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    customSubDomainName: '${namePrefix}-foundry-${suffix}'
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
  }
}
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: 'research'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: { displayName: 'Regula research', description: 'Evidence-grounded research agents' }
}

// Private endpoints share a dedicated subnet; application hosting must join this VNet.
resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${namePrefix}-vnet'
  location: location
  tags: tags
  properties: { addressSpace: { addressPrefixes: ['10.42.0.0/16'] } }
}
resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: network
  name: 'private-endpoints'
  properties: { addressPrefix: '10.42.0.0/24', privateEndpointNetworkPolicies: 'Disabled' }
}
var services = [
  { name: 'blob', id: storage.id, group: 'blob', dns: 'privatelink.blob.${environment().suffixes.storage}' }
  { name: 'cosmos', id: cosmos.id, group: 'Sql', dns: 'privatelink.documents.azure.com' }
  { name: 'search', id: search.id, group: 'searchService', dns: 'privatelink.search.windows.net' }
  { name: 'bus', id: bus.id, group: 'namespace', dns: 'privatelink.servicebus.windows.net' }
  { name: 'vault', id: vault.id, group: 'vault', dns: 'privatelink.vaultcore.azure.net' }
  { name: 'foundry', id: foundry.id, group: 'account', dns: 'privatelink.cognitiveservices.azure.com' }
]
resource zones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for service in services: {
  name: service.dns
  location: 'global'
}]
resource links 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (service, i) in services: {
  parent: zones[i]
  name: '${namePrefix}-link'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: network.id } }
}]
resource endpoints 'Microsoft.Network/privateEndpoints@2024-05-01' = [for service in services: {
  name: '${namePrefix}-${service.name}-pe'
  location: location
  properties: {
    subnet: { id: subnet.id }
    privateLinkServiceConnections: [{ name: service.name, properties: { privateLinkServiceId: service.id, groupIds: [service.group] } }]
  }
}]
resource zoneGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = [for (service, i) in services: {
  parent: endpoints[i]
  name: 'default'
  properties: { privateDnsZoneConfigs: [{ name: service.name, properties: { privateDnsZoneId: zones[i].id } }] }
}]

resource blobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, identity.id, 'blob-contributor')
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe') }
}
resource cosmosRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, identity.id, 'data-contributor')
  properties: { principalId: identity.properties.principalId, roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002', scope: '${cosmos.id}/dbs/research' }
}
output managedIdentityId string = identity.id
output foundryProjectId string = project.id
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output storageAccountName string = storage.name
output searchServiceName string = search.name
output serviceBusNamespace string = bus.name
output privateNetworkId string = network.id
