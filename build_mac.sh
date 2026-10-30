#!/usr/bin/env bash
# Builds ms-overlay-mac.zip: ms-overlay.app with a bundled, relocatable Tesseract.
# Run on macOS. Needs Python 3.10+ and Homebrew (Tesseract and dylibbundler are installed with it).
# The app is ad-hoc signed only (no Apple Developer ID), so Gatekeeper asks before the first launch.
set -euo pipefail
cd "$(dirname "$0")"

BUILD="$PWD/build"
TESS="$BUILD/tesseract"
APP="$BUILD/dist/ms-overlay.app"
ZIP="$PWD/ms-overlay-mac.zip"
PYTHON="${PYTHON:-python3}"

command -v brew >/dev/null || { echo "Homebrew not found." >&2; exit 1; }
mkdir -p "$BUILD"

echo "==> Installing Python dependencies"
"$PYTHON" -m pip install -r requirements.txt

echo "==> Installing Tesseract and dylibbundler (Homebrew)"
brew list tesseract >/dev/null 2>&1 || brew install tesseract
brew list dylibbundler >/dev/null 2>&1 || brew install dylibbundler

echo "==> Making a relocatable copy of Tesseract"
rm -rf "$TESS"; mkdir -p "$TESS"
cp -L "$(brew --prefix)/bin/tesseract" "$TESS/tesseract"
chmod u+w "$TESS/tesseract"
# copy every non-system library it needs into libs/ and point the binary at them
dylibbundler -od -b -cd -x "$TESS/tesseract" -d "$TESS/libs" -p @executable_path/libs/ \
    -s "$(brew --prefix)/lib"     # where to look for @rpath libraries (it would otherwise prompt)
# language data: English + orientation only, plus the config files pytesseract relies on
cp -RL "$(brew --prefix tesseract)/share/tessdata" "$TESS/tessdata"
find "$TESS/tessdata" -name "*.traineddata" ! -name eng.traineddata ! -name osd.traineddata -delete
[ -f "$TESS/tessdata/eng.traineddata" ] || { echo "No eng.traineddata." >&2; exit 1; }
# rewritten binaries lose their signature; Apple Silicon refuses to run unsigned code
codesign --force --sign - "$TESS"/libs/*.dylib "$TESS/tesseract"
if otool -L "$TESS/tesseract" "$TESS"/libs/*.dylib | grep -E "/(opt/homebrew|usr/local)/"; then
    echo "Tesseract still links to Homebrew libraries (listed above)." >&2; exit 1
fi
TESSDATA_PREFIX="$TESS/tessdata" "$TESS/tesseract" --list-langs

echo "==> Building app with PyInstaller"
rm -rf "$BUILD/dist"
"$PYTHON" -m PyInstaller --windowed --noconfirm --name ms-overlay \
    --osx-bundle-identifier io.github.chrisks.ms-overlay \
    --distpath "$BUILD/dist" --workpath "$BUILD/pyi" --specpath "$BUILD" ms_overlay.py
[ -d "$APP" ] || { echo "PyInstaller build failed." >&2; exit 1; }

echo "==> Adding Tesseract to the app"
cp -R "$TESS" "$APP/Contents/Resources/tesseract"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

echo "==> Zipping"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"     # ditto keeps the app's symlinks intact

echo ""
echo "Done: $ZIP"
