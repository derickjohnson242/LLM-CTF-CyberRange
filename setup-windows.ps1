# OWASP LLM CTF -- Windows 11 Setup Script
# Run this in PowerShell as Administrator

Write-Host "`n[ OWASP LLM CTF SETUP ]" -ForegroundColor Green
Write-Host "========================`n"

Write-Host "[1/5] Checking Docker Desktop..." -ForegroundColor Cyan
try {
    $dockerVersion = docker --version 2>&1
    Write-Host "      OK: $dockerVersion" -ForegroundColor Green
} catch {
    Write-Host "      ERROR: Docker not found." -ForegroundColor Red
    Write-Host "      Install Docker Desktop from: https://www.docker.com/products/docker-desktop/"
    Write-Host "      Make sure WSL2 backend is enabled in Docker Desktop settings."
    exit 1
}

$dockerPs = docker ps 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "      ERROR: Docker Desktop is installed but not running." -ForegroundColor Red
    Write-Host "      Please start Docker Desktop and run this script again."
    exit 1
}

Write-Host "`n[2/5] Detecting network IP..." -ForegroundColor Cyan
$hostIP = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.InterfaceAlias -notlike '*Loopback*' -and $_.IPAddress -notlike '169.*' } |
    Select-Object -First 1).IPAddress
Write-Host "      Your IP: $hostIP" -ForegroundColor Yellow
Write-Host "      Students connect to: http://$($hostIP):8080" -ForegroundColor Yellow

Write-Host "`n[3/5] Configuring Windows Firewall for port 8080..." -ForegroundColor Cyan
$existingRule = Get-NetFirewallRule -DisplayName "CTF-LLM-8080" -ErrorAction SilentlyContinue
if ($existingRule) {
    Write-Host "      Firewall rule already exists, skipping." -ForegroundColor Green
} else {
    New-NetFirewallRule `
        -DisplayName "CTF-LLM-8080" `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort 8080 `
        -Action Allow | Out-Null
    Write-Host "      Firewall rule created for port 8080." -ForegroundColor Green
}

Write-Host "`n[3b/5] Checking class passcode..." -ForegroundColor Cyan
$envPath = Join-Path $PSScriptRoot ".env"
$classPasscode = $null
if (Test-Path $envPath) {
    $existing = Get-Content $envPath -Raw -ErrorAction SilentlyContinue
    if ($existing -match '(?m)^CLASS_PASSCODE=(.*)$') {
        $classPasscode = $matches[1].Trim()
    }
}
if (-not $classPasscode) {
    $passcodeChars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
    $classPasscode = -join ((1..12) | ForEach-Object { $passcodeChars[(Get-Random -Maximum $passcodeChars.Length)] })
    Add-Content -Path $envPath -Value "CLASS_PASSCODE=$classPasscode" -Encoding ascii
    Write-Host "      Generated a new class passcode and saved it to .env" -ForegroundColor Green
} else {
    Write-Host "      Using existing CLASS_PASSCODE from .env" -ForegroundColor Green
}

Write-Host "`n[4/5] Starting Docker stack (this pulls Ollama + llama3.2:3b + nomic-embed-text -- ~2.3 GB total, be patient)..." -ForegroundColor Cyan
Write-Host "      This also builds 8 separate service images: gateway, group-a," -ForegroundColor Gray
Write-Host "      llm03, llm04, llm05, llm05-renderer, llm06, llm08 -- first run takes a while." -ForegroundColor Gray
Set-Location $PSScriptRoot
docker compose up -d --build

if ($LASTEXITCODE -ne 0) {
    Write-Host "      ERROR: docker compose failed. Check output above." -ForegroundColor Red
    exit 1
}
Write-Host "      Containers started." -ForegroundColor Green

Write-Host "`n[5/5] Waiting for llama3.2:3b to finish downloading..." -ForegroundColor Cyan
Write-Host "      (Check progress: docker logs ctf-model-pull -f)" -ForegroundColor Gray

$timeout = 600  # 10 minutes
$elapsed = 0
while ($elapsed -lt $timeout) {
    $status = docker inspect --format='{{.State.Status}}' ctf-model-pull 2>$null
    if ($status -eq "exited") {
        $exitCode = docker inspect --format='{{.State.ExitCode}}' ctf-model-pull
        if ($exitCode -eq "0") {
            Write-Host "      Model downloaded successfully!" -ForegroundColor Green
            break
        } else {
            Write-Host "      ERROR: Model pull failed. Run: docker logs ctf-model-pull" -ForegroundColor Red
            exit 1
        }
    }
    Start-Sleep -Seconds 5
    $elapsed += 5
    Write-Host "      Waiting... ($elapsed s)" -ForegroundColor Gray
}

Write-Host "`nWaiting for gateway to come up..." -ForegroundColor Cyan
$gwTimeout = 120
$gwElapsed = 0
while ($gwElapsed -lt $gwTimeout) {
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:8080/health" -TimeoutSec 3
        if ($health.status -eq "ok") {
            Write-Host "      Gateway OK -- $($health.challenges_registered) challenges registered." -ForegroundColor Green
            break
        }
    } catch {}
    Start-Sleep -Seconds 3
    $gwElapsed += 3
}

Write-Host "`n========================================" -ForegroundColor Green
Write-Host " CTF RANGE IS READY" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host " Web UI (you):      http://localhost:8080" -ForegroundColor Yellow
Write-Host " Student URL:       http://$($hostIP):8080" -ForegroundColor Yellow
Write-Host " Health check:      http://localhost:8080/health" -ForegroundColor Yellow
Write-Host ""
Write-Host " Class passcode:    $classPasscode  (also saved in .env)" -ForegroundColor Cyan
Write-Host " Students log in with a handle plus this passcode before they can see any challenge." -ForegroundColor Gray
Write-Host " Ollama itself is not reachable from outside Docker -- every request goes through the gateway." -ForegroundColor Gray
Write-Host ""
Write-Host " Stop the lab:      docker compose down" -ForegroundColor Gray
Write-Host " View gateway logs: docker logs ctf-gateway -f" -ForegroundColor Gray
Write-Host " View a challenge:  docker logs ctf-<challenge-or-group> -f   (e.g. ctf-group-a, ctf-llm03)" -ForegroundColor Gray
Write-Host ""
