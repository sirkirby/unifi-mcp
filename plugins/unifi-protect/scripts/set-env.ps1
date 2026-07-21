# Merge environment variables into .claude/settings.json
# Usage: set-env.ps1 KEY1=VALUE1 KEY2=VALUE2 ...
#
# Creates .claude/settings.json if it doesn't exist.
# Merges into existing "env" object without overwriting other keys.

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$KeyValuePairs
)

function ConvertTo-MutableMap {
    param(
        [Parameter(Mandatory = $true)]
        [object]$InputObject,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if ($InputObject -is [System.Collections.IDictionary]) {
        $result = @{}
        foreach ($key in $InputObject.Keys) {
            $result[$key] = $InputObject[$key]
        }
        return $result
    }

    if ($InputObject.GetType().FullName -eq 'System.Management.Automation.PSCustomObject') {
        $result = @{}
        foreach ($property in $InputObject.PSObject.Properties) {
            $result[$property.Name] = $property.Value
        }
        return $result
    }

    throw "$Description must be a JSON object."
}

if (-not $KeyValuePairs -or $KeyValuePairs.Count -eq 0) {
    Write-Error "Usage: set-env.ps1 KEY1=VALUE1 KEY2=VALUE2 ..."
    exit 1
}

# Parse key=value pairs
$newVars = @{}
foreach ($pair in $KeyValuePairs) {
    $eqIndex = $pair.IndexOf('=')
    if ($eqIndex -lt 1) {
        Write-Error "Invalid argument '$pair'. Expected KEY=VALUE format."
        exit 1
    }
    $key = $pair.Substring(0, $eqIndex)
    $value = $pair.Substring($eqIndex + 1)
    $newVars[$key] = $value
}

$settingsFile = ".claude/settings.local.json"

# Ensure .claude directory exists
$dir = Split-Path $settingsFile -Parent
if (-not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

# Read and validate existing settings or start fresh.
if (Test-Path -LiteralPath $settingsFile) {
    try {
        $parsedSettings = Get-Content -LiteralPath $settingsFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $parsedSettings) {
            throw 'The settings document must be a JSON object.'
        }
        $settings = ConvertTo-MutableMap -InputObject $parsedSettings -Description 'The settings document'

        if ($settings.ContainsKey('env')) {
            if ($null -eq $settings['env']) {
                throw 'The env setting must be a JSON object.'
            }
            $settings['env'] = ConvertTo-MutableMap -InputObject $settings['env'] -Description 'The env setting'
        } else {
            $settings['env'] = @{}
        }
    } catch {
        Write-Error "Failed to read or parse $settingsFile. Original file was not modified. $($_.Exception.Message)"
        exit 1
    }
} else {
    $settings = @{ env = @{} }
}

# Merge new vars
foreach ($key in $newVars.Keys) {
    $settings['env'][$key] = $newVars[$key]
}

# Generate and structurally validate the complete replacement beside the
# destination. The adjacent paths guarantee same-volume file operations.
$tempFile = "$settingsFile.tmp.$PID.$([Guid]::NewGuid().ToString('N'))"
$backupFile = "$settingsFile.backup.$PID.$([Guid]::NewGuid().ToString('N'))"
try {
    $json = $settings | ConvertTo-Json -Depth 100 -WarningAction Stop -ErrorAction Stop
    Set-Content -LiteralPath $tempFile -Value $json -Encoding UTF8 -ErrorAction Stop
    Get-Content -LiteralPath $tempFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop | Out-Null

    $tempFullPath = [IO.Path]::GetFullPath($tempFile)
    $settingsFullPath = [IO.Path]::GetFullPath($settingsFile)
    $backupFullPath = [IO.Path]::GetFullPath($backupFile)
    if ([IO.File]::Exists($settingsFullPath)) {
        [IO.File]::Replace($tempFullPath, $settingsFullPath, $backupFullPath)
        [IO.File]::Delete($backupFullPath)
    } else {
        [IO.File]::Move($tempFullPath, $settingsFullPath)
    }
} catch {
    $saveError = $_.Exception.Message
    Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue

    $recoveryMessage = 'Existing settings remain at the original path.'
    if ([IO.File]::Exists([IO.Path]::GetFullPath($backupFile))) {
        try {
            [IO.File]::Copy([IO.Path]::GetFullPath($backupFile), [IO.Path]::GetFullPath($settingsFile), $true)
            [IO.File]::Delete([IO.Path]::GetFullPath($backupFile))
            $recoveryMessage = 'Existing settings were restored from the recovery backup.'
        } catch {
            $recoveryMessage = "Existing settings recovery backup retained at $backupFile."
        }
    }

    Write-Error "Failed to save $settingsFile. $recoveryMessage $saveError"
    exit 1
}

# Report what was set (mask sensitive values)
foreach ($key in $newVars.Keys) {
    $value = $newVars[$key]
    if ($value.Length -gt 4 -and -not ($key -match '_(HOST|PORT|SITE)$') -and $value -ne 'true' -and $value -ne 'false') {
        $display = $value.Substring(0, 2) + '***' + $value.Substring($value.Length - 2)
    } else {
        $display = $value
    }
    Write-Host "  $key = $display"
}

Write-Host ""
Write-Host "Saved to $settingsFile"
