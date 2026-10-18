#!/bin/bash
# Put the CIVAI engine (or, with --stock, take it out) into the CIVAI mod. Civ must not be running.
set -e
BTS="$HOME/Library/Application Support/CrossOver/Bottles/${CIV_BOTTLE:-civ4}/drive_c/GOG Games/Civilization IV Complete/Civ4/Beyond the Sword"
DST="$BTS/Mods/CIVAI/Assets/CvGameCoreDLL.dll"
if ps -Ao command | grep -iq "[C]iv4BeyondSword"; then
	echo "Civ is still running: save, quit, then run this again"; exit 1
fi
if [ "$1" = "--stock" ]; then
	rm -f "$DST"; echo "removed: the mod uses the stock engine again"; exit 0
fi
SRC="${1:-$HOME/civai-sdk/build/claude/CvGameCoreDLL.dll}"
cp "$SRC" "$DST"
ls -l "$DST"
echo "installed the CIVAI engine; start Civ with the CIVAI mod and load the save"
