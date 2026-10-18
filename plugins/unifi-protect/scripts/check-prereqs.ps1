# Validate client prerequisites and existing configuration without writing.
param(
    [ValidateSet('claude', 'codex', 'openclaw')]
    [string]$Target = 'claude',
    [string]$PluginName = 'unifi plugin'
)

$ErrorActionPreference = 'Stop'

function Get-SetupRuntime {
    foreach ($name in @('python3', 'python')) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $command) { continue }
        # Store aliases can open a dialog instead of running Python. Never launch them.
        if ($command.Source -match '[\\/]WindowsApps[\\/]python[^\\/]*\.exe$') { continue }
        $probeStart = New-Object System.Diagnostics.ProcessStartInfo
        $probeStart.FileName = $command.Source
        $probeStart.Arguments = '-c "import sys; print(''unifi-setup-python-ok'') if sys.version_info >= (3, 11) else sys.exit(1)"'
        Set-BatchLauncher $probeStart
        $probeStart.UseShellExecute = $false
        $probeStart.RedirectStandardInput = $true
        $probeStart.RedirectStandardOutput = $true
        $probeStart.RedirectStandardError = $true
        $probe = New-Object System.Diagnostics.Process
        $probe.StartInfo = $probeStart
        try {
            [void]$probe.Start()
            $probe.StandardInput.Close()
            $output = $probe.StandardOutput.ReadToEndAsync()
            $errors = $probe.StandardError.ReadToEndAsync()
            if (-not $probe.WaitForExit(5000)) { $probe.Kill(); $probe.WaitForExit(); continue }
            if ($probe.ExitCode -eq 0 -and $output.Result.Trim() -ceq 'unifi-setup-python-ok') {
                return [pscustomobject]@{ FileName = $command.Source; Prefix = '' }
            }
            [void]$errors.Result
        } catch {
            # A missing runtime or nonfunctional alias is not a working interpreter.
        } finally {
            $probe.Dispose()
        }
    }
    $uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $uv) { throw 'Install uv to supply the setup runtime.' }
    return [pscustomobject]@{ FileName = $uv.Source; Prefix = 'run --no-project --python ">=3.11" python ' }
}

function Set-BatchLauncher {
    param($StartInfo)
    # npm-style test/client launchers on Windows require cmd; all arguments are
    # fixed options and paths. Submitted values still travel only on stdin.
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT -and $StartInfo.FileName -match '\.(cmd|bat)$') {
        $StartInfo.Arguments = '/d /s /c ""' + $StartInfo.FileName + '" ' + $StartInfo.Arguments + '"'
        $StartInfo.FileName = $env:ComSpec
    }
}

try {
    $helper = Join-Path $PSScriptRoot 'setup_config.py'
    if (-not (Test-Path -LiteralPath $helper)) {
        throw 'The plugin setup helper is missing.'
    }
    $runtime = Get-SetupRuntime

    # Fixed arguments only. Redirect child diagnostics because CLI errors may
    # include existing credentials read during validation.
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $runtime.FileName
    $start.Arguments = $runtime.Prefix + '"' + $helper + '" --target ' + $Target + ' --check'
    Set-BatchLauncher $start
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
    [Console]::Error.WriteLine('Prerequisite check failed for ' + $Target + '. Check uv/uvx (which supply Python), the target CLI, and existing configuration.')
    exit 1
}
exit 0
