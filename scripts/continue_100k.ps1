# Unattended 100K scale ladder: prepare → Qdrant → Mongo → analyze.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
$log = Join-Path (Get-Location) "experiments\results\scale100k.log"
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

# Embeddings already frozen at 100K; skip re-download/encode.
Invoke-Step "qdrant-up" { & (Join-Path $PSScriptRoot "one_engine.ps1") qdrant }
Start-Sleep -Seconds 8
Invoke-Step "qdrant-run" {
    & $py -m src.runners.study run --engine qdrant --experiments E0,E1,E2,E3,E4,E5,E6 --min-n 50000 --max-n 100000 --run-id qdrant-100k-vol
}

Invoke-Step "mongo-up" { & (Join-Path $PSScriptRoot "one_engine.ps1") mongo }
Start-Sleep -Seconds 12
Invoke-Step "mongo-run" {
    & $py -m src.runners.study run --engine mongo --experiments E0,E1,E2,E3,E4,E5,E6 --min-n 50000 --max-n 100000 --run-id mongo-100k
}

Invoke-Step "analyze" { & $py -m src.runners.study analyze }
& (Join-Path $PSScriptRoot "one_engine.ps1") none
Log "DONE 100K ladder"
