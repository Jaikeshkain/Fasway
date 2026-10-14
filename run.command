#!/bin/bash
# Fasway for macOS. Double-click in Finder, or run:  bash run.command
cd "$(dirname "$0")" || exit 1

find_python() {
  for p in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$p" >/dev/null 2>&1 &&
       "$p" -c 'import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      echo "$p"; return 0
    fi
  done
  return 1
}

fail() {
  echo; echo "$1"; read -r -p "Press Enter to close..."; exit 1
}

if [ ! -x .venv-mac/bin/python ]; then
  PY=$(find_python) || fail "Need Python 3.10+ with Tk. Install it from https://www.python.org/downloads/macos/ and run again."
  echo "First run: setting up with $PY (takes a minute)..."
  "$PY" -m venv .venv-mac &&
    .venv-mac/bin/python -m pip install -q --upgrade pip &&
    .venv-mac/bin/python -m pip install -q -r requirements.txt ||
    { rm -rf .venv-mac; fail "Setup failed - check your internet connection and try again."; }
fi
# quick no-op when up to date; picks up new requirements after updates
.venv-mac/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt ||
  fail "Installing updates failed - check your internet connection and try again."

exec .venv-mac/bin/python -m fasway
