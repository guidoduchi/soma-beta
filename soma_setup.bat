@echo off
setlocal
rem Source-development setup only. This is not the production installer.
py -3.14 -I -c "import sys" >nul 2>&1
if not errorlevel 1 goto python314
py -3.13 -I -c "import sys" >nul 2>&1
if not errorlevel 1 goto python313
echo Source setup requires Python 3.13 or 3.14 and the Windows py launcher. 1>&2
exit /b 10
:python314
py -3.14 -I "%~dp0tools\source_launcher.py" setup
exit /b %errorlevel%
:python313
py -3.13 -I "%~dp0tools\source_launcher.py" setup
exit /b %errorlevel%
