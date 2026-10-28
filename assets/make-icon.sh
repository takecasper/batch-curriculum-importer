#!/usr/bin/env bash
# Rebuild the app icon from icon.svg with macOS built-ins (qlmanage, sips,
# iconutil). Run after editing the SVG and commit the resulting .icns.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
OUT="../One45 Schedule Wrangler.app/Contents/Resources/AppIcon.icns"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

qlmanage -t -s 1024 -o "$WORK" icon.svg >/dev/null 2>&1
mv "$WORK/icon.svg.png" "$WORK/1024.png"

mkdir "$WORK/AppIcon.iconset"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$WORK/1024.png" --out "$WORK/AppIcon.iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$WORK/1024.png" --out "$WORK/AppIcon.iconset/icon_${size}x${size}@2x.png" >/dev/null
done

mkdir -p "$(dirname "$OUT")"
iconutil -c icns "$WORK/AppIcon.iconset" -o "$OUT"
echo "Wrote $OUT"
