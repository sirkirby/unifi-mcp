# Validate client prerequisites and existing configuration without writing.
param(
    [ValidateSet('claude', 'codex', 'openclaw')]
    [string]$Target = 'claude',
    [string]$PluginName = 'unifi plugin'
)

$ErrorActionPreference = 'Stop'
try {
    $helper = Join-Path $PSScriptRoot 'setup_config.py'
    if (-not (Test-Path -LiteralPath $helper)) {
        throw 'The plugin setup helper is missing.'
    }
    $python = $null
    foreach ($name in @('python3', 'python')) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $command) {
            $python = $command.Source
            break
        }
    }
    if ($null -eq $python) { throw 'Python 3 is required for plugin setup.' }

    # Fixed arguments only. Redirect child diagnostics because CLI errors may
    # include existing credentials read during validation.
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $python
    $start.Arguments = '"' + $helper + '" --target ' + $Target + ' --check'
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
        if ($process.ExitCode -ne 0) { throw 'Prerequisite check failed.' }
        [Console]::Out.Write($stdoutTask.Result)
        [void]$stderrTask.Result
    } finally {
        $process.Dispose()
    }
} catch {
    [Console]::Error.WriteLine('Prerequisite check failed for ' + $Target + '. Check Python 3, uvx, the target CLI, and existing configuration.')
    exit 1
}
exit 0
