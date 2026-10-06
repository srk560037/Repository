# ==============================================================================
# Script: start-backend.ps1
# Description: Runs pytest with coverage threshold before launching Uvicorn
# ==============================================================================

$ErrorActionPreference = "Stop"

# Navigate to the script root directory (backend)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location -Path $scriptDir

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Running Pre-Flight Unit Tests & Coverage  " -ForegroundColor Cyan
Write-Host " Minimum Required Coverage: 90%           " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Path to virtual environment Python executable
$pythonExe = Join-Path $scriptDir "venv\Scripts\python.exe"
if (-not (Test-Path -Path $pythonExe)) {
    $pythonExe = "python"
}

# 2. Execute Pytest with coverage threshold enforcement
try {
    & $pythonExe -m pytest --cov=. --cov-report=term-missing --cov-fail-under=90
    if ($LASTEXITCODE -ne 0) {
        throw "Pre-flight checks failed: Unit tests or coverage threshold (<90%) did not pass."
    }
    Write-Host "`n[SUCCESS] All unit tests passed & coverage requirement met (>= 90%)!" -ForegroundColor Green
}
catch {
    Write-Host "`n[ERROR] Pre-flight health checks failed. Aborting backend startup." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

# 3. Launch Uvicorn Development Server
Write-Host "`n==========================================" -ForegroundColor Cyan
Write-Host " Starting Uvicorn FastAPI Server...        " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

& $pythonExe -m uvicorn main:app --reload --port 8000