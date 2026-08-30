[CmdletBinding()]
param(
    [switch]$DryRun
)

Write-Warning "sync-github-mirror.ps1 is deprecated; runtime data now belongs on the data branch."
$arguments = @("-File", (Join-Path $PSScriptRoot "sync-github-data.ps1"))
if ($DryRun) {
    $arguments += "-DryRun"
}
& powershell.exe -NoProfile -ExecutionPolicy Bypass @arguments
exit $LASTEXITCODE
