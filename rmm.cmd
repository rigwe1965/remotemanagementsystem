@echo off
rem Double-click launcher. Usage: rmm.cmd [start|stop|restart|status|test]
set ACTION=%1
if "%ACTION%"=="" set ACTION=start
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0rmm.ps1" %ACTION% %2 %3
if "%1"=="" pause
