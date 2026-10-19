@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist "host\.venv\Scripts\python.exe" (
  py -3 -m venv "host\.venv"
  if errorlevel 1 goto failed
)
"host\.venv\Scripts\python.exe" -c "import textual,serial,psutil,cryptography,lz4,esptool,PIL,webview" >nul 2>&1
if errorlevel 1 (
  "host\.venv\Scripts\python.exe" -m pip install -r "host\requirements.txt"
  if errorlevel 1 goto failed
)
if "%~1"=="" goto terminal
if "%~1"=="--terminal" goto terminal
if "%~1"=="--check" goto console
if "%~1"=="--no-browser" goto console
start "" /b "host\.venv\Scripts\pythonw.exe" "host\agent_deck_app.py" %*
exit /b 0
:terminal
"host\.venv\Scripts\python.exe" "host\agent_deck_terminal.py"
if errorlevel 1 goto failed
exit /b 0
:console
"host\.venv\Scripts\python.exe" "host\agent_deck_app.py" %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo Agent Deck kunne ikke starte. Se feilmeldingen over.
pause
exit /b 1
