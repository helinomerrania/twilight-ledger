@echo off
rem Starts Twilight Ledger. After an update the app asks to be started again
rem (exit code 3), and this loop does it, so the update finishes by itself.
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py -3
:start
%PY% twilight.py
if %errorlevel%==3 (
  set TWILIGHT_RESTARTED=1
  goto start
)
if errorlevel 1 pause
