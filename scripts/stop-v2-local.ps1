[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pidRoot = Join-Path $repositoryRoot "runtime\pids"
$hadMismatch = $false

function Stop-RecordedProcess {
    param([string]$Name)
    $recordPath = Join-Path $pidRoot "$Name.json"
    if (-not (Test-Path -LiteralPath $recordPath)) {
        Write-Host "${Name}: no project PID record; nothing stopped."
        return
    }

    try {
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        if ([string]$record.repository_root -ne $repositoryRoot) {
            throw "repository root mismatch"
        }
        $process = Get-Process -Id ([int]$record.pid) -ErrorAction Stop
        $actualStart = $process.StartTime.ToUniversalTime()
        $recordedStart = [datetime]::Parse([string]$record.process_started_at).ToUniversalTime()
        if ([math]::Abs(($actualStart - $recordedStart).TotalSeconds) -gt 2) {
            throw "process start time mismatch"
        }
        if ($process.Path -and ([string]$process.Path -ne [string]$record.executable)) {
            throw "executable mismatch"
        }
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)" -ErrorAction Stop
        foreach ($marker in @($record.command_markers)) {
            if ([string]$cim.CommandLine -notlike "*$marker*") {
                throw "command line marker mismatch: $marker"
            }
        }

        Stop-Process -Id $process.Id -ErrorAction Stop
        Wait-Process -Id $process.Id -Timeout 10 -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $recordPath -Force
        Write-Host "${Name}: stopped verified project PID $($process.Id)."
    }
    catch [Microsoft.PowerShell.Commands.ProcessCommandException] {
        Remove-Item -LiteralPath $recordPath -Force
        Write-Host "${Name}: recorded process is no longer running; stale PID record removed."
    }
    catch {
        $script:hadMismatch = $true
        Write-Warning "$Name was not stopped because ownership verification failed: $($_.Exception.Message)"
    }
}

if (-not (Test-Path -LiteralPath $pidRoot)) {
    Write-Host "No V2 PID directory exists; nothing stopped."
    exit 0
}

Stop-RecordedProcess -Name "web"
Stop-RecordedProcess -Name "backend"

if ($hadMismatch) {
    Write-Error "At least one PID record did not safely match its live process. No unverified process was stopped."
    exit 1
}

Write-Host "Codex Reset Radar V2 local processes are stopped."
