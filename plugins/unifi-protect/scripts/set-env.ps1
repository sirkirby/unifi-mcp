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

function Get-PythonPath {
    foreach ($name in @('python3', 'python')) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $command) { return $command.Source }
    }
    throw 'Python 3 is required for plugin setup.'
}

function Invoke-SetupHelper {
    param([string]$Json)
    $helper = Join-Path $PSScriptRoot 'setup_config.py'
    if (-not (Test-Path -LiteralPath $helper)) {
        throw 'The plugin setup helper is missing.'
    }
    $python = Get-PythonPath
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $python
    $start.Arguments = '"' + $helper + '" --target ' + $Target
    if ($DryRun) { $start.Arguments += ' --dry-run' }
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
    [Console]::Error.WriteLine('Plugin setup failed. Check Python 3.11+, uvx, the target CLI, input format, and existing configuration.')
    exit 1
}
exit 0
