@echo off
rem Keep tonight's tickets from SambaPOS before the reset deletes them.
rem Double-click this just before running the reset.
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py -3
%PY% twilight.py pos save
echo.
pause
