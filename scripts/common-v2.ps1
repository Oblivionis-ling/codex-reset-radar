$script:CrrRepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Resolve-CrrPython {
    param([string]$RepositoryRoot = $script:CrrRepositoryRoot)
    $candidates = @(
        (Join-Path $RepositoryRoot "apps\backend\.venv\Scripts\python.exe"),
        (Join-Path $RepositoryRoot "backend\.venv\Scripts\python.exe")
    )
    $python = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $python) {
        throw "No project Python environment found. Follow docs\v2\local-development.md to create apps\backend\.venv."
    }
    return $python
}
