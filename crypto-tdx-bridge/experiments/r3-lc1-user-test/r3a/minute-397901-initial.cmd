@echo off
cd /d "%~dp0"
python -B external_minute.py initial
if errorlevel 1 goto end
start "" /D "%~dp0..\client" "%~dp0..\client\tdxw.exe"
:end
pause
