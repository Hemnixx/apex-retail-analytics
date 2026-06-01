param(
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
    $pythonExe = 'python'
}

Push-Location $projectRoot
try {
    docker info | Out-Null

    docker compose up --build -d

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $healthUrl = 'http://127.0.0.1:8000/health'
    $healthy = $false

    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri $healthUrl -UseBasicParsing -TimeoutSec 5
            if ($health.status -eq 'healthy') {
                $healthy = $true
                break
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }

    if (-not $healthy) {
        throw "API did not become healthy within $TimeoutSeconds seconds."
    }

    & $pythonExe (Join-Path $projectRoot 'scripts\smoke_verify.py')
    docker compose ps
}
finally {
    Pop-Location
}