#!/bin/bash
# Build "DFX Agent Enhancer.app" and dist/DFX-Agent-Enhancer.dmg from clean.
#
#   scripts/build_release.sh
#
# Uses the python.org Python (universal2) so the app runs on Apple silicon and Intel. Another
# Python works through PYTHON=..., but the app then has only that Python's architecture.
# The app is ad-hoc signed, not notarized (no Developer ID here).
set -euo pipefail

SRC=$(cd "$(dirname "$0")/.." && pwd)
# Build from a copy in a fixed neutral folder, so the bundle's .pyc files and Info.plist carry
# that path instead of this checkout's (which shows the username). Outputs are copied back.
ROOT=/private/tmp/dfx-agent-enhancer-build
PYTHON=${PYTHON:-/Library/Frameworks/Python.framework/Versions/3.14/bin/python3}
NAME="DFX Agent Enhancer"
BUILD=$ROOT/build
DIST=$ROOT/dist
APP="$BUILD/dist/$NAME.app"
DMG=$DIST/DFX-Agent-Enhancer.dmg

[ -x "$PYTHON" ] || { echo "no Python at $PYTHON (install it from python.org, or set PYTHON=)" >&2; exit 1; }
archs=$(lipo -archs "$("$PYTHON" -c 'import sys; print(sys.executable)')")
[ "$archs" = "x86_64 arm64" ] || echo "warning: $PYTHON is $archs, not universal2; the app will be $archs only" >&2

rm -rf /private/tmp/dfx-agent-enhancer-build
mkdir -p "$ROOT"
rsync -a --exclude __pycache__ "$SRC/src" "$SRC/scripts" "$SRC/tools" "$ROOT/"
mkdir -p "$BUILD" "$DIST"

echo "== build venv"
"$PYTHON" -m venv "$BUILD/venv"
"$BUILD/venv/bin/pip" install -q --disable-pip-version-check -r "$ROOT/scripts/build-requirements.txt"

echo "== icon"
"$BUILD/venv/bin/python" "$ROOT/tools/make_icon.py" "$BUILD/AppIcon.icns"

echo "== py2app (log: $BUILD/py2app.log)"
# run from build/ so setuptools does not read pyproject.toml
(cd "$BUILD" && DFX_ICON="$BUILD/AppIcon.icns" venv/bin/python "$ROOT/scripts/py2app_setup.py" py2app \
    --dist-dir "$BUILD/dist" > py2app.log 2>&1) || { tail -30 "$BUILD/py2app.log"; exit 1; }

echo "== ad-hoc sign"
# py2app strips the binaries after they were signed, and on Apple silicon a library with a broken
# signature is killed on load: sign every Mach-O file, then the bundle
find "$APP" -type f \( -name '*.so' -o -name '*.dylib' -o -perm -u+x \) -print0 |
while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q Mach-O; then codesign -f -s - "$f" 2>/dev/null; fi
done
codesign --force --deep -s - "$APP"
codesign --verify --deep --strict "$APP"

echo "== dmg"
STAGE=$BUILD/dmg
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/$NAME.app"
ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "$NAME" -srcfolder "$STAGE" -fs HFS+ -format UDRW -ov "$BUILD/rw.dmg"
# icon view with the app and Applications side by side; needs Finder, skipped if it fails
MNT=$(hdiutil attach -noautoopen "$BUILD/rw.dmg" | awk -F'\t' '/\/Volumes\//{print $NF}')
osascript - "$(basename "$MNT")" "$NAME" <<'EOF' || echo "warning: Finder layout skipped" >&2
on run argv
  tell application "Finder"
    tell disk (item 1 of argv)
      open
      set w to container window
      set current view of w to icon view
      set toolbar visible of w to false
      set statusbar visible of w to false
      set bounds of w to {200, 120, 740, 460}
      set o to icon view options of w
      set arrangement of o to not arranged
      set icon size of o to 128
      set position of item ((item 2 of argv) & ".app") to {140, 150}
      set position of item "Applications" to {400, 150}
      update without registering applications
      delay 1
      close
    end tell
  end tell
end run
EOF
rm -rf "$MNT/.fseventsd"
hdiutil detach -quiet "$MNT"
hdiutil convert -quiet "$BUILD/rw.dmg" -format UDZO -imagekey zlib-level=9 -o "$DMG"
rm "$BUILD/rw.dmg"

rm -rf "$SRC/build" "$SRC/dist"
mkdir -p "$SRC/build/dist" "$SRC/dist"
ditto "$APP" "$SRC/build/dist/$NAME.app"
cp "$DMG" "$SRC/dist/"
cp "$BUILD/py2app.log" "$SRC/build/"
APP="$SRC/build/dist/$NAME.app"
DMG="$SRC/dist/DFX-Agent-Enhancer.dmg"

echo
echo "app: $APP ($(du -sh "$APP" | cut -f1), $(lipo -archs "$APP/Contents/MacOS/$NAME"))"
echo "dmg: $DMG ($(du -h "$DMG" | cut -f1))"
