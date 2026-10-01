$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$config = Get-Content (Join-Path $root 'demo.config.json') -Raw | ConvertFrom-Json
$insurance = Get-Content (Join-Path $root 'insurance.config.json') -Raw | ConvertFrom-Json
$state = Get-Content (Join-Path $root '.local\deployment.json') -Raw | ConvertFrom-Json
$account = az account show -o json | ConvertFrom-Json
if ($account.tenantId -ne $config.tenant_id -or $account.id -ne $config.subscription_id) {
    throw 'Wrong Azure tenant or subscription.'
}
$module = Get-ChildItem (Join-Path $root '.local\psmodules\ExchangeOnlineManagement') -Directory |
    Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
Import-Module (Join-Path $module.FullName 'ExchangeOnlineManagement.psd1')
$raw = az account get-access-token --tenant $config.tenant_id --resource https://outlook.office365.com -o json
if ($LASTEXITCODE -ne 0) { throw 'Could not acquire Caldova Exchange token.' }
$token = $raw | ConvertFrom-Json
Connect-ExchangeOnline -AccessToken $token.accessToken -UserPrincipalName $config.report_recipient -ShowBanner:$false
try {
    $organization = Get-OrganizationConfig
    if ($organization.Name -ne $config.tenant_domain) { throw 'Connected Exchange organization is not Caldova.' }
    $mailboxes = @([pscustomobject]@{ name = 'Caldova Claims Operations'; mailbox = $insurance.claims_mailbox }) + @($insurance.garages)
    foreach ($entry in $mailboxes) {
        $address = $entry.mailbox
        if (-not $address.EndsWith('@' + $config.tenant_domain, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Mailbox outside Caldova: $address"
        }
        $existing = @(Get-Mailbox -Filter "PrimarySmtpAddress -eq '$address'")
        if ($existing.Count -eq 0) {
            New-Mailbox -Shared -Name $entry.name -DisplayName $entry.name -Alias $address.Split('@')[0] -PrimarySmtpAddress $address | Out-Null
        } elseif ($existing[0].RecipientTypeDetails -ne 'SharedMailbox') {
            throw "Refusing to repurpose a non-shared mailbox: $address"
        }
        Set-Mailbox -Identity $address -CustomAttribute15 CaldovaDriveRepairDemo
        $access = @(Get-MailboxPermission -Identity $address -User $config.report_recipient)
        if (-not ($access | Where-Object { $_.AccessRights -contains 'FullAccess' -and -not $_.Deny })) {
            Add-MailboxPermission -Identity $address -User $config.report_recipient -AccessRights FullAccess -InheritanceType All -AutoMapping:$false | Out-Null
        }
        $sendAs = @(Get-RecipientPermission -Identity $address -Trustee $config.report_recipient)
        if (-not ($sendAs | Where-Object { $_.AccessRights -contains 'SendAs' })) {
            Add-RecipientPermission -Identity $address -Trustee $config.report_recipient -AccessRights SendAs -Confirm:$false | Out-Null
        }
        Write-Output "Ready: $address"
    }
    $scopeName = 'Caldova Drive Repair Mailboxes'
    if (-not (Get-ManagementScope | Where-Object Name -eq $scopeName)) {
        New-ManagementScope -Name $scopeName -RecipientRestrictionFilter "CustomAttribute15 -eq 'CaldovaDriveRepairDemo'" | Out-Null
    }
    foreach ($identity in @(
        @{ AppId = $state.agent_app_id; ObjectId = $state.agent_principal_id; Label = 'Fleet agent transport' },
        @{ AppId = '622fc4cd-50da-4837-98b3-8014ea818f3a'; ObjectId = $state.appIdentity; Label = 'Fleet managed identity' }
    )) {
        $principal = Get-ServicePrincipal | Where-Object ObjectId -eq $identity.ObjectId
        if (-not $principal) {
            New-ServicePrincipal -AppId $identity.AppId -ObjectId $identity.ObjectId -DisplayName ('Caldova Drive - ' + $identity.Label) | Out-Null
        }
        foreach ($role in @('Application Mail.ReadWrite', 'Application Mail.Send')) {
            $assignmentName = 'CaldovaRepair-' + $identity.ObjectId.Substring(0, 8) + '-' + $role.Replace('Application ', '')
            if (-not (Get-ManagementRoleAssignment | Where-Object Name -eq $assignmentName)) {
                New-ManagementRoleAssignment -Name $assignmentName -App $identity.ObjectId -Role $role -CustomResourceScope $scopeName | Out-Null
            }
        }
        Test-ServicePrincipalAuthorization -Identity $identity.ObjectId -Resource $insurance.claims_mailbox |
            Select-Object RoleName, InScope | Format-Table -AutoSize
        $outside = @(Test-ServicePrincipalAuthorization -Identity $identity.ObjectId -Resource $config.report_recipient)
        if ($outside | Where-Object { "$($_.InScope)" -eq 'True' }) { throw 'Mailbox scope unexpectedly includes the operator mailbox.' }
    }
} finally {
    Disconnect-ExchangeOnline -Confirm:$false
}
