# AGMO calistiricisi (Windows): venv kur -> paketi bagla -> calistir
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
    & ".\.venv\Scripts\python.exe" -m pip install -q --upgrade pip
}
& ".\.venv\Scripts\python.exe" -m pip install -q -e . | Out-Null
& ".\.venv\Scripts\python.exe" -m agmo @args