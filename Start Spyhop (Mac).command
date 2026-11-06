#!/bin/bash
# Starts Spyhop in this Terminal window (close the window or press Ctrl+C to stop it).
# The first time, it also sets up Python (needs internet) and adds a Spyhop icon to
# Applications and the Desktop. After that you can start Spyhop from the icon.
cd "$(dirname "$0")" || exit 1
# you have approved this file, so stop macOS asking about the rest of the folder
xattr -dr com.apple.quarantine . 2>/dev/null
if [ ! -x .venv/bin/python ]; then
  echo "Setting up Spyhop for the first time - this needs internet and takes a minute..."
  python3 -m venv .venv || { echo "Python 3.10 or newer is needed: https://www.python.org/downloads/"; read -r; exit 1; }
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt || { echo "Setup failed - see the messages above."; read -r; exit 1; }
  cp requirements.txt .venv/requirements.installed
fi
# a newer Spyhop may need more Python packages: install them once (needs internet)
if ! cmp -s requirements.txt .venv/requirements.installed; then
  echo "Installing the Python packages this version of Spyhop needs..."
  if .venv/bin/python -m pip install -q -r requirements.txt; then cp requirements.txt .venv/requirements.installed
  else echo "Couldn't install them (no internet?). Spyhop starts without them and tries again next time."; fi
fi
# make (or update) the Spyhop icon if it is missing or points at another folder
.venv/bin/python -m spyhop --install-shortcut --if-needed
exec .venv/bin/python -m spyhop "$@"
