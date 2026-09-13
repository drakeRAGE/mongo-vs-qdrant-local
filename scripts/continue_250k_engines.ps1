# Resume 250K engine runs; embeddings already frozen.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
$log = Join-Path (Get-Location) "experiments\results\scale250k.log"

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
