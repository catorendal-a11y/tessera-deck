@echo off
rem Tessera launcher. With no arguments it starts everything: the tray icon, the USB host
rem and the editor window. Starting it again only brings up the existing editor window.
rem   --setup        first-run setup (dependencies and a Desktop shortcut)
rem   --uninstall    remove the autostart entry and the shortcut (add --purge to delete your data too)
rem   --diagnostics  write a support bundle without button contents
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist "host\.venv\Scripts\python.exe" (
  echo Setting up Tessera. The first start takes about a minute.
  call :create_environment
  if errorlevel 1 goto failed
  set FIRST_RUN=1
)
if "%~1"=="--uninstall" goto uninstall
"host\.venv\Scripts\python.exe" "host\setup_tool.py" ensure
if errorlevel 1 goto failed
if defined FIRST_RUN "host\.venv\Scripts\python.exe" "host\setup_tool.py" setup >nul
if "%~1"=="" goto app
if "%~1"=="--app" goto app
if "%~1"=="--setup" goto setup
if "%~1"=="--diagnostics" goto diagnostics
if "%~1"=="--terminal" goto terminal
if "%~1"=="--tray" goto tray
if "%~1"=="--sensors" goto sensors
if "%~1"=="--sensors-off" goto sensorsoff
if "%~1"=="--check" goto console
if "%~1"=="--no-browser" goto console
start "" /b "host\.venv\Scripts\pythonw.exe" "host\tessera_app.py" %*
exit /b 0
:app
start "" /b "host\.venv\Scripts\pythonw.exe" "host\tessera_tray.py"
start "" /b "host\.venv\Scripts\pythonw.exe" "host\tessera_app.py" --editor
exit /b 0
:sensors
rem Bypass for Tessera's own script only: Windows marks files from a downloaded zip, and RemoteSigned refuses them
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "tools\enable_sensors.ps1"
exit /b 0
:sensorsoff
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "tools\enable_sensors.ps1" -Remove
exit /b 0
:tray
start "" /b "host\.venv\Scripts\pythonw.exe" "host\tessera_tray.py"
exit /b 0
:setup
"host\.venv\Scripts\python.exe" "host\setup_tool.py" setup
if errorlevel 1 goto failed
pause
exit /b 0
:uninstall
"host\.venv\Scripts\python.exe" "host\setup_tool.py" uninstall %2
pause
exit /b 0
:diagnostics
"host\.venv\Scripts\python.exe" "host\setup_tool.py" diagnostics
pause
exit /b 0
:terminal
"host\.venv\Scripts\python.exe" "host\tessera_terminal.py"
if errorlevel 1 goto failed
exit /b 0
:console
"host\.venv\Scripts\python.exe" "host\tessera_app.py" %*
if errorlevel 1 goto failed
exit /b 0
:create_environment
set "PYTHON="
py -3 --version >nul 2>nul && set "PYTHON=py -3"
if not defined PYTHON python -c "" >nul 2>nul && set "PYTHON=python"
if not defined PYTHON call :install_python
if not defined PYTHON exit /b 1
%PYTHON% -m venv "host\.venv"
exit /b %errorlevel%
:install_python
echo Python is not installed. Installing it for this user with winget ...
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PYTHON="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYTHON echo Install Python 3.11 or newer from https://www.python.org/downloads/ and start Tessera again.
exit /b 0
:failed
echo Tessera could not start. See the error above.
pause
exit /b 1
