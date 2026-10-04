# Usage:  .\rmm.ps1 start | stop | restart | status   [-Agent] [-Frontend]
param(
    [ValidateSet('start','stop','restart','status')][string]$Action = 'restart',
    [switch]$Agent,      # also run the local agent (needs an elevated shell for patching)
    [switch]$Frontend    # also run the React dev server
)

$Root = $PSScriptRoot
$Ports = @{ API = 5000; Dashboard = 8501; React = 3000 }

function Test-Port($p) { [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) }

function Stop-All {
    foreach ($p in $Ports.Values) {
        Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    }
    # Celery worker + beat (also kills any duplicate beat), and the agent
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -match 'celery|rmm_agent\.py' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host 'Stopped.'
}

function Start-Svc($name, $dir, $cmd) {
    Start-Process powershell -WindowStyle Minimized -WorkingDirectory (Join-Path $Root $dir) `
        -ArgumentList '-NoExit', '-Command', "`$Host.UI.RawUI.WindowTitle='RMM $name'; $cmd"
    Write-Host "Started $name"
}

function Start-All {
    foreach ($p in 6379, 5432) {
        if (-not (Test-Port $p)) { Write-Warning "Nothing listening on $p (Redis=6379 / Postgres=5432). Start that service first (elevated)." }
    }
    Start-Svc 'API'       'api'       '.\venv\Scripts\python.exe app.py'
    Start-Svc 'Worker'    'api'       '.\venv\Scripts\celery.exe -A tasks.celery_app worker --pool=solo -l info'
    Start-Svc 'Beat'      'api'       '.\venv\Scripts\celery.exe -A tasks.celery_app beat -l info --pidfile=celerybeat.pid'
    Start-Svc 'Dashboard' 'dashboard' '.\venv\Scripts\streamlit.exe run app.py'
    if ($Frontend) { Start-Svc 'React' 'frontend' 'npm run dev' }
    if ($Agent)    { Start-Svc 'Agent' 'agent'    '.\venv\Scripts\python.exe rmm_agent.py' }

    Write-Host 'Waiting for API health...'
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $r = Invoke-WebRequest http://localhost:5000/api/health -UseBasicParsing -TimeoutSec 2
            Write-Host "API health: HTTP $($r.StatusCode)"; return
        } catch { Start-Sleep 1 }
    }
    Write-Warning 'API did not answer /api/health within 30s - check the "RMM API" window.'
}

function Show-Status {
    $Ports.GetEnumerator() | ForEach-Object { '{0,-10} :{1}  {2}' -f $_.Key, $_.Value, $(if (Test-Port $_.Value) {'UP'} else {'down'}) }
    $c = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'celery' })
    "Celery procs: $($c.Count)"
}

switch ($Action) {
    'start'   { Start-All }
    'stop'    { Stop-All }
    'restart' { Stop-All; Start-Sleep 2; Start-All }
    'status'  { Show-Status }
}
