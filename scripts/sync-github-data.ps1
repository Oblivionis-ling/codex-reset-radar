[CmdletBinding()]
param(
    [switch]$DryRun,
    [string]$Branch = "data",
    [string]$Remote = "origin",
    [string]$RemoteUrl,
    [ValidateRange(1, 4)]
    [Alias("MaxPushAttempts")]
    [int]$MaxAttempts = 4,
    [ValidateSet("scheduled", "event", "manual")]
    [string]$Trigger = "manual",
    [string]$CycleStartedAt = "",
    [string]$PreviousSuccessAt = "",
    [string]$TraceId = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
$syncRoot = Join-Path $repoRoot "_tmp\public-data-sync-$PID"
$exportDir = Join-Path $syncRoot "export"
$dataWorktree = Join-Path $syncRoot "data-worktree"
$requiredFiles = @("index.json", "tweets.json", "radar.json", "health.json", "resets.json", "meta.json")
$retryDelaysSeconds = @(0, 30, 60, 120)
$cycleStarted = if ($CycleStartedAt) { [datetimeoffset]::Parse($CycleStartedAt).ToUniversalTime() } else { [datetimeoffset]::UtcNow }
$previousSuccess = if ($PreviousSuccessAt) { [datetimeoffset]::Parse($PreviousSuccessAt).ToUniversalTime() } else { $null }
$traceId = if ($TraceId) { $TraceId } else { "mirror-$([guid]::NewGuid().ToString('N').Substring(0, 12))" }
$snapshotId = "-"
$terminalFailureWritten = $false
$exitCode = 0

function Format-CadenceTimestamp {
    param([datetimeoffset]$Value)
    return $Value.ToUniversalTime().ToString("o")
}

function Format-PreviousSuccess {
    if ($previousSuccess) {
        return Format-CadenceTimestamp $previousSuccess
    }
    return "-"
}

function Format-SecondsSincePreviousSuccess {
    param([datetimeoffset]$Value)
    if ($previousSuccess) {
        return [math]::Round(($Value - $previousSuccess).TotalSeconds, 3).ToString("0.###")
    }
    return "-"
}

function Redact-SensitiveText {
    param([AllowNull()][string]$Value)
    $redacted = ([string]$Value).Trim()
    foreach ($name in @("GITHUB_TOKEN", "DEEPSEEK_API_KEY", "WXPUSHER_APP_TOKEN", "WXPUSHER_UID")) {
        $environmentValue = Get-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        $secret = if ($environmentValue) { [string]$environmentValue.Value } else { "" }
        if ($secret) {
            $redacted = $redacted.Replace($secret, "[redacted]")
        }
    }
    $redacted = [regex]::Replace($redacted, "https?://[^/\s:@]+:[^@\s]+@", "https://[redacted]@")
    $redacted = ([regex]::Replace($redacted, "\s+", " ")).Trim()
    if ($redacted.Length -gt 500) {
        return $redacted.Substring(0, 500)
    }
    return $redacted
}

function Get-MirrorErrorType {
    param([AllowNull()][string]$Value)
    $text = (Redact-SensitiveText $Value).ToLowerInvariant()
    if ($text -match "auth|authentication|permission denied|could not read username|401|403|repository not found") {
        return "auth_failed"
    }
    if ($text -match "non-fast-forward|rejected|conflict|would be overwritten") {
        return "git_conflict"
    }
    if ($text -match "dns|could not resolve host|name resolution|temporary failure in name resolution") {
        return "network_dns"
    }
    if ($text -match "timed out|timeout|time-out|operation timed out") {
        return "network_timeout"
    }
    if ($text -match "connection reset|recv failure|connection was reset|reset by peer") {
        return "network_reset"
    }
    if ($text -match "could not connect|failed to connect|connection failure|network is unreachable|network down") {
        return "network_connect"
    }
    if ($text -match "\bclone\b") {
        return "clone_failed"
    }
    if ($text -match "\bfetch\b") {
        return "fetch_failed"
    }
    if ($text -match "\bpush\b") {
        return "push_failed"
    }
    return "unknown"
}

function Write-MirrorEvent {
    param(
        [Parameter(Mandatory = $true)][string]$Event,
        [Parameter(Mandatory = $true)][hashtable]$Fields
    )

    $fieldOrder = @(
        "trace_id", "snapshot_id",
        "cycle_started_at", "snapshot_generated_at", "push_started_at", "sync_finished_at", "published_at",
        "mirror_synced_at", "duration_ms", "attempt", "next_attempt", "previous_success_at",
        "seconds_since_previous_success", "retry_delay_seconds", "trigger", "result", "error_type", "terminal",
        "push_attempt"
    )
    if (-not $Fields.ContainsKey("trace_id")) { $Fields["trace_id"] = $traceId }
    if (-not $Fields.ContainsKey("snapshot_id")) { $Fields["snapshot_id"] = $snapshotId }
    $parts = @()
    foreach ($name in $fieldOrder) {
        if ($Fields.ContainsKey($name)) {
            $parts += "$name=$($Fields[$name])"
        }
    }
    if ($Fields.ContainsKey("reason")) {
        $parts += "reason=$(Redact-SensitiveText ([string]$Fields["reason"]))"
    }
    Write-Output "$Event $($parts -join ' ')"
}

function Invoke-GitChecked {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$WorkingDirectory
    )

    # Git writes normal push/status progress to stderr. Keep native stderr in
    # the captured output without letting PowerShell's Stop preference turn a
    # successful command into a terminating error.
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = @()
    if ($WorkingDirectory) {
        Push-Location -LiteralPath $WorkingDirectory
        try {
            $output = @(& git @Arguments 2>&1)
            $exitCode = $LASTEXITCODE
        } finally {
            Pop-Location
        }
    } else {
        $output = @(& git @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    $ErrorActionPreference = $previousErrorActionPreference
    if ($exitCode -ne 0) {
        throw "git $($Arguments -join ' ') failed: $(Redact-SensitiveText ($output -join ' '))"
    }
    return $output
}

function Remove-GeneratedSyncDirectory {
    if (-not (Test-Path -LiteralPath $syncRoot)) {
        return
    }
    $resolvedRoot = (Resolve-Path -LiteralPath $repoRoot).Path.TrimEnd('\')
    $resolvedSync = (Resolve-Path -LiteralPath $syncRoot).Path
    if (-not $resolvedSync.StartsWith("$resolvedRoot\", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a sync directory outside the repository _tmp folder: $resolvedSync"
    }
    Remove-Item -LiteralPath $resolvedSync -Recurse -Force
}

function Clear-DataWorktreeFiles {
    param([Parameter(Mandatory = $true)][string]$Worktree)

    $gitDirectory = Join-Path $Worktree ".git"
    Get-ChildItem -LiteralPath $Worktree -File -Recurse -Force |
        Where-Object { -not $_.FullName.StartsWith("$gitDirectory\", [System.StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

    Get-ChildItem -LiteralPath $Worktree -Directory -Recurse -Force |
        Sort-Object FullName -Descending |
        Where-Object {
            -not $_.FullName.StartsWith("$gitDirectory\", [System.StringComparison]::OrdinalIgnoreCase) -and
            $_.FullName -ne $Worktree
        } |
        ForEach-Object {
            if (-not (Get-ChildItem -LiteralPath $_.FullName -Force)) {
                Remove-Item -LiteralPath $_.FullName -Force
            }
        }
}

function ConvertTo-IsoUtc {
    param([Parameter(Mandatory = $true)]$Value)
    if ($Value -is [datetime]) {
        return $Value.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    }
    return ([string]$Value).Trim()
}

function Write-Meta {
    param(
        [Parameter(Mandatory = $true)][string]$PublishedAt,
        [Parameter(Mandatory = $true)][string]$GeneratedAt,
        [Parameter(Mandatory = $true)][string]$SnapshotId
    )
    $meta = [ordered]@{
        schema_version = 1
        generated_at = $GeneratedAt
        snapshot_id = $SnapshotId
        # Compatibility field: this is the timestamp of the exported snapshot.
        mirror_synced_at = $GeneratedAt
        # This marker is written immediately before the push. The version is
        # public only if the push succeeds; SYNC_SUCCESS records the exact
        # post-push completion time.
        published_at = $PublishedAt
        source = "local-radar"
        data_branch = $Branch
        last_sync_status = "success"
    }
    $metaJson = ($meta | ConvertTo-Json -Depth 4) + [Environment]::NewLine
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $exportDir "meta.json"), $metaJson, $utf8NoBom)
}

function New-DataWorktree {
    if (Test-Path -LiteralPath $dataWorktree) {
        Remove-Item -LiteralPath $dataWorktree -Recurse -Force
    }
    $cloneOutput = @(& git clone --quiet --branch $Branch --single-branch $remoteUrl $dataWorktree 2>&1)
    if ($LASTEXITCODE -eq 0) {
        return
    }
    if (Test-Path -LiteralPath $dataWorktree) {
        Remove-Item -LiteralPath $dataWorktree -Recurse -Force
    }
    $bootstrapOutput = @(& git clone --quiet --single-branch $remoteUrl $dataWorktree 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "git clone failed: $(Redact-SensitiveText (($cloneOutput + $bootstrapOutput) -join ' '))"
    }
    Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments @("switch", "--orphan", $Branch) | Out-Null
}

try {
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Backend virtual environment not found. Run start-radar.bat once first."
    }

    New-Item -ItemType Directory -Path $exportDir -Force | Out-Null
    & $python (Join-Path $repoRoot "scripts\public_export.py") --output $exportDir | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Public data export failed with exit code $LASTEXITCODE."
    }
    $exportFinished = [datetimeoffset]::UtcNow
    $index = Get-Content -LiteralPath (Join-Path $exportDir "index.json") -Raw | ConvertFrom-Json
    $generatedAt = ConvertTo-IsoUtc $index.generated_at
    if (-not $generatedAt) {
        throw "Public export did not provide index.generated_at."
    }
    $snapshotId = "snap-$($generatedAt.Replace(':', '').Replace('-', '').Replace('.', ''))-$([guid]::NewGuid().ToString('N').Substring(0, 6))"
    Write-MirrorEvent -Event "PUBLIC_MIRROR_EXPORT_COMPLETED" -Fields @{
        cycle_started_at = Format-CadenceTimestamp $cycleStarted
        snapshot_generated_at = $generatedAt
        push_started_at = "-"
        sync_finished_at = "-"
        published_at = "-"
        mirror_synced_at = $generatedAt
        duration_ms = [math]::Round(($exportFinished - $cycleStarted).TotalMilliseconds, 0)
        attempt = 0
        previous_success_at = Format-PreviousSuccess
        seconds_since_previous_success = Format-SecondsSincePreviousSuccess $exportFinished
        trigger = $Trigger
        result = "completed"
    }

    if ($RemoteUrl) {
        $remoteUrl = $RemoteUrl
    } else {
        $remoteOutput = @(Invoke-GitChecked -Arguments @("remote", "get-url", $Remote))
        $remoteUrl = if ($remoteOutput.Count -gt 0) { $remoteOutput[0].ToString().Trim() } else { "" }
    }
    if (-not $remoteUrl) {
        throw "Remote URL is empty for '$Remote'."
    }

    New-Item -ItemType Directory -Path $syncRoot -Force | Out-Null
    $worktreePrepared = $false
    $committed = $false
    $attempt = 1
    $terminalFailure = $null

    while ($attempt -le $MaxAttempts) {
        if ($attempt -gt 1) {
            # Retry delays are 30s, 60s and 120s between attempts. The export
            # directory and its generated snapshot are deliberately reused.
            Start-Sleep -Seconds $retryDelaysSeconds[$attempt - 1]
        }

        $pushStarted = $null
        try {
            if (-not $worktreePrepared) {
                New-DataWorktree
                Clear-DataWorktreeFiles -Worktree $dataWorktree
                foreach ($filename in $requiredFiles | Where-Object { $_ -ne "meta.json" }) {
                    $source = Join-Path $exportDir $filename
                    if (-not (Test-Path -LiteralPath $source)) {
                        throw "Required public data file is missing: $filename"
                    }
                    Copy-Item -LiteralPath $source -Destination (Join-Path $dataWorktree $filename) -Force
                }
                Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments @("config", "user.name", "Codex Reset Radar Mirror") | Out-Null
                Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments @("config", "user.email", "mirror@users.noreply.github.com") | Out-Null
                $worktreePrepared = $true
            }

            $pushStarted = [datetimeoffset]::UtcNow
            Write-Meta -PublishedAt (Format-CadenceTimestamp $pushStarted) -GeneratedAt $generatedAt -SnapshotId $snapshotId
            Copy-Item -LiteralPath (Join-Path $exportDir "meta.json") -Destination (Join-Path $dataWorktree "meta.json") -Force
            $addArguments = @("add", "--") + $requiredFiles
            Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments $addArguments | Out-Null
            if (-not $committed) {
                $diffArguments = @("diff", "--cached", "--name-only", "--") + $requiredFiles
                $staged = @(Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments $diffArguments)
                if ($staged.Count -eq 0) {
                    $skippedAt = [datetimeoffset]::UtcNow
                    Write-MirrorEvent -Event "PUBLIC_MIRROR_SYNC_SKIPPED" -Fields @{
                        cycle_started_at = Format-CadenceTimestamp $cycleStarted
                        snapshot_generated_at = $generatedAt
                        push_started_at = "-"
                        sync_finished_at = Format-CadenceTimestamp $skippedAt
                        published_at = "-"
                        mirror_synced_at = $generatedAt
                        duration_ms = [math]::Round(($skippedAt - $cycleStarted).TotalMilliseconds, 0)
                        attempt = $attempt
                        previous_success_at = Format-PreviousSuccess
                        seconds_since_previous_success = Format-SecondsSincePreviousSuccess $skippedAt
                        trigger = $Trigger
                        result = "skipped"
                        terminal = "true"
                        reason = "no_changes"
                    }
                    $exitCode = 0
                    break
                }
                if ($DryRun) {
                    Write-MirrorEvent -Event "PUBLIC_MIRROR_SYNC_SKIPPED" -Fields @{
                        cycle_started_at = Format-CadenceTimestamp $cycleStarted
                        snapshot_generated_at = $generatedAt
                        push_started_at = Format-CadenceTimestamp $pushStarted
                        sync_finished_at = Format-CadenceTimestamp ([datetimeoffset]::UtcNow)
                        published_at = "-"
                        mirror_synced_at = $generatedAt
                        duration_ms = [math]::Round(([datetimeoffset]::UtcNow - $cycleStarted).TotalMilliseconds, 0)
                        attempt = $attempt
                        previous_success_at = Format-PreviousSuccess
                        seconds_since_previous_success = Format-SecondsSincePreviousSuccess ([datetimeoffset]::UtcNow)
                        trigger = $Trigger
                        result = "skipped"
                        terminal = "true"
                        reason = "dry_run"
                    }
                    $exitCode = 0
                    break
                }
                Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments @("commit", "-m", "chore(data): update public radar mirror") | Out-Null
                $committed = $true
            } else {
                # Only the publication marker changes on a retry. The exported
                # snapshot itself is reused; SQLite is never read again here.
                Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments @("commit", "--amend", "--no-edit") | Out-Null
            }

            Write-MirrorEvent -Event "PUBLIC_MIRROR_PUSH_STARTED" -Fields @{
                cycle_started_at = Format-CadenceTimestamp $cycleStarted
                snapshot_generated_at = $generatedAt
                push_started_at = Format-CadenceTimestamp $pushStarted
                sync_finished_at = "-"
                published_at = "-"
                mirror_synced_at = $generatedAt
                duration_ms = [math]::Round(($pushStarted - $cycleStarted).TotalMilliseconds, 0)
                attempt = $attempt
                previous_success_at = Format-PreviousSuccess
                seconds_since_previous_success = Format-SecondsSincePreviousSuccess $pushStarted
                trigger = $Trigger
                result = "started"
            }
            Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments @("push", $Remote, "HEAD:$Branch") | Out-Null
            $syncFinished = [datetimeoffset]::UtcNow
            Write-MirrorEvent -Event "PUBLIC_MIRROR_SYNC_SUCCESS" -Fields @{
                cycle_started_at = Format-CadenceTimestamp $cycleStarted
                snapshot_generated_at = $generatedAt
                push_started_at = Format-CadenceTimestamp $pushStarted
                sync_finished_at = Format-CadenceTimestamp $syncFinished
                published_at = Format-CadenceTimestamp $syncFinished
                mirror_synced_at = $generatedAt
                duration_ms = [math]::Round(($syncFinished - $cycleStarted).TotalMilliseconds, 0)
                attempt = $attempt
                previous_success_at = Format-PreviousSuccess
                seconds_since_previous_success = Format-SecondsSincePreviousSuccess $syncFinished
                trigger = $Trigger
                result = "success"
                terminal = "true"
                push_attempt = $attempt
            }
            $exitCode = 0
            break
        } catch {
            $failedAt = [datetimeoffset]::UtcNow
            $reason = Redact-SensitiveText $_.Exception.Message
            $errorType = Get-MirrorErrorType $reason
            $retryable = $errorType -in @("network_connect", "network_timeout", "network_reset", "network_dns")
            $terminal = (-not $retryable) -or ($attempt -ge $MaxAttempts)
            Write-MirrorEvent -Event "PUBLIC_MIRROR_SYNC_FAILED" -Fields @{
                cycle_started_at = Format-CadenceTimestamp $cycleStarted
                snapshot_generated_at = $generatedAt
                push_started_at = if ($pushStarted) { Format-CadenceTimestamp $pushStarted } else { "-" }
                sync_finished_at = Format-CadenceTimestamp $failedAt
                published_at = "-"
                mirror_synced_at = $generatedAt
                duration_ms = [math]::Round(($failedAt - $cycleStarted).TotalMilliseconds, 0)
                attempt = $attempt
                previous_success_at = Format-PreviousSuccess
                seconds_since_previous_success = Format-SecondsSincePreviousSuccess $failedAt
                trigger = $Trigger
                result = "failed"
                error_type = $errorType
                terminal = if ($terminal) { "true" } else { "false" }
                reason = $reason
            }
            if ($terminal) {
                $terminalFailureWritten = $true
                $terminalFailure = $reason
                $exitCode = 1
                break
            }
            $delay = $retryDelaysSeconds[$attempt]
            Write-MirrorEvent -Event "PUBLIC_MIRROR_RETRY_SCHEDULED" -Fields @{
                cycle_started_at = Format-CadenceTimestamp $cycleStarted
                snapshot_generated_at = $generatedAt
                push_started_at = if ($pushStarted) { Format-CadenceTimestamp $pushStarted } else { "-" }
                sync_finished_at = Format-CadenceTimestamp $failedAt
                published_at = "-"
                mirror_synced_at = $generatedAt
                duration_ms = [math]::Round(($failedAt - $cycleStarted).TotalMilliseconds, 0)
                attempt = $attempt
                next_attempt = $attempt + 1
                previous_success_at = Format-PreviousSuccess
                seconds_since_previous_success = Format-SecondsSincePreviousSuccess $failedAt
                retry_delay_seconds = $delay
                trigger = $Trigger
                result = "retry_scheduled"
                error_type = $errorType
                reason = $reason
            }
            $attempt++
        }
    }

    if ($terminalFailure) {
        $exitCode = 1
    }
    exit $exitCode
} catch {
    if (-not $terminalFailureWritten) {
        $failedAt = [datetimeoffset]::UtcNow
        $reason = Redact-SensitiveText $_.Exception.Message
        Write-MirrorEvent -Event "PUBLIC_MIRROR_SYNC_FAILED" -Fields @{
            cycle_started_at = Format-CadenceTimestamp $cycleStarted
            snapshot_generated_at = "-"
            push_started_at = "-"
            sync_finished_at = Format-CadenceTimestamp $failedAt
            published_at = "-"
            mirror_synced_at = "-"
            duration_ms = [math]::Round(($failedAt - $cycleStarted).TotalMilliseconds, 0)
            attempt = 0
            previous_success_at = Format-PreviousSuccess
            seconds_since_previous_success = Format-SecondsSincePreviousSuccess $failedAt
            trigger = $Trigger
            result = "failed"
            error_type = Get-MirrorErrorType $reason
            terminal = "true"
            reason = $reason
        }
    }
    $exitCode = 1
} finally {
    Remove-GeneratedSyncDirectory
}

exit $exitCode
