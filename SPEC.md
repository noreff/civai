# CIVAI — Claude plays Civilization IV: Beyond the Sword

## Goal

Play Civ IV: Beyond the Sword against Claude (or alongside it), with Claude running a civilization **like a live player**:

- it sees only what its civilization sees;
- it can do anything a human can, at any level: from grand strategy down to every single worker;
- it talks to the player right inside the game;
- it remembers the whole game: plans, promises, grudges;
- it leaves a trail for the video: what it thought, what it decided, what it kept secret.

The end goal is to record a game and publish it on YouTube.

## How it should feel (for the player)

1. I start the game with the CIVAI mod and say which civilization Claude plays.
2. I play my turn as usual. Meanwhile Claude looks around, thinks and gives orders.
3. I press End Turn. If Claude isn't done yet, the game waits and shows "Brennus is still thinking...".
4. I write to Claude's leader in the game chat (or in the terminal). The answer shows up in the game within seconds.
5. We can agree on joint actions ("bring your archers, we take Babylon together") and Claude **actually does them**.
6. Claude writes to me on its own when something happens: first contact, war, a city taken, a wonder.
7. Claude remembers what happened 200 turns ago, even after its session restarts.
8. After the game there is a chronicle and a timestamped log of thoughts for editing.

## Principles

- **Fairness is built into the bridge.** Every query answers only with what Claude's civilization knows. Asking about hidden things is impossible by design. (The dev-only `civ py` sees everything; it is logged and can be switched off with `exec = off` in `config.txt`.)
- **The same buttons a human has.** Actions come from the list the game itself considers available for a unit or city. No custom code per action type.
- **Full control at any level.** Claude can drive every worker by hand. The built-in AI's automation is an option Claude turns on when it wants, like a human does, not an obligation.
- **Manual control must be cheap.** One call, many orders. Multi-turn orders: "go to", build queues, worker job queues ("farm here, then a road there").
- **Compact context.** A short digest + details on request + memory files. The game is never held in the head as a whole.
- **Explicit errors.** "Can't found a city here: too close to Uruk", never a silent failure.
- **Minimal code.** No changes to the game's C++ core while Python is enough.

## Decisions (2026-10-14)
- The built-in AI is the autopilot; Claude takes over anything, for any length of time. Full manual control (down to each worker) must be available and cheap.
- The game **always waits** for Claude: the AI's turn can't start until Claude says `civ ready`.
- Every turn gets a quick check (digest, small orders, `ready`). Deep thinking happens on events, every few turns, and when the player writes.
- The "brain" is a Claude Code session on the personal Max subscription, no API.

## Layers (decision 2026-10-14)

| Layer | What | Why |
|---|---|---|
| Mod `CIVAI` (bridge code: `ClaudeBridge.py`) | Python inside the game | eyes and hands: the world with fog of war, orders, events |
| Tool `civ` | terminal command | one way to talk to the game |
| Skill `civ4-player` | instructions for Claude Code | how to play: turn loop, fairness, persona, chat, memory, BtS strategy |
| Game folder `games/<id>/` | memory files | what is happening in this particular game |

The skill gets real content after stages 3 and 6, once there are real commands and a real turn loop. No separate MCP server is needed.

## Parts

### 1. Bridge (game ↔ Claude)
- Mailbox: folder `C:\claude_bridge\` (on the Mac: `…/Bottles/civ4/drive_c/claude_bridge/`).
- The mod checks incoming requests several times a second, runs them inside the game and writes the reply.
- On the Mac, `civ …` writes a request and waits for the reply (~50 ms). Works at any moment: on my turn, on Claude's, between turns, with the game window in the background.

### 2. Commands (✅ = exists)
**Look:**
- ✅ `civ ping`, `civ status` — digest: empire, cities, units, research, relations
- ✅ `civ map [X Y [R]]` — schematic map (PNG) with fog of war, plus a zoom
- ✅ `civ tile X Y`, `civ city <name>`, `civ unit <id>`, `civ player <name|civ|id>` — details, like hovering the mouse
- ✅ `civ events [N]`, `civ chat [N]` — event log and chat log (read from disk, work without the game)
- `civ actions <unit|city>` — which "buttons" are available right now

**Do:**
- ✅ `civ move <id> X Y` — walk a unit, over several turns, also into unexplored areas
- `civ do <unit(s)> <action> [params]` — any available action, can be queued
- `civ city <name> build|queue|hurry …`
- `civ research …`, `civ civics …`, `civ religion …`, `civ slider …`
- `civ war|peace|deal <player> …`
- ✅ `civ say "<text>"` — a chat line from Claude's leader in the game (`--popup` for a window)
- ✅ `civ py "<code>"` — DEV ONLY: run Python inside the game (sees everything, logged to `exec.log`)

**Who's in control:**
- ✅ `civ claim|release <id|all>` — take a unit from the built-in AI or give it back
- ✅ `civ gate on|off`, `civ ready` — the player can't end the turn until Claude says it is ready

**For the video:**
- ✅ `civ think "<text>"` — one line of reasoning → `games/<id>/thoughts.jsonl`; every `civ` command → `commands.jsonl` (wall-clock time, for overlays)

### 3. Turn loop and wake-ups
- Claude thinks during the human's turn. Turns are sequential, so there is time.
- The human's End Turn waits for `civ ready` (the `cannotDoControl` hook; "wait at end of turn" is switched on so auto end-turn can't bypass it). Escape hatch: the player types `!go` in chat.
- Wake-ups come from the event log: a player message, the player's turn starting, the player waiting at End Turn, first contact, war/peace, a city changing hands, a claimed unit arriving, a great person, a religion founded.

### 4. Memory (files in the game folder)
- `plan.md` — current strategy
- `dossiers/<player>.md` — promises, deals, grudges, trust
- `secrets.md` — what I hide and where I bluff
- `chronicle.md` — the chronicle; old eras get compressed
- everything stamped with the turn number, so a reloaded save is visible

### 5. For the video
- `thoughts.jsonl`, `commands.jsonl`, `chat.jsonl`, `events.jsonl` — all timestamped
- recording via `rec` (OBS): composite screen, webcam, and separate game / terminal streams
- later: voice for the leader's lines

## Direction: any LLM, many players (decision 2026-10-15)
Later CIVAI should run with an LLM of the user's choice, and several AIs should be able to play each other (with or without the human) — e.g. Claude vs Gemini vs ChatGPT vs Qwen as a home-made eval. Not now: we keep prototyping with Claude Code for speed, but build so the switch is cheap:
- **The game side stays model-agnostic.** Mod + mailbox + `civ` CLI are the whole interface; anything that can run a shell command can play. No Claude-specific logic in the bridge.
- **Everything is per player.** Commands, fairness filter, turn gate, claims and logs should take a player id instead of assuming one "Claude player" (today: `player = N` in `config.txt`). The gate waits for *all* agent-controlled players.
- **Game knowledge lives in files, not in the chat session.** Plan, dossiers, persona and rules are files in `games/<id>/` and the skill, so another model (or a fresh session) can pick them up.
- **Wake-ups come from `events.jsonl`.** The Claude Code Monitor is just one reader; a later harness reads the same file.
- **AI-only games (checked in the SDK 2026-10-15, not tested yet):** the game has a built-in "AI plays itself" mode, `CyGame().setAIAutoPlay(N)`, callable from Python. It removes the human's own civ (the human becomes a spectator) and runs N turns without anyone pressing End Turn; with N large the game never ends early (the "no humans left → game over" check is skipped while autoplay is on). Python's `doReviveActivePlayer` hook can keep the spectator from being revived. Missing piece: with no human End Turn to block, the game won't wait for agents (the AI turn can't be held by the unit hook: after 100 tries the game ends the unit's moves; `setPausePlayer` isn't exposed to Python). Workaround to test: when an agent-controlled player's turn starts, the bridge **holds inside Python**, still answering the mailbox, until that agent says `ready` (with a timeout). The game window freezes during that wait, which is fine for AI-only runs. The same hold could replace the End Turn lock in mixed games.
- **Cost matters.** Wake only on real events (auto-ready on quiet turns), keep the playing session small (a game-only session, not the dev session).

## Pitfalls found along the way
- **The in-game clock moves in 128-second steps**: the graphics engine switches the CPU's floating point to single precision, so `time.time()` in the game's Python is useless for short intervals. Everything time-based uses frame counters. Before we found this, it looked like the game "doesn't work without focus"; in fact the bridge works in the background and answers in ~50 ms.
- **The game caches the mod's Python files at startup**, and `reload()` returns stale code. So the bridge is loaded with `imp.load_source` straight from disk and **hot-reloads** when the file changes. A game restart is only needed after editing `ClaudeEventManager.py` or the XML.
- Hooks (chat, keys, unit AI, End Turn) are attached to the live event manager **at runtime** (`installPatches`), so they also update without a restart.
- The per-frame event is enabled by `USE_ON_UPDATE_CALLBACK` in the mod's `PythonCallbackDefines.xml`; plus a subscription to `gameUpdate`.
- The English game has no Cyrillic glyphs: in the game Claude's leader writes in English (or Russian transliteration).
- The built-in AI may cancel a unit's order mid-way, so any unit Claude gives an order to is **claimed** (`claims.json` + the `AI_unitUpdate` hook).
- The pathfinder only knows revealed tiles: orders into the dark walk toward the closest known tile in that direction and re-plan each turn.
- The player's turn-start event fires before the game turn counter moves on: label it `turn + 1`. `civ ready` targets the turn the human is playing or about to play.
- The game's tech tree differs from memory (e.g. in BtS Alphabet needs Writing, which needs Priesthood / Animal Husbandry / Pottery): rules and costs must come from the game's XML / API, never from recollection.
- The mod loads automatically (`Mod = Mods\CIVAI` in `CivilizationIV.ini`), the game runs windowed at 1680×1050.

## Known limits of a Python-only mod
- Resource trades (ongoing per-turn deals) can't be created: Python can read bonus imports/exports but not change them, and CvDeal's trades aren't exposed. Needs a DLL change (compiling the SDK with the old MSVC toolchain).
- The leader-screen diplomacy (animated leader) can't be opened from Python: deals with the human use the game's popup window instead.
- When the human trades with the Claude civ through the native diplomacy screen, the built-in AI still decides (no Python hook for AI_considerOffer). Deals with the Claude civ should go through chat + `civ offer`. The same holds for deals other AIs propose to the Claude civ during their turns: they can't be stopped, so the bridge compares snapshots at every turn hand-over, reports them (`native_deal`, with whose turn) and `civ cancel` ends ongoing ones under the game's rules (v31).
- Decisions the built-in AI no longer makes for the Claude civ (v31): the commerce split (`civ budget`, re-applied in the doGold hook, after AI_doCommerce), razing captured cities (canRazeCity hook keeps them; `civ raze` within a turn).

## Deliberately not doing
- No playing through screenshots and clicks on the 3D map: screenshots are for the video only.
- No changes to the game's C++ core (until we hit a wall).
- No separate orchestrator: the "brain" is a Claude Code session.
- No per-action code: everything goes through the game's own list of buttons.

## Risks to check
1. ✅ Holding the human's End Turn while Claude thinks — solved with `cannotDoControl`.
2. ✅ Whether AI units obey orders given outside their turn and whether the AI can be stopped from overriding them — solved with claims.
3. ✅ Mailbox in the update event: frequency, load, between turns — fine once the 128 s clock was found.
4. Getting a unit's or city's "buttons" from the game's action list.
5. Diplomatic deals from Python: techs, gold, resources, borders.
6. Speed: time per turn late in the game with full manual control.

## Stages

Each stage is a small piece: build → check together in the game → fix → move on.

| # | Stage | Done when |
|---|------|---------------|
| 0 | Eyes v0: world dump + schematic map | ✅ 2026-10-14 |
| 1 | Bridge: mailbox, `civ ping`, `civ status` | ✅ 2026-10-14: ~50 ms replies, also in the background (see "Pitfalls") |
| 2 | Look on request: `map`, `tile`, `city`, `unit`, `player`, `events` | ✅ 2026-10-14 |
| 3 | Buttons: `actions` + `do` for units and cities, research | ✅ 2026-10-15: `civ research`, `civ build` (city claims keep the queue), `civ actions` / `civ do` from the game's own action list, `civ area` text map with best city sites. Left: civics, sliders |
| 4 | Taking over from the AI: `claim` / `release`; war and peace only by Claude's decision | ⏳ units ✅ (the scout stood by the cows); war/peace and cities are next |
| 5 | Turn sync: `ready` | ✅ 2026-10-14: `cannotDoControl` blocks the human's End Turn until `civ ready`; `!go` in chat is the escape hatch; turn start and waiting wake Claude |
| 6 | Wake-ups: events wake Claude | ✅ mostly: Monitor on `events.jsonl` (re-arm every 30 min); Claude wrote first on meeting the Khan. 2026-10-15: auto-ready on quiet turns (`civ gate auto on [N]`), wake only on `claude_wake` (with reasons), chat or a waiting player; `civ hold` |
| 7 | In-game chat | ✅ 2026-10-14: the game's own chat (Tab) both ways, `civ say`, `civ chat` |
| 8 | Skill `civ4-player` + memory: files and update rules (2026-10-15: `loop.py` plays one fresh call per wake-up — playbook + memory files + brief; model command in `loop.json`; wake-up logs in `games/<id>/wakes/`) | ⏳ 2026-10-15: `PLAYBOOK.md` (model-agnostic) + thin skill `.claude/skills/civ4-player`; game files persona/plan/dossiers/secrets/chronicle. Done when a fresh session continues the game with the same personality |
| 9 | Diplomacy: deals | tech trades, peace, open borders agreed in chat |
| 10 | Test game without recording | a list of what is slow or annoying, fixed |
| 11 | Video: thought log, overlays, voice, recording | first video |

## State as of 2026-10-14, evening (live game)

- Game: Brennus (Celts, player 1) = Claude; V (Spain, player 0) = human; England (Victoria), Mongolia (Kublai Khan, met on turn 42), one more civilization not met yet. Turn ~43.
- Turn gate is on (`civ gate on`): Claude says `civ ready` every turn. Wake-ups: a Monitor on `events.jsonl` (chat, turn start, waiting, contact, wars, "unit arrived"); a monitor lives 30 minutes and must be re-armed.
- Scout #16385 is claimed by Claude, heading to (25, 24) ("10 west and 5 north of the cows"). Bibracte: worker → settler. Research: Agriculture → Priesthood → Writing → Alphabet.
- Game memory: `games/celts-vs-spain/` — `dossiers/spain.md` (the Alphabet pact: whoever gets it first gives it to the other for free; trades Archery↔Agriculture and Masonry↔Mining), `dossiers/mongolia.md`, `thoughts.jsonl` and `commands.jsonl` (timestamps for editing).
- Recording: `rec` (OBS hidden) writes the composite screen + webcam to `~/youtube/raw/ml-systems/2026-10-14_21*` (move to `~/youtube/raw/civai/` after "stop"), and separate game and kitty streams via Source Record to `~/youtube/raw/civ4-claude/streams/` (rename to `civai` after "stop"). `rec` got a `civ4` capture; the kitty layer sits above the game. Use `rec mark` at interesting moments.

### Next tasks
1. Stage 3: the general action mechanism (unit and city buttons), research and production as fair commands instead of `civ py`.
2. Idea pending the player's decision: "ready in advance, wake me only on events", so empty turns don't wait for Claude.
3. Bug: first contact is logged twice (first as "an unknown civilization").
4. Rule for the skill: take the tech tree and rules from the game's XML / API, not from memory.
5. Skill `civ4-player` (stage 8).
6. Bug (2026-10-15): Mongolia's research was set to Animal Husbandry on T21, progressed T21-24 (67/360), then was empty (-1) on T25 with no event explaining it. Cause unknown; `claude_wake` now includes `research_idle` so it can't silently waste turns.
