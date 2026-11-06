#!/bin/bash
# Start Spyhop on Linux. First run creates .venv (needs internet once) and adds Spyhop to the applications menu.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt || exit 1
  cp requirements.txt .venv/requirements.installed
fi
if ! cmp -s requirements.txt .venv/requirements.installed; then
  echo "Installing the Python packages this version of Spyhop needs..."
  .venv/bin/python -m pip install -q -r requirements.txt && cp requirements.txt .venv/requirements.installed \
    || echo "Couldn't install them (no internet?). Spyhop starts without them and tries again next time."
fi
.venv/bin/python -m spyhop --install-shortcut --if-needed
exec .venv/bin/python -m spyhop "$@"
