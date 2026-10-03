@echo off
setlocal
rem Source-development adapter. Opens only an authenticated, verified READY host.
if not exist "%~dp0.venv\Scripts\python.exe" goto missing
"%~dp0.venv\Scripts\python.exe" -I "%~dp0tools\source_launcher.py" run
exit /b %errorlevel%
:missing
echo Run soma_setup.bat to prepare the source environment. 1>&2
exit /b 10
