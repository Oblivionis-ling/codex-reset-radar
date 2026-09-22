[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$RemainingArgs)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common-v2.ps1")
$python = Resolve-CrrPython -RepositoryRoot $script:CrrRepositoryRoot
$entry = Join-Path $script:CrrRepositoryRoot "scripts\test_notifications.py"

& $python $entry @RemainingArgs
exit $LASTEXITCODE
