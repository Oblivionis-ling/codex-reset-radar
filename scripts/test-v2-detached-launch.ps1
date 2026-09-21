# Windows integration regression: uses harmless sleep processes, no API/model/database.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common-v2.ps1')
$root = $script:CrrRepositoryRoot
$marker = 'CRR-detach-test-' + [guid]::NewGuid().ToString('N')
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$common = (Join-Path $PSScriptRoot 'common-v2.ps1').Replace("'", "''")
$probeCommand = '"{0}" -NoProfile -NonInteractive -WindowStyle Hidden -Command "Start-Sleep -Seconds 90; # {1}"' -f $powershell, $marker
$callerCode = ". '$common'; Start-CrrDetachedProcess -CommandLine '$($probeCommand.Replace("'", "''"))' | Out-Null; Start-Sleep -Seconds 90"
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($callerCode))
$caller = $null
$probe = $null
try {
    $caller = Start-Process -FilePath $powershell -ArgumentList @('-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-EncodedCommand', $encoded) -WindowStyle Hidden -PassThru
    $deadline = [datetime]::UtcNow.AddSeconds(15)
    do {
        $probe = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -eq $probeCommand } | Select-Object -First 1
        if ($probe) { break }
        Start-Sleep -Milliseconds 250
    } while ([datetime]::UtcNow -lt $deadline)
    if (-not $probe) { throw 'Detached probe was not created.' }
    $broker = Get-CimInstance Win32_Process -Filter "ProcessId=$($probe.ParentProcessId)"
    if ($broker.Name -ne 'WmiPrvSE.exe') { throw "Unexpected parent: $($broker.Name)" }
    # Terminate only this test's caller tree, simulating host cleanup.
    & taskkill.exe /PID $caller.Id /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to terminate test caller tree.' }
    Start-Sleep -Seconds 1
    $survivor = Get-CimInstance Win32_Process -Filter "ProcessId=$($probe.ProcessId)"
    if (-not $survivor -or $survivor.CommandLine -ne $probeCommand) { throw 'Detached probe died with caller tree.' }
    Write-Output 'PASS: WMI-owned process survives caller process-tree termination.'
}
finally {
    if ($probe) {
        $remaining = Get-CimInstance Win32_Process -Filter "ProcessId=$($probe.ProcessId)"
        if ($remaining -and $remaining.CommandLine -eq $probeCommand) { Stop-Process -Id $probe.ProcessId -ErrorAction SilentlyContinue }
    }
    if ($caller -and -not $caller.HasExited) { $caller.Kill() }
}
