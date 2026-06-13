$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root ".venv"

if (-not (Test-Path $venv)) {
    python -m venv $venv
}

$python = Join-Path $venv "Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $root "requirements.txt")

Write-Host ""
Write-Host "Edge Agent kurulumu tamamlandi."
Write-Host "Saglik testi: .\.venv\Scripts\python.exe .\health_check.py"
Write-Host "Baslatma:     .\.venv\Scripts\python.exe .\main.py"
