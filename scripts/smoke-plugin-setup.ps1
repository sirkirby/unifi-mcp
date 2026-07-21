param(
    [string]$RepositoryRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$ExpectedVersionPrefix = ''
)

$ErrorActionPreference = 'Stop'
$script:Passes = 0
$script:Failures = New-Object System.Collections.Generic.List[string]

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if ($Condition) {
        Write-Host "  [OK]   $Message"
        $script:Passes++
    } else {
        Write-Host "  [FAIL] $Message"
        $script:Failures.Add($Message)
    }
}

function Assert-Equal {
    param($Actual, $Expected, [string]$Message)
    Assert-True -Condition ($Actual -eq $Expected) -Message $Message
}

function Get-CurrentShellPath {
    if ($PSVersionTable.PSEdition -eq 'Desktop') {
        return Join-Path $PSHOME 'powershell.exe'
    }
    if ($null -ne $IsWindows -and $IsWindows) {
        return Join-Path $PSHOME 'pwsh.exe'
    }
    return Join-Path $PSHOME 'pwsh'
}

function Invoke-SetEnv {
    param(
        [string]$Workspace,
        [string]$ScriptPath,
        [string[]]$Arguments
    )

    Push-Location $Workspace
    try {
        # Windows PowerShell 5.1 promotes native stderr records to terminating
        # NativeCommandError exceptions when the caller uses Stop. Expected
        # failure scenarios need the child exit code and output instead.
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $output = & (Get-CurrentShellPath) -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $ScriptPath @Arguments 2>&1
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        return [pscustomobject]@{
            ExitCode = $exitCode
            Output = ($output | Out-String)
        }
    } finally {
        Pop-Location
    }
}

function New-ScenarioWorkspace {
    param([string]$Root, [string]$Name)
    $workspace = Join-Path $Root $Name
    New-Item -ItemType Directory -Path (Join-Path $workspace '.claude') -Force | Out-Null
    return $workspace
}

function Get-BytesBase64 {
    param([string]$Path)
    return [Convert]::ToBase64String([IO.File]::ReadAllBytes($Path))
}

function Assert-NoReplacementArtifacts {
    param([string]$Workspace, [string]$Message)
    $settingsDirectory = Join-Path $Workspace '.claude'
    $artifacts = @(Get-ChildItem -LiteralPath $settingsDirectory -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -like 'settings.local.json.tmp.*' -or $_.Name -like 'settings.local.json.backup.*'
    })
    Assert-Equal -Actual $artifacts.Count -Expected 0 -Message $Message
}

function New-NestedSettingsJson {
    param([int]$Depth)
    $value = '{"leaf":"preserved"}'
    for ($index = $Depth - 1; $index -ge 0; $index--) {
        $value = '{"level' + $index + '":' + $value + '}'
    }
    return '{"env":{"EXISTING":"keep"},"deep":' + $value + '}'
}

function Get-NestedLeaf {
    param($Settings, [int]$Depth)
    $current = $Settings.deep
    for ($index = 0; $index -lt $Depth; $index++) {
        $property = $current.PSObject.Properties["level$index"]
        if ($null -eq $property) {
            return $null
        }
        $current = $property.Value
    }
    return $current.leaf
}

function Test-IsWindows {
    return [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
}

$networkScript = Join-Path $RepositoryRoot 'plugins/unifi-network/scripts/set-env.ps1'
$protectScript = Join-Path $RepositoryRoot 'plugins/unifi-protect/scripts/set-env.ps1'
$accessScript = Join-Path $RepositoryRoot 'plugins/unifi-access/scripts/set-env.ps1'
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('unifi-mcp-plugin-setup-' + [Guid]::NewGuid().ToString('N'))

try {
    New-Item -ItemType Directory -Path $testRoot | Out-Null

    if ($ExpectedVersionPrefix) {
        Assert-True -Condition ($PSVersionTable.PSVersion.ToString().StartsWith($ExpectedVersionPrefix)) -Message 'expected PowerShell version is running'
    }

    Write-Host '== Cross-plugin parity =='
    $networkHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $networkScript).Hash
    Assert-Equal (Get-FileHash -Algorithm SHA256 -LiteralPath $protectScript).Hash $networkHash 'Protect writer matches Network writer'
    Assert-Equal (Get-FileHash -Algorithm SHA256 -LiteralPath $accessScript).Hash $networkHash 'Access writer matches Network writer'

    Write-Host '== Empty workspace =='
    $workspace = New-ScenarioWorkspace $testRoot 'empty'
    $result = Invoke-SetEnv $workspace $networkScript @('UNIFI_NETWORK_HOST=192.0.2.1', 'UNIFI_NETWORK_USERNAME=test-user')
    Assert-Equal $result.ExitCode 0 'empty-workspace write exits zero'
    $settingsPath = Join-Path $workspace '.claude/settings.local.json'
    $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    Assert-Equal $settings.env.UNIFI_NETWORK_HOST '192.0.2.1' 'empty-workspace host is written'
    Assert-Equal $settings.env.UNIFI_NETWORK_USERNAME 'test-user' 'empty-workspace username is written'
    Assert-NoReplacementArtifacts $workspace 'empty-workspace write removes replacement artifacts'

    Write-Host '== Existing settings preservation =='
    $workspace = New-ScenarioWorkspace $testRoot 'preserve'
    $settingsPath = Join-Path $workspace '.claude/settings.local.json'
    $fixture = '{"permissions":{"allow":["Read"]},"env":{"EXISTING":"keep","UNIFI_NETWORK_HOST":"192.0.2.10"},"custom":{"nested":true}}'
    [IO.File]::WriteAllText($settingsPath, $fixture)
    $result = Invoke-SetEnv $workspace $networkScript @('UNIFI_NETWORK_HOST=192.0.2.20', 'UNIFI_NETWORK_USERNAME=test-user')
    Assert-Equal $result.ExitCode 0 'existing-settings merge exits zero'
    $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    Assert-Equal @($settings.permissions.allow).Count 1 'single-item permissions array remains an array'
    Assert-Equal $settings.permissions.allow[0] 'Read' 'permissions value is preserved'
    Assert-True ($settings.custom.nested -eq $true) 'custom nested value is preserved'
    Assert-Equal $settings.env.EXISTING 'keep' 'unrelated environment value is preserved'
    Assert-Equal $settings.env.UNIFI_NETWORK_HOST '192.0.2.20' 'matching environment value is updated'
    Assert-Equal $settings.env.UNIFI_NETWORK_USERNAME 'test-user' 'new environment value is inserted'
    Assert-True ($result.Output -match 'te\*\*\*er') 'sensitive output remains masked'
    Assert-True ($result.Output -notmatch 'test-user') 'raw sensitive output is not printed'
    Assert-NoReplacementArtifacts $workspace 'successful merge removes replacement artifacts'

    Write-Host '== Deep settings preservation =='
    $workspace = New-ScenarioWorkspace $testRoot 'deep-valid'
    $settingsPath = Join-Path $workspace '.claude/settings.local.json'
    [IO.File]::WriteAllText($settingsPath, (New-NestedSettingsJson 12))
    $result = Invoke-SetEnv $workspace $networkScript @('UNIFI_NETWORK_HOST=192.0.2.1')
    Assert-Equal $result.ExitCode 0 'valid deeply nested settings exit zero'
    $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    Assert-Equal (Get-NestedLeaf $settings 12) 'preserved' 'deeply nested leaf is preserved'
    Assert-NoReplacementArtifacts $workspace 'deeply nested merge removes replacement artifacts'

    $unsafeFixtures = @(
        [pscustomobject]@{ Name = 'malformed'; Content = '{ broken' },
        [pscustomobject]@{ Name = 'array-root'; Content = '["not-an-object"]' },
        [pscustomobject]@{ Name = 'array-env'; Content = '{"permissions":{"allow":["Read"]},"env":["not-an-object"]}' },
        [pscustomobject]@{ Name = 'depth-overflow'; Content = (New-NestedSettingsJson 101) }
    )

    foreach ($fixtureCase in $unsafeFixtures) {
        Write-Host "== Unsafe input: $($fixtureCase.Name) =="
        $workspace = New-ScenarioWorkspace $testRoot $fixtureCase.Name
        $settingsPath = Join-Path $workspace '.claude/settings.local.json'
        [IO.File]::WriteAllText($settingsPath, $fixtureCase.Content)
        $before = Get-BytesBase64 $settingsPath
        $result = Invoke-SetEnv $workspace $networkScript @('UNIFI_NETWORK_HOST=192.0.2.1')
        Assert-True ($result.ExitCode -ne 0) "$($fixtureCase.Name) exits nonzero"
        Assert-Equal (Get-BytesBase64 $settingsPath) $before "$($fixtureCase.Name) remains byte-for-byte unchanged"
        Assert-NoReplacementArtifacts $workspace "$($fixtureCase.Name) removes replacement artifacts"
    }

    if (Test-IsWindows) {
        Write-Host '== Replacement failure =='
        $workspace = New-ScenarioWorkspace $testRoot 'replace-failure'
        $settingsPath = Join-Path $workspace '.claude/settings.local.json'
        $fixture = '{"permissions":{"allow":["Read"]},"env":{"EXISTING":"keep"}}'
        [IO.File]::WriteAllText($settingsPath, $fixture)
        $before = Get-BytesBase64 $settingsPath
        (Get-Item -LiteralPath $settingsPath).IsReadOnly = $true
        try {
            $result = Invoke-SetEnv $workspace $networkScript @('UNIFI_NETWORK_HOST=192.0.2.1')
            Assert-True ($result.ExitCode -ne 0) 'replacement failure exits nonzero'
            Assert-Equal (Get-BytesBase64 $settingsPath) $before 'replacement failure preserves original bytes'
            Assert-NoReplacementArtifacts $workspace 'replacement failure removes replacement artifacts'
        } finally {
            (Get-Item -LiteralPath $settingsPath).IsReadOnly = $false
        }
    }
} finally {
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}

Write-Host ''
Write-Host "PowerShell $($PSVersionTable.PSVersion): $($script:Passes) passed, $($script:Failures.Count) failed"
if ($script:Failures.Count -gt 0) {
    foreach ($failure in $script:Failures) {
        Write-Host "  - $failure"
    }
    exit 1
}
