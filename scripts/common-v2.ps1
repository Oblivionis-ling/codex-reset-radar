$script:CrrRepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Start-CrrDetachedProcess {
    param([string]$CommandLine, [string]$WorkingDirectory = $script:CrrRepositoryRoot)
    $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $CommandLine
        CurrentDirectory = $WorkingDirectory
        ProcessStartupInformation = $startup
    }
    if ($created.ReturnValue -ne 0) {
        throw "Windows detached launch failed (WMI code $($created.ReturnValue)). No child-process fallback was started."
    }
    return [int]$created.ProcessId
}

function Resolve-CrrPython {
    param([string]$RepositoryRoot = $script:CrrRepositoryRoot)
    $python = Join-Path $RepositoryRoot "apps\backend\.venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        throw "No project Python environment found. Follow docs\v2\local-development.md to create apps\backend\.venv."
    }
    return $python
}
