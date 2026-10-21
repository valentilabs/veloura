#!/bin/zsh
# Build Veloura.app from a clean copy outside the iCloud-synced Desktop (run: npm run package:clean).
# iCloud "Optimize Mac Storage" evicts files in this folder; reading an evicted file can stall for minutes or come
# back empty, so the build takes its sources from git (committed code plus uncommitted edits to tracked files) and
# installs fresh npm packages in ~/Library/Caches/Cadence Build/src.
set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$HOME/Library/Caches/Cadence Build/src"
rm -rf "$SRC"
mkdir -p "$SRC"
git -C "$REPO" archive HEAD | tar -x -C "$SRC"
git -C "$REPO" diff --name-only HEAD -- veloura app fl_scripts requirements.txt | while read -r f; do
  [ -f "$REPO/$f" ] && cp "$REPO/$f" "$SRC/$f"
done
cd "$SRC/app"
npm ci --no-audit --no-fund --loglevel=error
node build/package.js < /dev/null
