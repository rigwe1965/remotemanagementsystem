# Usage:  .\rmm.ps1 start | stop | restart | status   [-NoAgent] [-Frontend]
param(
    [ValidateSet('start','stop','restart','status','test')][string]$Action = 'restart',
    [switch]$Agent,      # kept for compatibility - the agent now starts by default
    [switch]$NoAgent,    # skip the local agent (it needs an elevated shell for patching)
    [switch]$Frontend    # also run the React dev server
)

$Root = $PSScriptRoot
$Ports = @{ API = 5000; Dashboard = 8501; React = 3000 }

function Test-Port($p) { [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) }

function Stop-All {
    # Order matters: close host windows, then parents (Flask reloader / streamlit respawn children), then ports.
    Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
        Where-Object { $_.CommandLine -match "WindowTitle='RMM " } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -like "*$Root*" -or $_.CommandLine -match 'celery|rmm_agent\.py|streamlit' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep 1
    foreach ($p in $Ports.Values) {
        Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    }
    Write-Host 'Stopped.'
}

function Start-Svc($name, $dir, $cmd) {
    Start-Process powershell -WindowStyle Minimized -WorkingDirectory (Join-Path $Root $dir) `
        -ArgumentList '-NoExit', '-Command', "`$Host.UI.RawUI.WindowTitle='RMM $name'; $cmd"
    Write-Host "Started $name"
}

function Ensure-Deps {
    # Try to start Postgres / Redis(Memurai) Windows services if their ports are closed.
    $missing = @()
    foreach ($d in @(@{P=5432;N='postgresql*'}, @{P=6379;N='Memurai*','Redis*'})) {
        if (Test-Port $d.P) { continue }
        $svc = Get-Service -Name $d.N -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($svc) { try { Start-Service $svc.Name -ErrorAction Stop; Start-Sleep 3 } catch {} }
        if (-not (Test-Port $d.P)) { $missing += $(if ($svc) { $svc.Name } else { "(no service for port $($d.P))" }) }
    }
    if ($missing) {
        Write-Warning "Dependencies not running. Run this in an ELEVATED PowerShell, then retry:"
        $missing | ForEach-Object { if ($_ -notlike '(no*') { Write-Host "  Start-Service '$_'" } else { Write-Host "  $_" } }
    }
}

function Start-All {
    Ensure-Deps
    Start-Svc 'API'       'api'       '.\venv\Scripts\python.exe app.py'
    # `python -m ...` instead of the venv's *.exe launchers: Windows Application Control blocks
    # freshly generated (unsigned) launcher exes, e.g. after a pip reinstall.
    Start-Svc 'Worker'    'api'       '.\venv\Scripts\python.exe -m celery -A tasks.celery_app worker --pool=solo -l info'
    Start-Svc 'Beat'      'api'       '.\venv\Scripts\python.exe -m celery -A tasks.celery_app beat -l info --pidfile=celerybeat.pid'
    Start-Svc 'Dashboard' 'dashboard' '.\venv\Scripts\python.exe -m streamlit run app.py'
    if ($Frontend) { Start-Svc 'React' 'frontend' 'npm run dev' }
    if (-not $NoAgent) { Start-Svc 'Agent' 'agent'    '.\venv\Scripts\python.exe rmm_agent.py' }

    Write-Host 'Waiting for API health...'
    for ($i = 0; $i -lt 60; $i++) {
        $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 3 http://localhost:5000/api/health
        if ($code -eq '200') { Write-Host "API health: HTTP $code"; return }
        Start-Sleep 1
    }
    Write-Warning 'API did not answer /api/health within 60s - check the "RMM API" window.'
}

function Show-Status {
    $Ports.GetEnumerator() | ForEach-Object { '{0,-10} :{1}  {2}' -f $_.Key, $_.Value, $(if (Test-Port $_.Value) {'UP'} else {'down'}) }
    $c = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'celery' })
    "Celery procs: $($c.Count)"
    foreach ($u in @{API='http://localhost:5000/api/health'; Dashboard='http://localhost:8501'}.GetEnumerator()) {
        $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 3 $u.Value
        if ($code -eq '000') { $code = 'unreachable' }
        '{0,-10} HTTP {1}' -f $u.Key, $code
    }
}

function Run-Tests {
    Push-Location (Join-Path $Root 'api');       & .\venv\Scripts\python.exe -m pytest tests -q; Pop-Location
    Push-Location (Join-Path $Root 'dashboard'); & .\venv\Scripts\python.exe -m pytest -q;       Pop-Location
    Push-Location (Join-Path $Root 'agent');     & .\venv\Scripts\python.exe -m pytest -q;       Pop-Location
}

switch ($Action) {
    'start'   { Start-All }
    'stop'    { Stop-All }
    'restart' { Stop-All; Start-Sleep 2; Start-All }
    'status'  { Show-Status }
    'test'    { Run-Tests }
}
