Compact this session for the CIVAI project. The next context must be able to keep directing the running game and keep building, without re-reading the transcript. Keep facts, numbers, paths, decisions and the author's words; drop tool-output noise and dead ends (keep a dead end only as a one-line "tried X, failed because Y").

Write these sections, in this order:

1. **The goal and how the author wants to work** (verbatim where it matters)
   - The active /goal text, verbatim.
   - The author's standing instructions, verbatim or near-verbatim: fix root causes with real code, not patches or undo; read the players' reports to the director constantly and react; tools-only answers to players, never game advice; general, scalable prompt instructions, never game-specific micro-rules; test early on the live game and say so; plain language; Russian in chat with the author; don't hold the author to past decisions.
   - Hard constraints: git author `noreff <uhhunet@gmail.com>`, never Claude/AI co-author trailers or mentions; repo noreff/civai stays private; no afplay; no iPhone; never kill fileproviderd; no webcam/mic in CIVAI recordings; fair play (each agent knows only its civ; `civ py` is director-only; models never read others' private messages, enforced by broker + sandbox); never permanently delete files (Trash only; the author empties it).

2. **Where things stand right now**
   - Current game: id, turn, seats (key, player, leader, civ, model, harness, effort), whether seats/broker/monitor run, bridge version, engine state.
   - Standings: score, cities, techs, military per leader; wars and peace in effect; who leads and why; notable storylines (attacks, betrayals, captured cities, Apostolic Palace resolutions, space race).
   - Counters for the paper: chat lines, private vs public, thoughts, deals between agents, failed wakes, content-filter refusals by model, tool error rate.
   - Disk free, recording state (OBS, gamerec.py idle pause), saves (every turn + `T###_bridge`).
   - Open questions waiting for the author (e.g. finish Test D or start the Claude/GPT/DeepSeek game; ChatGPT Pro; DeepSeek Pro vs Flash).

3. **The games so far, one paragraph each with the numbers that matter**: game-01 (Khan, human vs Claude), Test A, Test B (Claude/GPT/DeepSeek, GPT usage limit, ~5 messages each), Test C (3 Sonnet + built-in AI: 1 message in 330 turns, all eliminated by Hannibal), Test D (redesigned prompt, 5 agents, no built-in AI: >1000 messages, hundreds of deals, wars). What each one taught.

4. **The system as built** (enough to operate and change it)
   - Components and paths: `~/civai/loop.py` (seat loop, wake kinds founding/council/audience/turn, court table, closings, effort policy, refusal handling, "turn waits for you" wake, forced ready only for the wake's own turn), `broker.py` (socket, tokens, calls.jsonl with args+ms, neutral names, keeps saves + `T###_bridge`), `multi.py` (config/start/stop/restart/status), `metrics.py`, `replay.py`, `PLAYBOOK.md` (ruler's briefing: how the game is won, levers, court, rhythm, memory forms, tool sheet), `civ` CLI, `mod/CIVAI/Assets/Python/ClaudeBridge.py` (bridge, current version), engine in `~/civai-sdk/src/claude` (git; patch mirrored to `~/civai/engine/civai-engine.patch`), `~/youtube/rec/gamerec.py` and `trim_idle.py`.
   - Engine changes and why: claudeReady hold; simultaneous turns; claudeLeaveGroup; standing orders run while the agent plays; human pathfinding rules for agent units; claudeChooseElection; exports must stay 2432.
   - Bridge rules worth remembering: hooks answer as the owner's seat (asSeatOf); per-seat state (PerSeat); proposals open until the end of the next turn and re-read after the game acts; treaties are two-way; refusals explain why; `civ work`, `civ votes`, `what_they_give`, projects in lists.
   - Game/data layout: `~/civai/games/<id>/` (seats.json, manifest.json, calls.jsonl, saves/, raw/<seat>/ prompts+outputs, per-seat memory files, wakes/, wake_stats.jsonl, to_director.jsonl, director_inbox.md), bridge dir `claude_bridge` in the CrossOver bottle (chat_all.jsonl, truth.jsonl, p<N>/events.jsonl, bridge.log; game clock is 1 h ahead of the Mac's), archives in `claude_bridge/archive/`.

5. **Operating procedures that work** (step by step)
   - Reinstall engine/bridge: stop seats at once (a reload rewinds the turn anyway), kill Civ by the CX launcher name, wait for it to exit, `engine/install_engine.sh` and `./install.sh` (never in parallel with launching Civ), open Civ, Single Player → Load Game → expand single → auto → newest → OK (Wine needs mouse down/up; typing doesn't work), then `multi.py <id> start`, check `civ ping`, simultaneous turns, holds; tell players in `director_inbox.md` (tools only).
   - Bridge-only change: edit, bump BRIDGE_VERSION, `./install.sh`, wait for `civ ping` to show it (hot reload), commit.
   - Loop change: commit, `multi.py <id> restart` (waits per seat).
   - New game: archive bridge files, seats.json, `multi.py config`, Custom Game (open slot 6), launch, `multi.py start`, `forEachSeat(seatTurnStart)` + `setAIAutoPlay(400)`.
   - Monitoring: the Monitor script (reports, FAILED wakes, bridge FAILED/held, 15-min stall watchdog) expires every 30 min; re-arm it.

6. **Known issues and their status**: Opus content-filter refusals (~5-15%, rising with wars; audience skipped, turn retried with lower effort, passed after 3); the ready-but-held safety net (logs what holds a turn; root cause still open: likely hasBusyUnit skipping unit updates); turn 0 skipped at game start (simultaneous turns switched on mid-turn); bridge.log rename hiccups under Wine (now retried).

7. **Paper and video**: what's drafted (`~/civai/paper/`), the strongest findings so far (redesign effect C→D, filter refusals, built-in AI beating agents in C, Opus leading D), what the recording now captures (spectator full view, director camera) and what the replay tool can redo.

Keep it under ~2,500 words. Prefer lists and exact values over prose.
