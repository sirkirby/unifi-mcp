# Apply a plugin environment patch with the shared transactional setup helper.
# Secret values must be supplied as JSON on stdin: ... | set-env.ps1 -InputJson
[CmdletBinding(PositionalBinding = $false)]
param(
    [ValidateSet('claude', 'codex', 'openclaw')]
    [string]$Target = 'claude',
    [switch]$InputJson,
    [switch]$DryRun,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$KeyValuePairs,
    [Parameter(ValueFromPipeline = $true)]
    [string]$PipelineInput
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

function Invoke-SetupHelper {
    param([string]$Json)
    $helper = Join-Path $PSScriptRoot 'setup_config.py'
    if (-not (Test-Path -LiteralPath $helper)) {
        throw 'The plugin setup helper is missing.'
    }
    $runtime = Get-SetupRuntime
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $runtime.FileName
    $start.Arguments = $runtime.Prefix + '"' + $helper + '" --target ' + $Target
    if ($DryRun) { $start.Arguments += ' --dry-run' }
    Set-BatchLauncher $start
    $start.UseShellExecute = $false
    $start.RedirectStandardInput = $true
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
        $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($Json)
        $process.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
        $process.StandardInput.BaseStream.Close()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            # Child diagnostics can contain controller values or submitted secrets.
            throw 'Plugin setup failed; configuration was not applied.'
        }
        if ($stdoutTask.Result) { [Console]::Out.Write($stdoutTask.Result) }
        [void]$stderrTask.Result
    } finally {
        $process.Dispose()
    }
}

try {
    if ($InputJson) {
        if ($KeyValuePairs -and $KeyValuePairs.Count -gt 0) {
            throw 'Use either JSON stdin or KEY=VALUE arguments.'
        }
        if ($MyInvocation.ExpectingInput) {
            # Direct PowerShell pipelines send objects through $input, while
            # native `powershell -File` sends bytes through Console.In.
            $json = @($input) -join [Environment]::NewLine
        } else {
            [Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
            $json = [Console]::In.ReadToEnd()
        }
        if ([string]::IsNullOrWhiteSpace($json)) {
            throw 'JSON stdin is required with -InputJson.'
        }
    } else {
        if (-not $KeyValuePairs -or $KeyValuePairs.Count -eq 0) {
            throw 'Provide non-secret KEY=VALUE arguments or use -InputJson for credentials.'
        }
        $patch = @{}
        foreach ($pair in $KeyValuePairs) {
            $separator = $pair.IndexOf('=')
            if ($separator -lt 1) {
                throw 'Expected KEY=VALUE format.'
            }
            $key = $pair.Substring(0, $separator)
            if ($key -cnotmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
                throw 'An environment key is invalid.'
            }
            if ($key -match '(^|_)(PASSWORD|PASS|API_KEY|TOKEN|SECRET|PRIVATE_KEY|CREDENTIAL|AUTH)(_|$)' -and
                $key -notmatch '(^|_)(PASSWORD|API_KEY)_(FILE|COMMAND)$') {
                throw 'Credentials must be supplied through -InputJson on stdin.'
            }
            if ($patch.ContainsKey($key)) {
                throw 'Duplicate environment keys are unsupported.'
            }
            $patch[$key] = $pair.Substring($separator + 1)
        }
        $json = ConvertTo-Json -InputObject $patch -Depth 5 -Compress
    }
    Invoke-SetupHelper -Json $json
} catch {
    # Do not include the exception: native runtimes may render stdin or argv.
    [Console]::Error.WriteLine('Plugin setup failed. Check uv/uvx (which supply Python), the target CLI, input format, and existing configuration.')
    exit 1
}
exit 0
