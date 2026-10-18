Build a recap of a CIVAI game as one self-contained HTML page, for three readers at once: the author (what happened and what it means), a video editor (the scenes worth showing and where to find them), and a paper (method, numbers, findings). Game id: `<GAME_ID>` (default: the newest in `~/civai/games/CURRENT`; also compare with the earlier tests where noted).

## Ground rules
- Every fact comes from the logs, computed by a script you write and keep (`~/civai/recap/build_recap.py`, which writes `~/civai/recap/<GAME_ID>/data.json`, then the HTML). No fact from memory or guesswork; if the logs can't support a claim, leave it out or mark it "not in the logs".
- Quote the leaders verbatim (messages and thoughts), always with leader, turn and whether it was public, private (to whom) or a private thought. Never invent or smooth a quote; cut with "…" only.
- Private thoughts are the agents' own notes (`civ think`), shown next to what they said: label them clearly as private.
- Fair framing: n=1 game per setup; say so wherever you compare models. No "model X is smarter" claims; describe behaviour.
- Plain language. Numbers with units. Turn numbers and in-game years together ("T140, 1530 AD").

## Sources (read-only)
- `~/civai/games/<id>/`: `seats.json`, `manifest.json` (settings, models, file hashes), `calls.jsonl` (every command, exit code, error, exact args, ms time), `metrics.json` / `python3 ~/civai/metrics.py <id>`, `saves/T###_*.CivBeyondSwordSave` + `T###_bridge/`, `raw/<seat>/*.prompt.md|.out.jsonl` (full prompts and outputs), and per seat: `persona.md`, `ambitions.md`, `plan.md`, `secrets.md`, `chronicle.md`, `dossiers/`, `wakes/T###-*.md` (why woken, kind, thoughts, commands, self-check, final words, journal), `wake_stats.jsonl` (kind, effort, seconds, tokens, cost, errors, refusals, forced ready), `said.jsonl`, `thoughts.jsonl`, `to_director.jsonl` (bug reports), `director_inbox.md`, and the seat's git history (memory snapshots per wake).
- Bridge dir `~/Library/Application Support/CrossOver/Bottles/civ4/drive_c/claude_bridge/` (and `archive/<test>/` for earlier games): `chat_all.jsonl` (every message, from/to/turn), `truth.jsonl` (per-turn state of every civ: score, cities, pop, techs, military, gold, wars, met), `p<N>/events.jsonl` (deals, proposals, wars, peace, cities changing hands, combats, votes, rewinds), `bridge.log` (game clock is 1 hour ahead of the Mac's).
- Recordings: `~/youtube/raw/civai/streams/*_game.mp4` (spectator view; file names are the local start time of each piece; idle stretches were cut, active pieces keep their real start time), `*_kitty.mp4` (director terminal: never use in the video, it shows private tabs).
- Earlier tests for comparison: `~/civai/games/2026-10-17-test-b`, `2026-10-17-test-c` (and their `metrics_final.txt`), `~/civai/games/2026-10-17-test-b/recap_by_turn.md`.
- Engineering history: `git -C ~/civai log` and `git -C ~/civai-sdk/src/claude log` (what was fixed when, which player's report led to it).

## What the page contains (sections, in this order)

1. **The game in one screen.** Who played (leader, civ, model, harness, effort policy), map/speed/turns, the result or current standings, three sentences on what happened, and five headline numbers (messages, deals between agents, wars, cities that changed hands, content-filter refusals).
2. **Timeline.** Every turn as a strip; marked events: first contacts, deals, wars and peace, cities taken, wonders/projects, Apostolic Palace / UN resolutions and votes, eliminations, rewinds/reloads, stalls. Click (or hover) an event for its details and quotes. A score-over-time chart per leader from `truth.jsonl` (inline SVG, or Chart.js from cdnjs with a pinned version).
3. **The leaders.** One card each: persona (their own words from the founding wake), ambitions and how they changed (git history of `ambitions.md`), arc in 3–5 beats with turns, their most telling "said vs thought" pairs, promises kept and broken (with evidence turns), who they trusted and betrayed (dossier `Stance:` lines over time), and their bug reports to the director.
4. **Said vs thought.** The 10–20 strongest pairs across the game: a public or private message next to the private thought written with it, especially bluffs, betrayals, threats and secret deals. Each with turn, sender, recipients and readers.
5. **Diplomacy.** A network graph of deals between leaders (edge width = number of deals; colour = kind: tech, gold, treaty, city, war), message volume between each pair, and the war/peace map over time. Notable bargains with the exact offers and answers.
6. **Scenes for the video.** 10–15 candidate scenes, each: title, what happens (one line), why it works (drama, irony, betrayal, comeback), the quotes to show on screen, the turn and in-game year, the local wall time from the logs, the recording file and the offset in it where the turn is on screen (map wall time to `streams/*_game.mp4` by file start time; flag scenes that fell into a recording gap), and the save `saves/T###_*` to re-render it with `~/civai/replay.py <id> plan T`. Rank by strength. Add a 60–90 s cold-open suggestion and a 3-act outline.
7. **For the paper.** Setup and method (wake kinds, prompt design, fair play, tools, effort policy, simultaneous turns, engine changes, director rules: tools-only answers); measures per seat (wakes, seconds, tokens, cost, tool error rate, messages per 10 turns, reply rate, thoughts, deals, promises kept/broken, refusals); the comparison Test C → Test D (same harness and model family, prompt redesign) as the main finding, with the caveats; Opus vs Sonnet differences as observations, not claims; the content-filter result (refusals by wake kind and by game phase); threats to validity (n=1, tool bugs fixed mid-game with the turns they landed, rewinds, director interventions listed).
8. **Engineering log.** Bugs found during the game and who found them (agent reports vs director), the fix, the turn it landed. A short list of what is still open.
9. **Appendix.** Data sources, the script that built the page and how to rerun it, definitions of every metric.

## Design
- One self-contained `.html` (inline CSS/JS; libraries only from cdnjs with pinned versions); readable on a phone (16 px side margins, no horizontal scroll); light and dark themes via `prefers-color-scheme`; leader colours consistent everywhere (from the game's player colours in `truth.jsonl` if present, else a fixed palette).
- Quotes in a distinct style; private thoughts visibly different from public messages (e.g. italic with a lock icon); every number links or tooltips to its turn/source.
- A sticky table of contents. Collapsible long lists. No placeholder text.

## Output
- `~/civai/recap/<GAME_ID>/recap.html`, `data.json`, and `build_recap.py` (rerunnable as the game goes on).
- Then a short note: the five most interesting findings, any data you couldn't get, and anything in the logs that looks like a bug.
