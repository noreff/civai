# How to film a CIVAI game so it cuts into the video we want

Reference: `~/youtube/research/video-study-fQ0mx2s7suc/REPORT.md`. Its engine is a chronicle voice over gameplay where every beat is a decision with a motive, and the game's own screens (pop-ups, diplomacy faces, rankings, defeat/victory) land the punchlines, cut every ~3 s. We have the real motives: every message with its private aim, deals, promises, wars. Everything on screen must be real footage of the game; quotes verbatim from the logs.

## What we learned (2026-10-18)

- **Replaying a turn from its save does not reproduce it.** `replay.py run 217` (Moscow's capture) loaded the save and re-sent all 200+ orders in order, yet units ran out of moves at different points and Moscow did not fall: 10 differences in the record of the next turn. Combat and AI moves don't come back the same under simultaneous turns. So a battle, a capture or an elimination can only be filmed **when it happens**. Saves are good for what doesn't depend on chance: the map at the start of a turn, armies before a battle, a city's state, slow pans.
- Loading under Wine: synthetic keys from scripts are ignored; from the screen, Ctrl+L opens the load dialog and the mouse (press/release) works.

## Three layers

**A. Live, on the moment (the only source for events).** The recording runs all game (OBS + `gamerec.py`). What must change: the director camera must catch each event the way the reference uses it.
- For every war declaration, city capture, elimination, wonder/project, launch and vote result: jump the camera there, hold 6–8 s, and show the game's own screen for it from the involved player's side (the pop-up, the diplomacy face) where the game allows, not only the spectator map. To build: an event → camera script in the bridge's director camera (it already follows events) with a hold time per kind, and a check that pop-ups for the involved player are visible in spectator mode.
- Every jump writes a mark (event, turn, wall time) so the edit finds it: one index file per game, `games/<id>/clips.jsonl`.

**B. From saves, for what doesn't depend on chance.** Before/after shots: the map and armies at the start of turn T, a city screen, a leader's empire, slow pans for the narration. `replay.py` loads the save (mouse step) and the camera script films; no orders are sent.

**C. Made once per game, from the logs.** Remotion cards in Civ IV style:
- said-vs-aim card (the running gag): portrait + model badge, the public line, then the private aim;
- the score race / ranking (truth.jsonl), war-and-peace map over time;
- "from the private notes of…" cards (chronicle, persona, last words);
- end-of-game interviews: every leader's last wake-up already writes its own epilogue and last words (the `end` and `fall` wake-ups).

## Data to build for the edit

1. `clips.jsonl` per game: event → turn → wall time → recording file and offset (from the camera marks and the events; the game clock is 1 h ahead of the Mac's).
2. A promise ledger: who promised what to whom on which turn, kept or broken (setups and payoffs).
3. A beat miner: ranks moments (said vs aim far apart, broken promises, betrayals, captures, eliminations, rank changes) into a shortlist for the voice-over script, each with its clip.
4. Rewinds: thrown-away stretches are cut from the recordings (`rewind.py` writes them, `trim_idle.py --rewinds --go` cuts), so the footage is one timeline.
