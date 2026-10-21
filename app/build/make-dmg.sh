#!/bin/zsh
# Veloura-Beta.dmg from the signed build: Veloura.app + an Applications shortcut, signed with the Developer ID,
# notarized and stapled, then checked as a quarantined download. Run after `npm run package:clean` with VELOURA_SIGN=1.
# Usage: zsh app/build/make-dmg.sh   (needs the "cadence-notary" notarytool profile in the Keychain)
set -e
B="$HOME/Library/Caches/Cadence Build"; A="$B/dist/Veloura-darwin-arm64/Veloura.app"; OUT="$B/release"
ID="${SIGN_IDENTITY:-Developer ID Application}"; PROFILE="${VELOURA_NOTARY_PROFILE:-cadence-notary}"
LSR=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
[ -d "$A" ] || { echo "No signed build at $A"; exit 1; }
mkdir -p "$OUT"; rm -f "$OUT/Veloura-Beta.dmg"
# Branded window (dmg-background.tiff from make-dmg-art.js) laid out by dmgbuild, so Finder never has to be scripted.
DMGBUILD="$B/dmgbuild-venv/bin/dmgbuild"
[ -x "$DMGBUILD" ] || { /usr/bin/python3 -m venv "$B/dmgbuild-venv" && "$B/dmgbuild-venv/bin/pip" install -q dmgbuild; }
HERE="$(cd "$(dirname "$0")" && pwd)"
"$DMGBUILD" -s "$HERE/dmg-settings.py" -D app="$A" -D build_dir="$HERE" "Veloura Beta" "$OUT/Veloura-Beta.dmg"
codesign --sign "$ID" --timestamp "$OUT/Veloura-Beta.dmg"
xcrun notarytool submit "$OUT/Veloura-Beta.dmg" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$OUT/Veloura-Beta.dmg"
xcrun stapler validate "$OUT/Veloura-Beta.dmg"
T=$(mktemp -d); cp "$OUT/Veloura-Beta.dmg" "$T/"; xattr -w com.apple.quarantine "0083;$(printf %x $(date +%s));Safari;" "$T/Veloura-Beta.dmg"
echo "== DMG as a download:"; spctl -a -vv -t open --context context:primary-signature "$T/Veloura-Beta.dmg" 2>&1
MP=$(mktemp -d); hdiutil attach -quiet -nobrowse -readonly -mountpoint "$MP" "$T/Veloura-Beta.dmg"
echo "== Veloura.app inside:"; spctl -a -vv -t exec "$MP/Veloura.app" 2>&1
$LSR -u "$MP/Veloura.app" 2>/dev/null || true; hdiutil detach -quiet "$MP"; rm -rf "$T" "$MP"
ls -la "$OUT/Veloura-Beta.dmg"
# The update notice's manifest (app/update-check.js reads it from the latest GitHub Release): attach it next to the DMG.
VERSION=$(/usr/libexec/PlistBuddy -c "Print CFBundleShortVersionString" "$A/Contents/Info.plist")
printf '{"version": "%s", "download_url": "https://github.com/valentilabs/veloura/releases/latest/download/Veloura-Beta.dmg", "headline": ""}\n' "$VERSION" > "$OUT/veloura-update-mac.json"
cat "$OUT/veloura-update-mac.json"
