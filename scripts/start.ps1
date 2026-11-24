param([int]$Port = 8010)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { throw 'Run .\scripts\setup.ps1 first.' }
if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) { throw 'Build the frontend with .\scripts\setup.ps1 first.' }
Write-Host "Memory Lab: http://127.0.0.1:$Port"
Write-Host 'Keep this terminal open. Use another PowerShell terminal for demo commands.'
& '.\.venv\Scripts\python.exe' -m uvicorn memory_demo.api:app --host 127.0.0.1 --port $Port
