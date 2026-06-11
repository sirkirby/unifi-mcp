param(
    [ValidateSet("claude", "codex", "openclaw")]
    [string]$Target = "claude",

    [string]$PluginName = "unifi plugin"
)

$ErrorActionPreference = "Stop"
$errors = 0
$warnings = 0

function Test-CommandExists {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Write-Ok { param([string]$Message) Write-Host "  [OK]   $Message" }
function Write-Warn { param([string]$Message) Write-Host "  [WARN] $Message"; $script:warnings++ }
function Write-Fail { param([string]$Message) Write-Host "  [FAIL] $Message"; $script:errors++ }

Write-Host "Checking prerequisites for $PluginName ($Target)..."
Write-Host ""

if (Test-CommandExists "uvx") {
    $uvxVersion = (& uvx --version 2>&1 | Select-Object -First 1)
    Write-Ok "uvx found: $uvxVersion"
} else {
    Write-Fail "uvx not found on PATH"
    Write-Host ""
    Write-Host "         Install uv from https://docs.astral.sh/uv/getting-started/installation/"
    Write-Host "         Then restart PowerShell or Codex so PATH refreshes."
}

if ($Target -eq "codex") {
    if (Test-CommandExists "codex") {
        $codexVersion = (& codex --version 2>&1 | Select-Object -First 1)
        Write-Ok "codex found: $codexVersion"
        try {
            & codex mcp list *> $null
            Write-Ok "codex mcp list succeeded"
        } catch {
            Write-Warn "codex is installed, but 'codex mcp list' failed. Setup may still work after Codex authentication is refreshed."
        }
    } else {
        Write-Fail "codex CLI not found on PATH"
        Write-Host "         Codex setup registers the MCP server with 'codex mcp add'."
    }
} elseif ($Target -eq "openclaw") {
    if (Test-CommandExists "openclaw") {
        $openclawVersion = (& openclaw --version 2>&1 | Select-Object -First 1)
        Write-Ok "openclaw found: $openclawVersion"
    } else {
        Write-Fail "openclaw CLI not found on PATH"
    }
} else {
    $settingsFile = ".claude/settings.local.json"
    if (Test-Path $settingsFile) {
        try {
            Get-Content $settingsFile -Raw | ConvertFrom-Json | Out-Null
            Write-Ok "$settingsFile is valid JSON"
        } catch {
            Write-Fail "$settingsFile exists but is not valid JSON"
            Write-Host "         Fix or move it aside before continuing; setup will not clobber a malformed settings file."
        }
    } else {
        Write-Ok "$settingsFile does not exist yet (will be created)"
    }
}

if ($Target -eq "codex") {
    Write-Host "  [INFO] After setup, restart Codex so MCP server changes are loaded."
} elseif ($Target -eq "openclaw") {
    Write-Host "  [INFO] After setup, restart the OpenClaw Gateway so MCP server changes are loaded."
} else {
    Write-Host "  [INFO] Reminder: 'installed' is not the same as 'enabled'."
    Write-Host "         After setup, run /plugin and confirm the plugin shows enabled."
}

Write-Host ""
if ($errors -gt 0) {
    Write-Host "Prerequisite check FAILED with $errors error(s). Resolve the issues above and re-run."
    exit 1
}

if ($warnings -gt 0) {
    Write-Host "Prerequisite check passed with $warnings warning(s)."
} else {
    Write-Host "Prerequisite check passed."
}
