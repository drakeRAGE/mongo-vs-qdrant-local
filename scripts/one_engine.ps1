# Bring up exactly one study profile and tear the other down.
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("mongo", "qdrant", "none")]
    [string]$Engine
)

$ErrorActionPreference = "Stop"
$ComposeDir = Join-Path $PSScriptRoot "..\compose"
$Project = "vectordb-proof"

function Invoke-Compose {
    param([string[]]$ComposeArgs)
    docker compose -p $Project -f (Join-Path $ComposeDir "docker-compose.yml") @ComposeArgs
}

Write-Host "Stopping all study profiles..."
Invoke-Compose @("--profile", "mongo", "down", "--remove-orphans")
Invoke-Compose @("--profile", "qdrant", "down", "--remove-orphans")

if ($Engine -eq "none") {
    Write-Host "No engine running."
    exit 0
}

New-Item -ItemType Directory -Force -Path (Join-Path $ComposeDir "..\data\docker\mongod") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ComposeDir "..\data\docker\mongot") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ComposeDir "..\data\docker\qdrant") | Out-Null

Write-Host "Starting profile $Engine ..."
Invoke-Compose @("--profile", $Engine, "up", "-d")
if ($Engine -eq "mongo") {
    Write-Host "Waiting for mongod ping and initiating replica set..."
    $py = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { $py = "python" }
    & $py (Join-Path $PSScriptRoot "init_mongo.py")
}
Write-Host "Profile $Engine is up. Run: python scripts/check_host.py --expect $Engine"
