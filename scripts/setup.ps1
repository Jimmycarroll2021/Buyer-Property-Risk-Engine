param([switch]$NoStart)
$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) { py -3.13 -m venv .venv }
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { python -m venv .venv }
    else { throw 'Install Python 3.12 or 3.13, then run setup again.' }
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the Python environment.' }
}
& '.venv\Scripts\python.exe' -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& '.venv\Scripts\python.exe' -m pip install --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw 'Application installation failed.' }
& '.venv\Scripts\python.exe' -m riskengine init
& '.venv\Scripts\python.exe' -m riskengine demo
if ($LASTEXITCODE -ne 0) { throw 'Demonstration did not complete. Read the error above.' }
Write-Host 'Setup complete. Open runtime\demo-report.html for the sample report.'
if (-not $NoStart) {
    & '.venv\Scripts\python.exe' -m riskengine serve --desktop
}

