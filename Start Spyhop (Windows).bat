@echo off
rem Starts Spyhop in this window (close the window or press Ctrl+C to stop it).
rem The first time, it also sets up Python (needs internet) and adds a Spyhop icon
rem to the Desktop and the Start menu. After that you can start Spyhop from the icon.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Setting up Spyhop for the first time - this needs internet and takes a minute...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 (
    echo Python 3.10 or newer is needed: https://www.python.org/downloads/
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Setup failed - see the messages above.
    pause
    exit /b 1
  )
  copy /y requirements.txt ".venv\requirements.installed" >nul
)
rem a newer Spyhop may need more Python packages: install them once (needs internet)
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1
if errorlevel 1 (
  echo Installing the Python packages this version of Spyhop needs...
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
  if errorlevel 1 (
    echo Couldn't install them - no internet? Spyhop starts without them and tries again next time.
  ) else (
    copy /y requirements.txt ".venv\requirements.installed" >nul
  )
)
".venv\Scripts\python.exe" -m spyhop --install-shortcut --if-needed
".venv\Scripts\python.exe" -m spyhop %*
if errorlevel 1 pause
