# Unattended 250K scale: extend embeddings, then Qdrant, Mongo, analyze.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
$log = Join-Path (Get-Location) "experiments\results\scale250k.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

function Log([string]$m) {
    $line = "{0} {1}" -f (Get-Date -Format o), $m
    Add-Content -Path $log -Value $line
    Write-Host $line
}

function Invoke-Step([string]$name, [scriptblock]$block) {
    Log "START $name"
    & $block
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        Log "FAIL $name exit=$LASTEXITCODE"
        throw "$name failed with exit $LASTEXITCODE"
    }
    Log "OK $name"
}

$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

function Stop-DockerForEmbed {
    Log "stopping Docker/WSL to free RAM for encode"
    docker compose -p vectordb-proof -f (Join-Path (Get-Location) "compose\docker-compose.yml") --profile mongo down --remove-orphans 2>$null
    docker compose -p vectordb-proof -f (Join-Path (Get-Location) "compose\docker-compose.yml") --profile qdrant down --remove-orphans 2>$null
    Get-Process "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    wsl --shutdown
    Start-Sleep -Seconds 5
}

function Wait-Docker {
    $desktop = "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe"
    if (-not (Test-Path $desktop)) {
        $desktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    }
    if (Test-Path $desktop) {
        Start-Process $desktop
    }
    $deadline = (Get-Date).AddMinutes(6)
    while ((Get-Date) -lt $deadline) {
        cmd /c "docker info >nul 2>&1"
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 5
    }
    throw "Docker did not become ready"
}

Stop-DockerForEmbed

Invoke-Step "prepare-250k" {
    & $py -m src.runners.study prepare --max-docs 250000 --batch-size 64
}

Log "starting Docker for engine runs"
Wait-Docker

Invoke-Step "qdrant-up" { & (Join-Path $PSScriptRoot "one_engine.ps1") qdrant }
Start-Sleep -Seconds 8
Invoke-Step "qdrant-run" {
    & $py -m src.runners.study run --engine qdrant --experiments E0,E1,E2,E3,E4,E5,E6 --min-n 250000 --max-n 250000 --run-id qdrant-250k
}

Invoke-Step "mongo-up" { & (Join-Path $PSScriptRoot "one_engine.ps1") mongo }
Start-Sleep -Seconds 12
Invoke-Step "mongo-run" {
    & $py -m src.runners.study run --engine mongo --experiments E0,E1,E2,E3,E4,E5,E6 --min-n 250000 --max-n 250000 --run-id mongo-250k
}

Invoke-Step "analyze" { & $py -m src.runners.study analyze }
& (Join-Path $PSScriptRoot "one_engine.ps1") none
Log "DONE 250K ladder"
