---
name: civ4-player
description: Play the current CIVAI game (Civilization IV BtS) as a live player — read the playbook and the game folder, then listen for game events and act on them. Use when asked to play, continue, or resume the CIVAI game.
---

1. Read `~/civai/PLAYBOOK.md` and follow it. It is the full instruction set.
2. Do the "Start of a session" steps from the playbook.
3. Listen for wake-ups with the Monitor tool (timeout 1800000 ms, re-arm every time it expires):

   ```
   F="$HOME/Library/Application Support/CrossOver/Bottles/civ4/drive_c/claude_bridge/events.jsonl"; touch "$F"; tail -n 0 -F "$F" 2>/dev/null | grep --line-buffered -E '"kind":"(message_from_player|claude_wake|player_waiting|deal_done|deal_declined|deal_failed|native_deal)"'
   ```

4. Make sure auto-ready is on: `civ gate` should show `on: yes` and `auto: yes` (else `civ gate on` and `civ gate auto on 5`).
5. Talk to the person at the terminal in short plain English; in the game, stay in character.
