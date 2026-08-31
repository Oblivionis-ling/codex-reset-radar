[CmdletBinding()]
param(
    [switch]$DryRun,
    [string]$Branch = "data",
    [string]$Remote = "origin",
    [string]$RemoteUrl,
    [ValidateRange(1, 3)]
    [int]$MaxPushAttempts = 3,
    [ValidateRange(0, 60)]
    [int]$RetryDelaySeconds = 2
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
$syncRoot = Join-Path $repoRoot "_tmp\public-data-sync-$PID"
$exportDir = Join-Path $syncRoot "export"
$dataWorktree = Join-Path $syncRoot "data-worktree"
$requiredFiles = @("index.json", "tweets.json", "radar.json", "health.json", "resets.json", "meta.json")

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
        throw "git $($Arguments -join ' ') failed: $($output -join ' ')"
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

try {
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Backend virtual environment not found. Run start-radar.bat once first."
    }

    New-Item -ItemType Directory -Path $exportDir -Force | Out-Null
    & $python (Join-Path $repoRoot "scripts\public_export.py") --output $exportDir
    if ($LASTEXITCODE -ne 0) {
        throw "Public data export failed with exit code $LASTEXITCODE."
    }

    $index = Get-Content -LiteralPath (Join-Path $exportDir "index.json") -Raw | ConvertFrom-Json
    $generatedAt = ConvertTo-IsoUtc $index.generated_at
    if (-not $generatedAt) {
        throw "Public export did not provide index.generated_at."
    }

    # mirror_synced_at is intentionally tied to the exported snapshot time;
    # the file is only published after the data branch push succeeds.
    $meta = [ordered]@{
        schema_version = 1
        generated_at = $generatedAt
        mirror_synced_at = $generatedAt
        source = "local-radar"
        data_branch = $Branch
        last_sync_status = "success"
    }
    $metaJson = ($meta | ConvertTo-Json -Depth 4) + [Environment]::NewLine
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $exportDir "meta.json"), $metaJson, $utf8NoBom)

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
    $cloneOutput = @(& git clone --quiet --branch $Branch --single-branch $remoteUrl $dataWorktree 2>&1)
    $cloneExit = $LASTEXITCODE
    if ($cloneExit -ne 0) {
        if (Test-Path -LiteralPath $dataWorktree) {
            Remove-Item -LiteralPath $dataWorktree -Recurse -Force
        }
        $cloneOutput = @(& git clone --quiet --single-branch $remoteUrl $dataWorktree 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "Could not clone the data branch or its bootstrap source: $($cloneOutput -join ' ')"
        }
        Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments @("switch", "--orphan", $Branch) | Out-Null
    }

    Clear-DataWorktreeFiles -Worktree $dataWorktree
    foreach ($filename in $requiredFiles) {
        $source = Join-Path $exportDir $filename
        if (-not (Test-Path -LiteralPath $source)) {
            throw "Required public data file is missing: $filename"
        }
        Copy-Item -LiteralPath $source -Destination (Join-Path $dataWorktree $filename) -Force
    }

    Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments @("config", "user.name", "Codex Reset Radar Mirror") | Out-Null
    Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments @("config", "user.email", "mirror@users.noreply.github.com") | Out-Null
    $addArguments = @("add", "--") + $requiredFiles
    Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments $addArguments | Out-Null
    $diffArguments = @("diff", "--cached", "--name-only", "--") + $requiredFiles
    $staged = @(Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments $diffArguments)
    if ($staged.Count -eq 0) {
        Write-Host "Public data branch is unchanged; nothing to push."
        exit 0
    }

    if ($DryRun) {
        Write-Host "Dry run: data branch changes"
        Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments @("diff", "--cached", "--stat")
        exit 0
    }

    Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments @("commit", "-m", "chore(data): update public radar mirror") | Out-Null
    $pushSucceeded = $false
    for ($attempt = 1; $attempt -le $MaxPushAttempts; $attempt++) {
        try {
            $pushOutput = @(Invoke-GitChecked -WorkingDirectory $dataWorktree -Arguments @("push", $Remote, "HEAD:$Branch"))
            $pushSucceeded = $true
            Write-Host "Public data mirror pushed to '$Branch' on attempt $attempt."
            break
        } catch {
            $pushOutput = @($_.Exception.Message)
            Write-Warning "Public data push attempt $attempt/$MaxPushAttempts failed: $($pushOutput -join ' ')"
        }
        if ($attempt -lt $MaxPushAttempts -and $RetryDelaySeconds -gt 0) {
            Start-Sleep -Seconds $RetryDelaySeconds
        }
    }
    if (-not $pushSucceeded) {
        throw "Public data push failed after $MaxPushAttempts attempts."
    }
    exit 0
} catch {
    Write-Error "PUBLIC_MIRROR_SYNC_FAILED: $($_.Exception.Message)"
    exit 1
} finally {
    Remove-GeneratedSyncDirectory
}
