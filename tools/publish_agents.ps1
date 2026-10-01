$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$pac = Join-Path $root '.local\pac\pac.exe'
$env:AZURE_TOKEN_CREDENTIALS = 'AzureCliCredential'
$account = az account show -o json | ConvertFrom-Json
if ($account.tenantId -ne 'b6883271-971b-4198-92a5-8ad615765572') { throw 'Only Caldova is allowed.' }
$agents = @(
    @{ folder = 'coordinator'; schema = 'cdv_repaircoordinator' },
    @{ folder = 'alder'; schema = 'cdv_alderrepairs' },
    @{ folder = 'metro'; schema = 'cdv_metrorepairs' },
    @{ folder = 'riverside'; schema = 'cdv_riversiderepairs' }
)
foreach ($agent in $agents) {
    $push = & $pac copilot push --project-dir (Join-Path $root ('copilot\' + $agent.folder)) 2>&1
    $push | Write-Output
    if ($LASTEXITCODE -ne 0) { throw "Native push failed: $($agent.schema)" }
    $publish = & $pac copilot publish --bot $agent.schema --environment https://org1a562eb0.crm.dynamics.com 2>&1
    $publish | Write-Output
    if ($LASTEXITCODE -ne 0 -or ($publish -join "`n") -notmatch 'Published successfully!') {
        throw "Copilot Studio did not confirm successful publication: $($agent.schema)"
    }
}
