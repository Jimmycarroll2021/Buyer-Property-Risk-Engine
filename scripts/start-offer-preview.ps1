param([ValidateRange(1, 65535)][int]$Port = 8131)
$ErrorActionPreference = "Stop"
$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectDir ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $pythonPath)) { throw "Install the project dependencies before starting the local preview." }
Push-Location $projectDir
try {
    & $pythonPath -m riskengine --data-dir runtime/buyer-preview init | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not initialize the dedicated buyer preview." }
    if (Test-Path -LiteralPath "runtime/buyer-preview/jardine-3-9-kingston/public-observations.json") {
        & $pythonPath "scripts/seed-first-home-preview.py"
        if ($LASTEXITCODE -ne 0) { throw "Could not prepare the Jardine worked example." }
    }
    Write-Host "Open http://127.0.0.1:$Port/ to build an offer brief."
    & $pythonPath -m riskengine --data-dir runtime/buyer-preview serve --sample-preview --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) { throw "Could not start the local preview on port $Port." }
} finally { Pop-Location }
