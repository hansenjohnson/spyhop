#!/bin/bash
# Starts Spyhop in this Terminal window (close the window or press Ctrl+C to stop it).
# The first time, it also sets up Python (needs internet) and adds a Spyhop icon to
# Applications and the Desktop. After that you can start Spyhop from the icon.
cd "$(dirname "$0")" || exit 1
# you have approved this file, so stop macOS asking about the rest of the folder
xattr -dr com.apple.quarantine . 2>/dev/null
# the Python versions Spyhop is tested with, released ones only (also in pyproject.toml, spyhop/__main__.py and the other start files)
PY_OK='import sys; v = sys.version_info; sys.exit(0 if (3, 10) <= v[:2] <= (3, 15) and v.releaselevel == "final" else 1)'
pick_python() {   # the newest supported Python on this Mac
  for c in python3.15 python3.14 python3.13 python3.12 python3.11 python3.10 \
           /Library/Frameworks/Python.framework/Versions/3.1{5,4,3,2,1,0}/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    p=$(command -v "$c" 2>/dev/null) || continue
    "$p" -c "$PY_OK" 2>/dev/null && { echo "$p"; return 0; }
  done
  return 1
}
if [ ! -x .venv/bin/python ]; then
  echo "Setting up Spyhop for the first time - this needs internet and takes a minute..."
  PY=$(pick_python) || {
    echo "Spyhop needs Python 3.10 to 3.15 (3.13 is a good choice), and none was found."
    command -v python3 >/dev/null && echo "This Mac has $(python3 -V 2>&1), which Spyhop doesn't support yet."
    echo "Install Python 3.13 from https://www.python.org/downloads/ and open this file again."
    read -r; exit 1; }
  echo "Using $("$PY" -V 2>&1) ($PY)"
  "$PY" -m venv .venv || { echo "Couldn't set up Python - see the messages above."; read -r; exit 1; }
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.lock || { rm -rf .venv; echo "Setup failed - see the messages above."; read -r; exit 1; }
  cp requirements.lock .venv/requirements.installed
fi
.venv/bin/python -c "$PY_OK" 2>/dev/null || echo "Warning: Spyhop was set up with $(.venv/bin/python -V 2>&1), which it isn't tested with. If it misbehaves, delete the .venv folder here and open this file again."
# a newer Spyhop may need other versions of its Python packages: install them once (needs internet)
if ! cmp -s requirements.lock .venv/requirements.installed; then
  echo "Installing the Python packages this version of Spyhop needs..."
  if .venv/bin/python -m pip install -q -r requirements.lock; then cp requirements.lock .venv/requirements.installed
  else echo "Couldn't install them (no internet?). Spyhop starts without them and tries again next time."; fi
fi
# make (or update) the Spyhop icon if it is missing or points at another folder
.venv/bin/python -m spyhop --install-shortcut --if-needed
exec .venv/bin/python -m spyhop "$@"
