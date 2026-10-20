@echo off
rem Tessera launcher. With no arguments it starts everything: the tray icon, the USB host
rem and the editor window. Starting it again only brings up the existing editor window.
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist "host\.venv\Scripts\python.exe" (
  py -3 -m venv "host\.venv"
  if errorlevel 1 goto failed
)
"host\.venv\Scripts\python.exe" -c "import textual,serial,psutil,cryptography,lz4,esptool,PIL,webview,win32pdh,pystray" >nul 2>&1
if errorlevel 1 (
  "host\.venv\Scripts\python.exe" -m pip install -r "host\requirements.txt"
  if errorlevel 1 goto failed
)
if "%~1"=="" goto app
if "%~1"=="--app" goto app
if "%~1"=="--terminal" goto terminal
if "%~1"=="--tray" goto tray
if "%~1"=="--check" goto console
if "%~1"=="--no-browser" goto console
start "" /b "host\.venv\Scripts\pythonw.exe" "host\tessera_app.py" %*
exit /b 0
:app
start "" /b "host\.venv\Scripts\pythonw.exe" "host\tessera_tray.py"
start "" /b "host\.venv\Scripts\pythonw.exe" "host\tessera_app.py" --editor
exit /b 0
:tray
start "" /b "host\.venv\Scripts\pythonw.exe" "host\tessera_tray.py"
exit /b 0
:terminal
"host\.venv\Scripts\python.exe" "host\tessera_terminal.py"
if errorlevel 1 goto failed
exit /b 0
:console
"host\.venv\Scripts\python.exe" "host\tessera_app.py" %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo Tessera could not start. See the error above.
pause
exit /b 1
