#!/usr/bin/env bash
# Build a clean directory to deploy from.
#
# `gradio deploy` calls upload_folder() on the whole working directory with no
# ignore patterns and no .gitignore handling — it would publish .env (both API
# keys), .venv/ and sandbox/. Deploying from a staging directory that contains
# only what the Space needs is the safe way round that.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$HERE/.space"

rm -rf "$OUT"
mkdir -p "$OUT/src" "$OUT/examples"

cp "$HERE/app.py"          "$OUT/app.py"
cp "$HERE/pyproject.toml"  "$OUT/pyproject.toml"
cp "$HERE/uv.lock"         "$OUT/uv.lock"
cp "$HERE/SPACE_README.md" "$OUT/README.md"   # the front-matter version Spaces needs

cp -r "$HERE/src/engineering_team" "$OUT/src/engineering_team"
cp -r "$HERE/examples/gym_class_booking" "$OUT/examples/gym_class_booking"

# Strip anything that is build output or would be dead weight in the Space.
find "$OUT" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$OUT" -name "*.pyc" -delete
rm -f "$OUT/examples/gym_class_booking/gym_class_booking.zip"

echo "Staged $OUT"
echo
echo "Secrets that must NOT be there:"
for f in .env .venv sandbox exports tests PLAN.md CLAUDE.md; do
  if [ -e "$OUT/$f" ]; then echo "  LEAK: $f"; exit 1; fi
done
echo "  none present — clean"
echo
echo "Size: $(du -sh "$OUT" | cut -f1)"
