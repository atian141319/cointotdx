@echo off
cd /d "%~dp0"
python -B multi.py restore
if errorlevel 1 goto end
:end
pause
