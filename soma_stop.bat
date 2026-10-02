@echo off
setlocal
rem Source-development adapter. No PID/port/process-name termination authority.
if not exist "%~dp0.venv\Scripts\python.exe" goto missing
"%~dp0.venv\Scripts\python.exe" -I "%~dp0tools\source_launcher.py" stop
exit /b %errorlevel%
:missing
echo Run soma_setup.bat to prepare the source environment. 1>&2
exit /b 10
