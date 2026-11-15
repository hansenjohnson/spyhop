@echo off
rem Starts Spyhop in this window (close the window or press Ctrl+C to stop it).
rem The first time, it also sets up Python (needs internet) and adds a Spyhop icon
rem to the Desktop and the Start menu. After that you can start Spyhop from the icon.
cd /d "%~dp0"
rem the Python versions Spyhop is tested with, released ones only (also in pyproject.toml, spyhop/__main__.py and the other start files)
set "PY_OK=import sys; v = sys.version_info; sys.exit(0 if (3, 10) <= v[:2] <= (3, 15) and v.releaselevel == 'final' else 1)"
if not exist ".venv\Scripts\python.exe" (
  echo Setting up Spyhop for the first time - this needs internet and takes a minute...
  call :pick_python
  if not defined PYCMD (
    echo Spyhop needs Python 3.10 to 3.15 ^(3.13 is a good choice^), and none was found.
    echo Install Python 3.13 from https://www.python.org/downloads/ and open this file again.
    pause
    exit /b 1
  )
  call :make_venv
  if errorlevel 1 (
    echo Setup failed - see the messages above.
    if exist ".venv" rmdir /s /q ".venv"
    pause
    exit /b 1
  )
  copy /y requirements.lock ".venv\requirements.installed" >nul
)
".venv\Scripts\python.exe" -c "%PY_OK%" >nul 2>&1
if errorlevel 1 echo Warning: Spyhop was set up with a Python it isn't tested with. If it misbehaves, delete the .venv folder here and open this file again.
rem a newer Spyhop may need other versions of its Python packages: install them once (needs internet)
fc /b requirements.lock ".venv\requirements.installed" >nul 2>&1
if errorlevel 1 (
  echo Installing the Python packages this version of Spyhop needs...
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.lock
  if errorlevel 1 (
    echo Couldn't install them - no internet? Spyhop starts without them and tries again next time.
  ) else (
    copy /y requirements.lock ".venv\requirements.installed" >nul
  )
)
".venv\Scripts\python.exe" -m spyhop --install-shortcut --if-needed
".venv\Scripts\python.exe" -m spyhop %*
if errorlevel 1 pause
exit /b

:pick_python
rem the newest supported Python: the py launcher first, then python on the PATH
set "PYCMD="
for %%V in (3.15 3.14 3.13 3.12 3.11 3.10) do (
  if not defined PYCMD (
    py -%%V -c "%PY_OK%" >nul 2>&1 && set "PYCMD=py -%%V"
  )
)
if not defined PYCMD (
  python -c "%PY_OK%" >nul 2>&1 && set "PYCMD=python"
)
exit /b 0

:make_venv
echo Using %PYCMD%
%PYCMD% -m venv .venv || exit /b 1
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.lock || exit /b 1
exit /b 0
