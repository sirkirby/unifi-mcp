param(
    [string]$RepositoryRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$ExpectedVersionPrefix = '',
    [switch]$SkipFixtures
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
    Assert-True -Condition ($Actual -ceq $Expected) -Message $Message
}

function Get-CurrentShellPath {
    if ($PSVersionTable.PSEdition -eq 'Desktop') { return (Join-Path $PSHOME 'powershell.exe') }
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) { return (Join-Path $PSHOME 'pwsh.exe') }
    return (Join-Path $PSHOME 'pwsh')
}

function Clear-ControllerEnvironment {
    param($StartInfo)
    foreach ($name in @($StartInfo.EnvironmentVariables.Keys)) {
        if ($name -like 'UNIFI_*') { $StartInfo.EnvironmentVariables.Remove($name) }
    }
}

function Invoke-PluginScript {
    param([string]$Workspace, [string]$ScriptPath, [string[]]$Arguments, [string]$InputText = '', [switch]$NoPython)
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = Get-CurrentShellPath
    $start.Arguments = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $ScriptPath + '"'
    foreach ($argument in $Arguments) { $start.Arguments += ' "' + $argument + '"' }
    $start.WorkingDirectory = $Workspace
    $start.UseShellExecute = $false
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $start.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
    Clear-ControllerEnvironment $start
    if ($NoPython) { $start.EnvironmentVariables['PATH'] = '' }
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    try {
        [void]$process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($InputText)
        $process.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
        $process.StandardInput.BaseStream.Close()
        $process.WaitForExit()
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Output = $stdoutTask.Result + $stderrTask.Result
        }
    } finally {
        $process.Dispose()
    }
}

function New-ScenarioWorkspace {
    param([string]$Root, [string]$Name)
    $workspace = Join-Path $Root $Name
    New-Item -ItemType Directory -Path $workspace -Force | Out-Null
    return $workspace
}

function Get-BytesBase64 {
    param([string]$Path)
    return [Convert]::ToBase64String([IO.File]::ReadAllBytes($Path))
}

function Invoke-DirectPipeline {
    param([string]$Workspace, [string]$ScriptPath, [string]$JsonPath)
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = Get-CurrentShellPath
    $start.Arguments = '-NoLogo -NoProfile -NonInteractive -Command "Get-Content -LiteralPath $env:PS_SETUP_INPUT_PATH -Raw -Encoding UTF8 | & $env:PS_SETUP_SCRIPT_PATH -InputJson"'
    $start.WorkingDirectory = $Workspace
    $start.UseShellExecute = $false
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $start.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
    Clear-ControllerEnvironment $start
    $start.EnvironmentVariables['PS_SETUP_INPUT_PATH'] = $JsonPath
    $start.EnvironmentVariables['PS_SETUP_SCRIPT_PATH'] = $ScriptPath
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    try {
        [void]$process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        return [pscustomobject]@{ ExitCode = $process.ExitCode; Output = $stdoutTask.Result + $stderrTask.Result }
    } finally {
        $process.Dispose()
    }
}

function Invoke-PortableFixtures {
    $python = $null
    foreach ($name in @('python3', 'python')) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $command -or $command.Source -match '[\\/]WindowsApps[\\/]python[^\\/]*\.exe$') { continue }
        try {
            $probe = & $command.Source -c "import sys; print('unifi-setup-python-ok') if sys.version_info >= (3, 11) else sys.exit(1)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $probe -ceq 'unifi-setup-python-ok') { $python = $command.Source; break }
        } catch { }
    }
    if ($null -eq $python) { return [pscustomobject]@{ ExitCode = 1; Output = 'Python 3.11+ unavailable' } }
    $fixturePath = Join-Path $RepositoryRoot 'scripts/plugin_setup_fixtures.py'
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $python
    $start.Arguments = '"' + $fixturePath + '" --powershell "' + (Get-CurrentShellPath) + '"'
    $start.WorkingDirectory = $RepositoryRoot
    $start.UseShellExecute = $false
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $start.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    try {
        [void]$process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        return [pscustomobject]@{ ExitCode = $process.ExitCode; Output = $stdoutTask.Result + $stderrTask.Result }
    } finally {
        $process.Dispose()
    }
}

function Assert-NoReplacementArtifacts {
    param([string]$Workspace, [string]$Message)
    $artifacts = @(Get-ChildItem -LiteralPath $Workspace -Recurse -Force -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -match '(\.tmp\.|\.backup\.|\.rollback\.)'
    })
    Assert-Equal $artifacts.Count 0 $Message
}

$networkDir = Join-Path $RepositoryRoot 'plugins/unifi-network/scripts'
$protectDir = Join-Path $RepositoryRoot 'plugins/unifi-protect/scripts'
$accessDir = Join-Path $RepositoryRoot 'plugins/unifi-access/scripts'
$networkScript = Join-Path $networkDir 'set-env.ps1'
$testRoot = Join-Path $RepositoryRoot ('.setup-powershell-smoke space-' + [Guid]::NewGuid().ToString('N'))
$priorHome = $env:HOME
$priorUserProfile = $env:USERPROFILE
$priorCodexHome = $env:CODEX_HOME
$priorClaudeConfigDir = $env:CLAUDE_CONFIG_DIR
$priorOpenClawStateDir = $env:OPENCLAW_STATE_DIR
$priorOpenClawConfigPath = $env:OPENCLAW_CONFIG_PATH
$priorPath = $env:PATH

try {
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    $env:HOME = $testRoot
    $env:USERPROFILE = $testRoot
    $env:CODEX_HOME = Join-Path $testRoot 'codex-home'
    $env:CLAUDE_CONFIG_DIR = Join-Path $testRoot 'claude-home'
    $env:OPENCLAW_STATE_DIR = Join-Path $testRoot 'openclaw-home'
    $env:OPENCLAW_CONFIG_PATH = Join-Path $env:OPENCLAW_STATE_DIR 'openclaw.json'
    $scratchOpenClawConfigPath = $env:OPENCLAW_CONFIG_PATH
    $fakeBin = Join-Path $testRoot 'bin'
    New-Item -ItemType Directory -Path $fakeBin | Out-Null
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        [IO.File]::WriteAllText((Join-Path $fakeBin 'uvx.cmd'), "@echo off`r`nexit /b 0`r`n")
    } else {
        $fakeUvx = Join-Path $fakeBin 'uvx'
        [IO.File]::WriteAllText($fakeUvx, "#!/bin/sh`nexit 0`n")
        & chmod 755 $fakeUvx
    }
    $env:PATH = $fakeBin + [IO.Path]::PathSeparator + $priorPath

    if ($ExpectedVersionPrefix) {
        Assert-True ($PSVersionTable.PSVersion.ToString().StartsWith($ExpectedVersionPrefix)) 'expected PowerShell version is running'
    }

    Write-Host '== Cross-plugin parity =='
    foreach ($name in @('set-env.ps1', 'check-prereqs.ps1')) {
        $expected = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $networkDir $name)).Hash
        Assert-Equal (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $protectDir $name)).Hash $expected "Protect $name matches Network"
        Assert-Equal (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $accessDir $name)).Hash $expected "Access $name matches Network"
    }

    Write-Host '== Secret input and preservation =='
    $workspace = New-ScenarioWorkspace $testRoot 'merge'
    $settingsDir = Join-Path $workspace '.claude'
    New-Item -ItemType Directory -Path $settingsDir | Out-Null
    $settingsPath = Join-Path $settingsDir 'settings.local.json'
    [IO.File]::WriteAllText($settingsPath, '{"permissions":{"allow":["Read"]},"env":{"EXISTING":"keep"},"custom":{"nested":true}}')
    $secret = 'short-secret-' + [char]0x03A9
    $inputJson = '{"UNIFI_NETWORK_HOST":"192.0.2.1","UNIFI_NETWORK_PASSWORD":"' + $secret + '"}'
    $result = Invoke-PluginScript $workspace $networkScript @('-InputJson') $inputJson
    Assert-Equal $result.ExitCode 0 'JSON stdin setup succeeds'
    # Helpers write UTF-8 without a BOM; Windows PowerShell defaults to ANSI.
    $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Equal $settings.env.UNIFI_NETWORK_PASSWORD $secret 'UTF-8 secret is written exactly'
    Assert-Equal $settings.env.EXISTING 'keep' 'unrelated env is preserved'
    Assert-Equal @($settings.permissions.allow).Count 1 'single-item array is preserved'
    Assert-True ($settings.custom.nested -eq $true) 'unrelated nested settings are preserved'
    Assert-True ($result.Output -notlike "*$secret*") 'secret is absent from setup output'
    Assert-True ($result.Output -notlike '*short*') 'secret fragment is absent from setup output'
    Assert-NoReplacementArtifacts $workspace 'successful merge leaves no replacement artifacts'
    $result = Invoke-PluginScript $workspace $networkScript @('UNIFI_NETWORK_HOST=192.0.2.9')
    Assert-Equal $result.ExitCode 0 'legacy non-secret KEY=VALUE succeeds'
    $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Equal $settings.env.UNIFI_NETWORK_HOST '192.0.2.9' 'legacy non-secret value is forwarded'
    $pipelineJsonPath = Join-Path $workspace 'pipeline-input.json'
    $pipelineSecret = $secret + '-pipeline-' + [char]::ConvertFromUtf32(0x1F600) + ' "quoted" \ tail'
    $pipelineJson = ConvertTo-Json -InputObject @{ UNIFI_NETWORK_PASSWORD = $pipelineSecret } -Compress
    [IO.File]::WriteAllText($pipelineJsonPath, $pipelineJson)
    $result = Invoke-DirectPipeline $workspace $networkScript $pipelineJsonPath
    Assert-Equal $result.ExitCode 0 'direct PowerShell JSON pipeline succeeds'
    $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Equal $settings.env.UNIFI_NETWORK_PASSWORD $pipelineSecret 'direct pipeline preserves UTF-8 secret'
    Assert-True ($result.Output -notlike "*$pipelineSecret*") 'direct pipeline output omits secret'

    Write-Host '== Prerequisites and missing runtime =='
    $result = Invoke-PluginScript $workspace (Join-Path $networkDir 'check-prereqs.ps1') @('-Target', 'claude')
    Assert-Equal $result.ExitCode 0 'Claude prerequisite wrapper forwards --check'
    $result = Invoke-PluginScript $workspace (Join-Path $networkDir 'check-prereqs.ps1') @('-Target', 'openclaw')
    # The isolated state contains no OpenClaw install/configuration. A missing
    # CLI or malformed config must be reported by the selected target.
    if ($result.ExitCode -eq 0) {
        $badOpenClawPath = Join-Path $workspace 'bad-openclaw.json'
        [IO.File]::WriteAllText($badOpenClawPath, '{ broken')
        $env:OPENCLAW_CONFIG_PATH = $badOpenClawPath
        $result = Invoke-PluginScript $workspace (Join-Path $networkDir 'check-prereqs.ps1') @('-Target', 'openclaw')
        $env:OPENCLAW_CONFIG_PATH = $scratchOpenClawConfigPath
    }
    Assert-True ($result.ExitCode -ne 0) 'OpenClaw prerequisite wrapper checks selected target'
    $before = Get-BytesBase64 $settingsPath
    $result = Invoke-PluginScript $workspace $networkScript @('-InputJson') '{"UNIFI_NETWORK_HOST":"192.0.2.2"}' -NoPython
    Assert-True ($result.ExitCode -ne 0) 'missing Python and uv fail closed'
    Assert-Equal (Get-BytesBase64 $settingsPath) $before 'missing Python and uv preserve exact bytes'

    Write-Host '== Dry run and delete =='
    $before = Get-BytesBase64 $settingsPath
    $result = Invoke-PluginScript $workspace $networkScript @('-InputJson', '-DryRun') '{"UNIFI_NETWORK_PASSWORD":null}'
    Assert-Equal $result.ExitCode 0 'dry run succeeds'
    Assert-Equal (Get-BytesBase64 $settingsPath) $before 'dry run preserves exact bytes'
    $result = Invoke-PluginScript $workspace $networkScript @('-InputJson') '{"UNIFI_NETWORK_PASSWORD":null}'
    Assert-Equal $result.ExitCode 0 'null patch succeeds'
    $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($null -eq $settings.env.PSObject.Properties['UNIFI_NETWORK_PASSWORD']) 'null removes the selected key'

    Write-Host '== Positional credential refusal =='
    $before = Get-BytesBase64 $settingsPath
    $result = Invoke-PluginScript $workspace $networkScript @('UNIFI_NETWORK_PASSWORD=do-not-print')
    Assert-True ($result.ExitCode -ne 0) 'positional credential is rejected'
    Assert-True ($result.Output -notlike '*do-not-print*') 'rejection output contains no credential'
    Assert-Equal (Get-BytesBase64 $settingsPath) $before 'rejected credential preserves exact bytes'

    Write-Host '== Malformed existing settings =='
    foreach ($case in @(
        [pscustomobject]@{ Name = 'malformed'; Content = '{ broken' },
        [pscustomobject]@{ Name = 'array-root'; Content = '["not-an-object"]' },
        [pscustomobject]@{ Name = 'array-env'; Content = '{"env":["not-an-object"]}' }
    )) {
        $caseWorkspace = New-ScenarioWorkspace $testRoot $case.Name
        $caseDir = Join-Path $caseWorkspace '.claude'
        New-Item -ItemType Directory -Path $caseDir | Out-Null
        $casePath = Join-Path $caseDir 'settings.local.json'
        [IO.File]::WriteAllText($casePath, $case.Content)
        $caseBefore = Get-BytesBase64 $casePath
        $result = Invoke-PluginScript $caseWorkspace $networkScript @('-InputJson') '{"UNIFI_NETWORK_HOST":"192.0.2.1"}'
        Assert-True ($result.ExitCode -ne 0) "$($case.Name) fails closed"
        Assert-Equal (Get-BytesBase64 $casePath) $caseBefore "$($case.Name) preserves exact bytes"
        Assert-NoReplacementArtifacts $caseWorkspace "$($case.Name) leaves no replacement artifacts"
    }

    if (-not $SkipFixtures) {
        Write-Host '== Transactional client fixtures =='
        $fixtures = Invoke-PortableFixtures
        if ($fixtures.ExitCode -ne 0) {
            # The fixture captures fake credential values. Report only its fixed
            # assertion label, never raw traceback lines or client output.
            $failureLine = @($fixtures.Output -split "`r?`n" | Where-Object { $_ -match '^AssertionError: [A-Za-z0-9 _./-]{1,120}$' } | Select-Object -Last 1)
            if ($failureLine.Count -gt 0) {
                Write-Host ('  Fixture failure: ' + $failureLine[0])
            } else {
                Write-Host '  Fixture process failed; inspect the isolated test run.'
            }
        } else {
            $countLine = @($fixtures.Output -split "`r?`n" | Where-Object { $_ -match '^Fixture assertions: [0-9]+ passed$' } | Select-Object -Last 1)
            if ($countLine.Count -gt 0) { Write-Host ('  ' + $countLine[0]) }
        }
        Assert-Equal $fixtures.ExitCode 0 'all three plugins and client targets pass portable fixtures'
    }
} finally {
    $env:HOME = $priorHome
    $env:USERPROFILE = $priorUserProfile
    $env:CODEX_HOME = $priorCodexHome
    $env:CLAUDE_CONFIG_DIR = $priorClaudeConfigDir
    $env:OPENCLAW_STATE_DIR = $priorOpenClawStateDir
    $env:OPENCLAW_CONFIG_PATH = $priorOpenClawConfigPath
    $env:PATH = $priorPath
    if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}

Write-Host "PowerShell $($PSVersionTable.PSVersion): $($script:Passes) passed, $($script:Failures.Count) failed"
if ($script:Failures.Count -gt 0) {
    foreach ($failure in $script:Failures) { Write-Host "  - $failure" }
    exit 1
}
exit 0
