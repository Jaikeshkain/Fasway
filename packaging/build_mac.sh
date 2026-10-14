#!/bin/bash
# Builds dist/Fasway.app and dist/Fasway-mac-<arch>.dmg. Must run ON a Mac (GitHub Actions does this for you).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

python3 -m pip install -q -r requirements.txt pyinstaller
python3 packaging/make_icon.py

# absolute paths: PyInstaller resolves relative ones against --specpath
python3 -m PyInstaller --noconfirm --clean --windowed \
  --name Fasway \
  --icon "$ROOT/packaging/build/Fasway.icns" \
  --osx-bundle-identifier com.fasway.app \
  --add-data "$ROOT/web:web" \
  --paths "$ROOT" \
  --distpath dist --workpath packaging/build/pyi --specpath packaging/build \
  packaging/fasway_app.py

ARCH=$(uname -m)   # arm64 (Apple Silicon) or x86_64 (Intel)
STAGE=packaging/build/dmg
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R dist/Fasway.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"      # drag-to-install layout
hdiutil create -volname Fasway -srcfolder "$STAGE" -ov -format UDZO "dist/Fasway-mac-$ARCH.dmg"
echo "Built dist/Fasway-mac-$ARCH.dmg"
