#!/usr/bin/env bash
# Assemble the shareable app: the committed bundle plus the files it runs,
# copied into Contents/Resources, then zipped. Output goes to dist/ (or $DIST).
# A zip of the bare checkout is not enough: Gatekeeper runs a downloaded app
# from a read-only copy of the .app alone, so everything must be inside it.
# Release: attach the zip to the GitHub Release (gh release upload <tag> <zip>).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
APP="One45 Schedule Wrangler.app"
DIST="${DIST:-dist}"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"
if [[ -z "$VERSION" || "$VERSION" == *$'\n'* ]]; then
  echo "Could not read one version from pyproject.toml" >&2
  exit 1
fi
ZIP="$DIST/One45-Schedule-Wrangler-$VERSION.zip"

if [[ -e .git ]] && [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
  echo "Warning: the checkout has uncommitted changes; the zip will not match a tag." >&2
fi

BUILT_APP="${DIST:?}/${APP:?}"
rm -rf "$BUILT_APP" "$ZIP"
mkdir -p "$DIST"
cp -R "$APP" "$DIST/"
cp wrangler.py wrangler_gui.py setup-venv.sh requirements.txt "$BUILT_APP/Contents/Resources/"
find "$BUILT_APP" -name .DS_Store -delete
# Anyone on the Mac can read the app, whatever the modes in this checkout.
chmod -R u+rwX,go+rX "$BUILT_APP"
# --keepParent: the zip unpacks to the .app itself, not to a loose Contents
# folder. --norsrc: no ._ files from this machine's extended attributes.
ditto -c -k --norsrc --keepParent "$BUILT_APP" "$ZIP"

echo "Built $BUILT_APP"
echo "Share $ZIP"
