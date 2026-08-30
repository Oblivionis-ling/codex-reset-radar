[CmdletBinding()]
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Backend virtual environment not found. Run start-radar.bat once first."
}

Push-Location $repoRoot
try {
    & $python (Join-Path $repoRoot "scripts\public_export.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Public data export failed with exit code $LASTEXITCODE."
    }

    if ($DryRun) {
        git diff -- public-data
        exit 0
    }

    git add -- public-data
    $staged = @(git diff --cached --name-only -- public-data)
    if ($staged.Count -eq 0) {
        Write-Host "Public mirror is unchanged; nothing to push."
        exit 0
    }

    git commit -m "chore(mirror): update sanitized radar data"
    git push origin main
} finally {
    Pop-Location
}
