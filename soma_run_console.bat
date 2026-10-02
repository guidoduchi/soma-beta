@echo off
setlocal
rem Foreground source adapter. Trusted host composition is dependency-pending.
if not exist "%~dp0.venv\Scripts\python.exe" goto missing
"%~dp0.venv\Scripts\python.exe" -I "%~dp0tools\source_launcher.py" console
exit /b %errorlevel%
:missing
echo Run soma_setup.bat to prepare the source environment. 1>&2
exit /b 10
