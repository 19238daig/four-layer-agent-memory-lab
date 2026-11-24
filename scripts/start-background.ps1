param([int]$Port = 8010, [switch]$OpenBrowser, [ValidateSet('studio','meal','overview')][string]$View = 'studio')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
$taskData = Join-Path $taskRoot 'data'
$taskUrl = "http://127.0.0.1:$Port"
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run scripts\setup.ps1 first.' }
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'frontend\dist\index.html'))) { throw 'Build the frontend with scripts\setup.ps1 first.' }

function Get-MemoryHealth {
    try {
        $taskResponse = Invoke-RestMethod -Uri "$taskUrl/api/health" -TimeoutSec 2
        if ($taskResponse.app -eq 'memory-lab' -and $taskResponse.ok) { return $true }
    } catch { }
    return $false
}

if (-not (Get-MemoryHealth)) {
    $taskListener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($taskListener) { throw "Port $Port is occupied by another service. No process was stopped." }
    New-Item -ItemType Directory -Path $taskData -Force | Out-Null
    $taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('-m','uvicorn','memory_demo.api:app','--host','127.0.0.1','--port',"$Port") -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskData 'server.stdout.log') -RedirectStandardError (Join-Path $taskData 'server.stderr.log') -PassThru
    Set-Content -LiteralPath (Join-Path $taskData 'server.pid') -Value $taskProcess.Id -Encoding ASCII
    $taskReady = $false
    for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
        if (Get-MemoryHealth) { $taskReady = $true; break }
        $taskProcess.Refresh()
        if ($taskProcess.HasExited) { throw "Service exited. Check data\server.stderr.log." }
        Start-Sleep -Milliseconds 300
    }
    if (-not $taskReady) { throw 'Service did not become ready. Check data\server.stderr.log.' }
}
Write-Host "Memory Lab is running in the background: $taskUrl"
Write-Host 'Logs: data\server.stdout.log and data\server.stderr.log'
if ($OpenBrowser) {
    $taskBrowserUrl = "$taskUrl/?view=$View"
    $taskEdgeCandidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe')
    )
    $taskEdge = $taskEdgeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($taskEdge) {
        Start-Process -FilePath $taskEdge -ArgumentList @('--new-window', $taskBrowserUrl)
        Write-Host 'Opened Microsoft Edge. If the window is behind another app, select Edge in the taskbar.'
    } else {
        Start-Process -FilePath $taskBrowserUrl
        Write-Host 'Asked the default browser to open the page.'
    }
}
