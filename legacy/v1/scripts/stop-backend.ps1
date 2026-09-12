[CmdletBinding()]
param(
    [switch]$Force,

    [ValidateRange(1, 120)]
    [int]$TimeoutSeconds = 10
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$venvScripts = Join-Path $projectRoot 'backend\.venv\Scripts'
$allowedExecutables = @(
    (Join-Path $venvScripts 'python.exe'),
    (Join-Path $venvScripts 'pythonw.exe')
) | ForEach-Object { [System.IO.Path]::GetFullPath($_).ToLowerInvariant() }

function Get-NormalizedPath {
    param([AllowNull()][string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return ''
    }

    try {
        return [System.IO.Path]::GetFullPath($Path).ToLowerInvariant()
    }
    catch {
        return $Path.ToLowerInvariant()
    }
}

function Get-TargetBackend {
    $processes = @(Get-CimInstance -ClassName Win32_Process)

    foreach ($process in $processes) {
        $processName = ([string]$process.Name).ToLowerInvariant()
        if ($processName -notin @('python.exe', 'pythonw.exe')) {
            continue
        }

        $executablePath = Get-NormalizedPath ([string]$process.ExecutablePath)
        if ($executablePath -notin $allowedExecutables) {
            continue
        }

        $commandLine = [string]$process.CommandLine
        if ([string]::IsNullOrWhiteSpace($commandLine)) {
            continue
        }

        $isUvicorn = $commandLine -match '(?i)(^|\s)-m\s+uvicorn(?:\s|$)'
        $isApp = $commandLine -match '(?i)(^|\s)app\.main:app(?:\s|$)'
        $isProjectAppDir = $commandLine -match '(?i)(^|\s)--app-dir\s+["'']?backend["'']?(?=\s|$)'
        $isPort = $commandLine -match '(?i)(^|\s)--port\s+8787(?=\s|$)'

        if (-not ($isUvicorn -and $isApp -and $isProjectAppDir -and $isPort)) {
            continue
        }

        [PSCustomObject]@{
            ProcessId = [int]$process.ProcessId
            Name = $process.Name
            ExecutablePath = $process.ExecutablePath
            CommandLine = $commandLine
        }
    }
}

function Test-TargetRunning {
    param([int]$ProcessId)

    return @(
        Get-TargetBackend | Where-Object { $_.ProcessId -eq $ProcessId }
    ).Count -gt 0
}

function Wait-TargetExit {
    param(
        [int]$ProcessId,
        [int]$Seconds
    )

    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        if (-not (Test-TargetRunning -ProcessId $ProcessId)) {
            return $true
        }

        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    return -not (Test-TargetRunning -ProcessId $ProcessId)
}

try {
    $targets = @(Get-TargetBackend)
}
catch {
    Write-Error "Unable to read Windows process information: $($_.Exception.Message)"
    exit 1
}

if ($targets.Count -eq 0) {
    Write-Host 'No matching project Backend on port 8787 was found. No process was stopped.'
    exit 0
}

Write-Host "Found $($targets.Count) matching project Backend process(es):"
foreach ($target in $targets) {
    Write-Host "  PID $($target.ProcessId)  $($target.ExecutablePath)"
}

$remaining = @()
foreach ($target in $targets) {
    if (-not (Test-TargetRunning -ProcessId $target.ProcessId)) {
        continue
    }

    $taskKillArguments = @('/PID', [string]$target.ProcessId, '/T')
    if ($Force) {
        $taskKillArguments += '/F'
        Write-Host "Force-stopping PID $($target.ProcessId)..."
    }
    else {
        Write-Host "Requesting stop for PID $($target.ProcessId)..."
    }

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & taskkill.exe @taskKillArguments 2>&1 | ForEach-Object { Write-Host $_ }
    $taskKillExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    if ($taskKillExitCode -ne 0) {
        Write-Warning "The stop command for PID $($target.ProcessId) returned code $taskKillExitCode."
    }

    if (-not (Wait-TargetExit -ProcessId $target.ProcessId -Seconds $TimeoutSeconds)) {
        $remaining += $target
    }
}

if ($remaining.Count -eq 0) {
    Write-Host 'Backend stopped. SQLite data was not deleted.'
    exit 0
}

foreach ($target in $remaining) {
    if ($Force) {
        Write-Error "PID $($target.ProcessId) is still running after force-stop. Check permissions or handle it manually."
    }
    else {
        Write-Warning "PID $($target.ProcessId) did not exit within $TimeoutSeconds seconds. The script did not force-terminate it."
        Write-Host 'If force-stop is intended, run: .\scripts\stop-backend.ps1 -Force'
    }
}

exit 2
