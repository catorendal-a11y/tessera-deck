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
  echo 1/3 Finding Python ...
  call :create_environment
  if errorlevel 1 goto failed
  set FIRST_RUN=1
)
if "%~1"=="--uninstall" goto uninstall
if defined FIRST_RUN echo 2/3 Installing packages ...
"host\.venv\Scripts\python.exe" "host\setup_tool.py" ensure
if errorlevel 1 goto failed
if defined FIRST_RUN "host\.venv\Scripts\python.exe" "host\setup_tool.py" setup >nul
if defined FIRST_RUN echo 3/3 Starting Tessera. Look for the editor window and the tray icon.
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
rem Python 3.11 or newer (README); an older one is skipped, and winget installs 3.12 when none fits
set "PYTHON="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PYTHON=py -3"
if not defined PYTHON python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PYTHON=python"
if not defined PYTHON python -c "" >nul 2>nul && echo The Python on this PC is older than 3.11, which Tessera needs.
if not defined PYTHON call :install_python
if not defined PYTHON exit /b 1
%PYTHON% -m venv "host\.venv"
if errorlevel 1 echo Python could not create host\.venv. Delete that folder if it is there and start Tessera again.
exit /b %errorlevel%
:install_python
echo Installing Python 3.12 for this user with winget ...
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PYTHON="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYTHON echo Python 3.11 or newer could not be installed. Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH") and start Tessera again.
exit /b 0
:failed
echo Tessera could not start. See the error above.
pause
exit /b 1
