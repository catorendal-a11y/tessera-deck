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
  py -3 -m venv "host\.venv"
  if errorlevel 1 goto failed
)
if "%~1"=="--uninstall" goto uninstall
"host\.venv\Scripts\python.exe" "host\setup_tool.py" ensure
if errorlevel 1 goto failed
if "%~1"=="" goto app
if "%~1"=="--app" goto app
if "%~1"=="--setup" goto setup
if "%~1"=="--diagnostics" goto diagnostics
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
:failed
echo Tessera could not start. See the error above.
pause
exit /b 1
