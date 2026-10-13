$ErrorActionPreference = "Stop"

$ProjectRoot  = "D:\CMTI"
$BackendRoot  = Join-Path $ProjectRoot "backend"
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$Python       = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

$BackendProcess = $null
$FrontendProcess = $null

Clear-Host

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "              ManufacturaIQ" -ForegroundColor White
Write-Host "        Backend + Frontend Startup" -ForegroundColor White
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------
# Validate paths
# ---------------------------------------------------------

if (-not (Test-Path $Python)) {
    Write-Host "[ERROR] Python not found:" -ForegroundColor Red
    Write-Host $Python
    exit 1
}

if (-not (Test-Path $BackendRoot)) {
    Write-Host "[ERROR] Backend folder not found:" -ForegroundColor Red
    Write-Host $BackendRoot
    exit 1
}

if (-not (Test-Path $FrontendRoot)) {
    Write-Host "[ERROR] Frontend folder not found:" -ForegroundColor Red
    Write-Host $FrontendRoot
    exit 1
}

$BackendEnvPath = Join-Path $BackendRoot ".env"
if (-not (Test-Path $BackendEnvPath) -or -not (Select-String -LiteralPath $BackendEnvPath -Pattern '^\s*AUTH_JWT_SECRET\s*=\s*\S+' -Quiet)) {
    Write-Host "[WARN] AUTH_JWT_SECRET is not configured in backend\.env." -ForegroundColor Yellow
    Write-Host "       Login endpoints require it. Generate one with:" -ForegroundColor DarkYellow
    Write-Host "       $Python -c `"import secrets; print(secrets.token_urlsafe(48))`"" -ForegroundColor DarkGray
    Write-Host ""
}

# ---------------------------------------------------------
# Start backend
# ---------------------------------------------------------

try {

    Write-Host "[1/2] Starting Backend..." -ForegroundColor Yellow
    Write-Host "      http://127.0.0.1:8000" -ForegroundColor DarkGray
    Write-Host ""

    $BackendProcess = Start-Process `
        -FilePath $Python `
        -ArgumentList @(
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000"
        ) `
        -WorkingDirectory $BackendRoot `
        -NoNewWindow `
        -PassThru

    # -----------------------------------------------------
    # Wait for backend health
    # -----------------------------------------------------

    Write-Host "[WAIT] Waiting for backend..." -ForegroundColor Yellow

    $BackendReady = $false

    for ($i = 0; $i -lt 30; $i++) {

        Start-Sleep -Seconds 1

        try {
            $response = Invoke-RestMethod `
                -Uri "http://127.0.0.1:8000/health" `
                -Method Get `
                -TimeoutSec 2

            if ($response.status -eq "ok") {
                $BackendReady = $true
                break
            }
        }
        catch {
            # Backend still starting
        }

        if ($BackendProcess.HasExited) {
            throw "Backend process stopped unexpectedly."
        }
    }

    if (-not $BackendReady) {
        throw "Backend did not become healthy within 30 seconds."
    }

    Write-Host ""
    Write-Host "[OK] Backend online" -ForegroundColor Green
    Write-Host ""

    # ---------------------------------------------------------
    # Start frontend in same terminal
    # ---------------------------------------------------------

    Write-Host "[2/2] Starting Frontend..." -ForegroundColor Yellow
    Write-Host "      http://localhost:5173" -ForegroundColor DarkGray
    Write-Host ""

    $FrontendProcess = Start-Process `
        -FilePath "npm.cmd" `
        -ArgumentList @("run", "dev") `
        -WorkingDirectory $FrontendRoot `
        -NoNewWindow `
        -PassThru

    Start-Sleep -Seconds 3

    if ($FrontendProcess.HasExited) {
        throw "Frontend process stopped unexpectedly."
    }

    # ---------------------------------------------------------
    # Ready
    # ---------------------------------------------------------

    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Green
    Write-Host "              ManufacturaIQ READY" -ForegroundColor Green
    Write-Host "==================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Frontend : http://localhost:5173" -ForegroundColor White
    Write-Host "Backend  : http://127.0.0.1:8000" -ForegroundColor White
    Write-Host "Health   : http://127.0.0.1:8000/health" -ForegroundColor White
    Write-Host "Ready    : http://127.0.0.1:8000/ready" -ForegroundColor White
    Write-Host ""
    Write-Host "Press CTRL+C to stop ManufacturaIQ." -ForegroundColor Yellow
    Write-Host ""

    Start-Process "http://localhost:5173"

    # ---------------------------------------------------------
    # Keep script alive
    # ---------------------------------------------------------

    while ($true) {

        Start-Sleep -Seconds 2

        if ($BackendProcess.HasExited) {
            Write-Host ""
            Write-Host "[ERROR] Backend stopped unexpectedly." -ForegroundColor Red
            break
        }

        if ($FrontendProcess.HasExited) {
            Write-Host ""
            Write-Host "[ERROR] Frontend stopped unexpectedly." -ForegroundColor Red
            break
        }
    }
}
finally {

    Write-Host ""
    Write-Host "Stopping ManufacturaIQ..." -ForegroundColor Yellow

    if ($FrontendProcess -and -not $FrontendProcess.HasExited) {
        Stop-Process -Id $FrontendProcess.Id -Force -ErrorAction SilentlyContinue
    }

    if ($BackendProcess -and -not $BackendProcess.HasExited) {
        Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue
    }

    Write-Host "ManufacturaIQ stopped." -ForegroundColor Green
}
