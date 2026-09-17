[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendRoot = Join-Path $repositoryRoot "apps\backend"
$webRoot = Join-Path $repositoryRoot "apps\web"
$runtimeRoot = Join-Path $repositoryRoot "runtime"
$pidRoot = Join-Path $runtimeRoot "pids"
$launcherLogRoot = Join-Path $runtimeRoot "launcher"

New-Item -ItemType Directory -Force -Path $pidRoot, $launcherLogRoot | Out-Null

function Get-RecordedProcess {
    param([string]$Name)
    $recordPath = Join-Path $pidRoot "$Name.json"
    if (-not (Test-Path -LiteralPath $recordPath)) {
        return $null
    }
    try {
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        $process = Get-Process -Id ([int]$record.pid) -ErrorAction Stop
        $actualStart = $process.StartTime.ToUniversalTime()
        $recordedStart = [datetime]::Parse([string]$record.process_started_at).ToUniversalTime()
        if ([math]::Abs(($actualStart - $recordedStart).TotalSeconds) -gt 2) {
            return $null
        }
        if ($process.Path -and ([string]$process.Path -ne [string]$record.executable)) {
            return $null
        }
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)" -ErrorAction Stop
        foreach ($marker in @($record.command_markers)) {
            if ([string]$cim.CommandLine -notlike "*$marker*") {
                return $null
            }
        }
        return $process
    }
    catch {
        return $null
    }
}

function Assert-PortAvailable {
    param([int]$Port, [System.Diagnostics.Process]$AllowedProcess)
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        if ($null -eq $AllowedProcess -or $listener.OwningProcess -ne $AllowedProcess.Id) {
            throw "Port $Port is already owned by PID $($listener.OwningProcess). Stop that process explicitly; this launcher will not replace it."
        }
    }
}

function Save-ProcessRecord {
    param(
        [string]$Name,
        [System.Diagnostics.Process]$Process,
        [string[]]$CommandMarkers
    )
    $Process.Refresh()
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($Process.Id)" -ErrorAction SilentlyContinue
    $record = [ordered]@{
        schema_version = 1
        name = $Name
        pid = $Process.Id
        process_started_at = $Process.StartTime.ToUniversalTime().ToString("o")
        recorded_at = [datetime]::UtcNow.ToString("o")
        executable = $Process.Path
        command_line = if ($cim) { [string]$cim.CommandLine } else { "" }
        command_markers = $CommandMarkers
        repository_root = $repositoryRoot
    }
    $record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $pidRoot "$Name.json") -Encoding utf8
}

function Wait-Endpoint {
    param([string]$Url, [int]$TimeoutSeconds = 30)
    $deadline = [datetime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    } while ([datetime]::UtcNow -lt $deadline)
    throw "Timed out waiting for $Url"
}

$pythonCandidates = @(
    (Join-Path $backendRoot ".venv\Scripts\python.exe"),
    (Join-Path $repositoryRoot "backend\.venv\Scripts\python.exe")
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
    throw "No project Python environment found. Follow docs\v2\local-development.md to create apps\backend\.venv."
}
& $python -c "import fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "The selected Python environment is missing V2 Backend dependencies: $python"
}

$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
    throw "node.exe was not found. Install Node.js 20 or later."
}
$node = $nodeCommand.Source
$viteEntry = Join-Path $webRoot "node_modules\vite\bin\vite.js"
if (-not (Test-Path -LiteralPath $viteEntry)) {
    throw "Web dependencies are not installed. Run 'npm ci' inside apps\web first."
}

$backendProcess = Get-RecordedProcess -Name "backend"
$webProcess = Get-RecordedProcess -Name "web"
Assert-PortAvailable -Port 8787 -AllowedProcess $backendProcess
Assert-PortAvailable -Port 5173 -AllowedProcess $webProcess

try {
    if (-not $backendProcess) {
        $backendStdout = Join-Path $launcherLogRoot "backend.stdout.log"
        $backendStderr = Join-Path $launcherLogRoot "backend.stderr.log"
        $backendLauncher = Start-Process -FilePath $python -ArgumentList @(
            "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8787"
        ) -WorkingDirectory $backendRoot -WindowStyle Hidden -RedirectStandardOutput $backendStdout -RedirectStandardError $backendStderr -PassThru
        Wait-Endpoint -Url "http://127.0.0.1:8787/api/v2/health"
        $backendListener = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction Stop | Select-Object -First 1
        $backendProcess = Get-Process -Id $backendListener.OwningProcess -ErrorAction Stop
        Save-ProcessRecord -Name "backend" -Process $backendProcess -CommandMarkers @("app.main:app", "8787")
    }
    else {
        Wait-Endpoint -Url "http://127.0.0.1:8787/api/v2/health"
    }

    if (-not $webProcess) {
        $webStdout = Join-Path $launcherLogRoot "web.stdout.log"
        $webStderr = Join-Path $launcherLogRoot "web.stderr.log"
        $webProcess = Start-Process -FilePath $node -ArgumentList @(
            $viteEntry, "--host", "127.0.0.1", "--port", "5173", "--strictPort"
        ) -WorkingDirectory $webRoot -WindowStyle Hidden -RedirectStandardOutput $webStdout -RedirectStandardError $webStderr -PassThru
        Save-ProcessRecord -Name "web" -Process $webProcess -CommandMarkers @("vite.js", "5173")
    }
    Wait-Endpoint -Url "http://127.0.0.1:5173/"
}
catch {
    Write-Error $_
    Write-Host "Use stop-v2-local.bat to stop any process that was successfully recorded."
    exit 1
}

Write-Host "Codex Reset Radar V2 Local Intelligence Alpha 2 is running."
Write-Host "Web:            http://127.0.0.1:5173"
Write-Host "Backend API:    http://127.0.0.1:8787/api/v2"
Write-Host "Backend health: http://127.0.0.1:8787/api/v2/health"
Write-Host "Backend PID:    $($backendProcess.Id)"
Write-Host "Web PID:        $($webProcess.Id)"
Write-Host "Stop with:      stop-v2-local.bat"
