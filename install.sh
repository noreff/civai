#!/bin/bash
# Copy the CIVAI mod into the Civ IV: BtS install inside the CrossOver bottle.
# Files are updated in place (no delete-then-copy), so a running game can hot-reload.
set -e
BTS="$HOME/Library/Application Support/CrossOver/Bottles/civ4/drive_c/GOG Games/Civilization IV Complete/Civ4/Beyond the Sword"
rsync -a --exclude __pycache__ "$(dirname "$0")/mod/CIVAI/" "$BTS/Mods/CIVAI/"
mkdir -p "$HOME/Library/Application Support/CrossOver/Bottles/civ4/drive_c/claude_bridge"
echo "installed -> $BTS/Mods/CIVAI"
