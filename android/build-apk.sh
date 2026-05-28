#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK=${ANDROID_HOME:-/opt/android-sdk}
PLATFORM=$SDK/platforms/android-34/android.jar
BUILD_TOOLS=$SDK/build-tools/36.0.0
OUT=$ROOT/build
PKG=ru.banzai.dictaphone

rm -rf "$OUT/classes" "$OUT/dex" "$OUT/compiled" "$OUT/app-unsigned.apk" "$OUT/app-aligned.apk"
mkdir -p "$OUT/classes" "$OUT/dex" "$OUT/compiled"

"$BUILD_TOOLS/aapt2" compile --dir "$ROOT/res" -o "$OUT/compiled/resources.zip"
"$BUILD_TOOLS/aapt2" link \
  -I "$PLATFORM" \
  --manifest "$ROOT/AndroidManifest.xml" \
  -o "$OUT/app-unsigned.apk" \
  "$OUT/compiled/resources.zip"

javac \
  -g:none \
  -encoding UTF-8 \
  -source 8 \
  -target 8 \
  -bootclasspath "$PLATFORM" \
  -d "$OUT/classes" \
  $(find "$ROOT/src" -name '*.java' | sort)

"$BUILD_TOOLS/d8" \
  --lib "$PLATFORM" \
  --output "$OUT/dex" \
  $(find "$OUT/classes" -name '*.class' | sort)

cd "$OUT/dex"
zip -q "$OUT/app-unsigned.apk" classes.dex

if [ ! -f "$OUT/debug.keystore" ]; then
  keytool -genkeypair \
    -keystore "$OUT/debug.keystore" \
    -storepass android \
    -keypass android \
    -alias androiddebugkey \
    -keyalg RSA \
    -keysize 2048 \
    -validity 10000 \
    -dname "CN=Banzai Dictaphone,O=Banzai,C=RU" >/dev/null
fi

"$BUILD_TOOLS/zipalign" -f 4 "$OUT/app-unsigned.apk" "$OUT/app-aligned.apk"
"$BUILD_TOOLS/apksigner" sign \
  --ks "$OUT/debug.keystore" \
  --ks-pass pass:android \
  --key-pass pass:android \
  --out "$ROOT/banzai-dictaphone.apk" \
  "$OUT/app-aligned.apk"

"$BUILD_TOOLS/apksigner" verify --verbose "$ROOT/banzai-dictaphone.apk"
ls -lh "$ROOT/banzai-dictaphone.apk"
