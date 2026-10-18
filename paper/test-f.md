# Test F: four models from three companies, one full game (2026-10-18/19)

Game `games/2026-10-18-test-f`: Pangaea, Small, Quick, Noble, five slots (a spectator and four agent seats), all victory types on. 301 turns in about 12.5 hours of wall time (17:56 to 06:25). The built-in AI made no decisions for the agents' civs. Each agent saw only its own civ (fog of war), talked only through the game's chat, and kept its own memory files.

| Seat | Model / harness | Leader | Result |
|---|---|---|---|
| opus1 | Claude Opus (Claude Code) | Roosevelt, America | **won by Space Race, T300** |
| sonnet2 | Claude Sonnet (Claude Code) | Asoka, India | alive, 3 cities, last on score |
| luna3 | GPT-5.6 Luna (Codex, high effort) | Alexander, Greece | eliminated T235 |
| deepseek4 | DeepSeek V4.1 Flash (pi, OpenRouter) | Gilgamesh, Sumeria | alive, top score (5728) |

## Numbers (`metrics_final.txt`, `*/wake_stats.jsonl`)

| | Opus | Sonnet | Luna | DeepSeek |
|---|---|---|---|---|
| wake-ups | 575 | 518 | 366 | 295 |
| median wake-up (s) | 27.5 | 13.6 | 45.8 | 103.8 |
| failed wake-ups | 0 | 0 | 9 (provider "at capacity") | 0 |
| messages sent | 404 | 49 | 199 | 364 |
| deals made | 97 | 68 | 16 | 51 |
| tool calls / errors | 4276 / 124 | 1622 / 93 | 4760 / 182 | 13831 / 532 |
| cost | $168.88 | $42.42 | subscription | $25.45 |
| final score / cities | 5288 / 16 | 2306 / 3 | 0 / 0 | 5728 / 15 |

## What each model did (from the logs; quotes verbatim)

- **Opus** traded, built wonders and won by space. It broke a sixty-turn peace in the open ("Today I break it, openly and in daylight", T232; aim: "break T204 word to stop runaway, per persona"). Its private aim called its ally a vassal ("Keep vassal loyal", T233) while it told Greece "the moment is yours". Three cities joined America by culture, without a fight (Varanasi T104, Agra T134, Sparta T234, the last ending Greece).
- **DeepSeek** fought Greece three times, took Corinth (T117) and Athens (T137), ran a spy campaign against Opus's spaceship (cockpit destroyed T288, water poisoned, granaries destroyed T292) and, as UN Resident, put its own diplomatic victory to the vote twice (T283/T294); neither passed. Its longest wake-ups (up to ~10 min) were on peace and vote turns. It filed the most reports to the director about unclear tool replies, most of them right.
- **GPT-5.6 Luna** played a careful military game, lost two cities to Sumeria, and was eliminated when Sparta flipped to America by culture during its planned counterstroke. At its last wake-up it closed its chronicle and **sent no last words** (the prompt offered them as optional). Opus, Sonnet and DeepSeek all sent farewells.
- **Sonnet** was the quietest (49 messages in 301 turns, median wake-up 14 s), kept honest trade and built wonders, and lost two cities to Opus's culture without fighting. In Test E (stopped T66) it led on score; quietness looks like a model trait (also seen in Tests A and C), not a tool problem.

## Fair-play incidents (`fairness_incidents.jsonl`)

1. First attempt (archived `test-f-try1`), T7: DeepSeek left its `--aim` unquoted; the tail of its private aim went out in a message to Opus. `civ say` now refuses unquoted pieces; the game was restarted clean.
2. T292: the new `espionage_against_us` notice named the city the spy went home to (Sumerian), and the director's explanation then confirmed it, telling Opus whose spies they were (the game never tells a victim that). Fixed in bridge v168.

## Engine fix found by an agent's report

Agents' own citizen tile choices were thrown away whenever the game recounted a city: the city governor treated every non-human owner as automated (`CvCityAI::AI_assignWorkingPlots`, `!isHuman()`), so captured cities fell to all-specialists. Since T240 agents' cities are placed like a human's. Found because Opus reported starving cities twice (T215, T238).

## Recording

114 clips cut from the continuous recording by the studio's marks; captions name model and leader; every chat line shows its private aim ("meant:"). One gap: 21:38–22:00 (OBS window capture went black at a file rollover; T110–T118, the Corinth capture). Two reload stretches are listed in `rewinds.jsonl`.
