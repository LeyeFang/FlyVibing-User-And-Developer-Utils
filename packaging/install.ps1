$ErrorActionPreference = "Stop"

function Show-Usage {
    @"
FlyVibing Tools installer

Usage:
  install.cmd [options]
  powershell -ExecutionPolicy Bypass -File install.ps1 [options]

Options:
  --workspace DIR   write the engine-editor skill and .vscode/mcp.json there
  --profile lite    MCP profile (lite or full; default: lite)
  --python PATH     Python 3.10+ executable to use
  --offline         use bundled wheels only; dependencies must already exist
  --no-setup        install packages without touching a workspace
  --dry-run         print the commands without installing
  --help            show this help

The script installs the bundled wheels with pip.  For a normal Python install
it uses the user site; inside a virtual environment it installs into that
environment.
"@ | Write-Host
}

$forward = New-Object System.Collections.Generic.List[string]
$pythonArg = $null
for ($i = 0; $i -lt $args.Count; $i++) {
    $arg = [string]$args[$i]
    if ($arg -eq "--help" -or $arg -eq "-h") {
        Show-Usage
        exit 0
    }
    if ($arg -eq "--python" -or $arg -eq "-Python") {
        if ($i + 1 -ge $args.Count) {
            Write-Host "ERROR: --python expects a path or command" -ForegroundColor Red
            exit 2
        }
        $i++
        $pythonArg = [string]$args[$i]
        continue
    }
    if ($arg -match '^--python=(.+)$') {
        $pythonArg = $Matches[1]
        continue
    }
    $forward.Add($arg)
}

$candidates = @()
if ($pythonArg) {
    $candidates += @{ Exe = $pythonArg; Args = @() }
} else {
    if ($env:FLYVIBING_PYTHON) {
        $candidates += @{ Exe = $env:FLYVIBING_PYTHON; Args = @() }
    }
    # Prefer stable CPython releases before the free-threaded default.
    $candidates += @(
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "py"; Args = @("-3.11") },
        @{ Exe = "py"; Args = @("-3.10") },
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "python"; Args = @() },
        @{ Exe = "python3"; Args = @() }
    )
}

function Resolve-PythonCandidate {
    param($Candidate)
    $exe = [string]$Candidate.Exe
    if ([string]::IsNullOrWhiteSpace($exe)) {
        return $null
    }
    $command = Get-Command $exe -ErrorAction SilentlyContinue
    if (-not $command) {
        return $null
    }
    $probe = @($Candidate.Args) + @(
        "-c",
        "import sys; print('%d.%d' % sys.version_info[:2]); raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
    )
    try {
        $result = & $command.Source @probe 2>$null
    } catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    $version = [string]($result | Select-Object -Last 1)
    $version = $version.Trim()
    if ($version -notmatch '^(\d+)\.(\d+)$') {
        return $null
    }
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
        return $null
    }
    return @{
        Exe = $command.Source
        Args = @($Candidate.Args)
        Version = $version
    }
}

$found = $null
foreach ($candidate in $candidates) {
    $found = Resolve-PythonCandidate $candidate
    if ($found) {
        break
    }
}
if (-not $found) {
    Write-Host "ERROR: Python 3.10+ was not found." -ForegroundColor Red
    Write-Host "Install Python from https://www.python.org/downloads/ and rerun this script."
    Write-Host "If Python is installed in a non-standard place, pass --python <path>."
    exit 1
}

$installer = Join-Path $PSScriptRoot "install.py"
if (-not (Test-Path -LiteralPath $installer)) {
    Write-Host "ERROR: install.py is missing next to this script." -ForegroundColor Red
    exit 1
}

Write-Host "Using Python $($found.Version): $($found.Exe)"
$invoke = @($found.Args) + @($installer) + @($forward.ToArray())
& $found.Exe @invoke
exit $LASTEXITCODE
