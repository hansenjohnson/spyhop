#!/bin/bash
# Start Spyhop on Linux. First run creates .venv (needs internet once) and adds Spyhop to the applications menu.
cd "$(dirname "$0")" || exit 1
# the Python versions Spyhop is tested with, released ones only (also in pyproject.toml, spyhop/__main__.py and the other start files)
PY_OK='import sys; v = sys.version_info; sys.exit(0 if (3, 10) <= v[:2] <= (3, 15) and v.releaselevel == "final" else 1)'
pick_python() {
  for c in python3.15 python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    p=$(command -v "$c" 2>/dev/null) || continue
    "$p" -c "$PY_OK" 2>/dev/null && { echo "$p"; return 0; }
  done
  return 1
}
if [ ! -x .venv/bin/python ]; then
  PY=$(pick_python) || { echo "Spyhop needs Python 3.10 to 3.15 (and the venv module, e.g. python3-venv); none was found."; exit 1; }
  echo "Setting up Spyhop with $("$PY" -V 2>&1) ($PY)..."
  "$PY" -m venv .venv && .venv/bin/python -m pip install -r requirements.lock || { rm -rf .venv; exit 1; }
  cp requirements.lock .venv/requirements.installed
fi
.venv/bin/python -c "$PY_OK" 2>/dev/null || echo "Warning: Spyhop was set up with $(.venv/bin/python -V 2>&1), which it isn't tested with. If it misbehaves, delete .venv and start again."
if ! cmp -s requirements.lock .venv/requirements.installed; then
  echo "Installing the Python packages this version of Spyhop needs..."
  .venv/bin/python -m pip install -q -r requirements.lock && cp requirements.lock .venv/requirements.installed \
    || echo "Couldn't install them (no internet?). Spyhop starts without them and tries again next time."
fi
.venv/bin/python -m spyhop --install-shortcut --if-needed
exec .venv/bin/python -m spyhop "$@"
