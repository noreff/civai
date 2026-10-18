# CIVAI game engine

The game's core (CvGameCoreDLL.dll) rebuilt from Firaxis' BtS 3.19 SDK with one addition:
a civ can be flagged as Claude's (`CyPlayer.setClaude(True)`; the bridge sets it after every load),
and then the built-in AI makes no choices for it:

- per-turn AI routines skip it: research, budget, military disbanding, civics, religion, finances,
  diplomacy, colonies, spaceship, promotions, upgrades (CvPlayerAI::AI_doTurnPre/Post, AI_doTurnUnitsPre/Post);
- its cities: no rushing, drafting, panic builds, emphasis or forced specialists (CvCityAI::AI_doTurn);
- its team: no war plans, war or peace decisions (CvTeamAI::AI_doTurnPre/Post); other AIs no longer
  make peace with it on their own (CvTeamAI::AI_doWar) but ask, as they ask a human;
- AI leaders talk to it like to a human (CvPlayerAI::AI_doDiplo), but its "diplomacy screen" is the
  bridge: the game event `claudeDiplomacy`; offers made to it (`claudeOffered`) get no minister's answer;
- unit automation never disbands its units (CvUnitAI::AI_scrapUnlessClaude).

- other leaders ask it like a human: peace, capitulation and war-hire offers (AI_doPeace, the hire
  block), tribute requests from a master (also from the human master: no automatic war);
- votes (UN / Apostolic Palace), random events and quests, free techs (Oracle, first-to-discover)
  are Claude's choices (game events `claudeVote`, `claudeEvent`, `claudeFreeTech`);
- research is never picked or wiped for it; the budget and espionage weights are never reset;
- its ministers don't refuse trades, cap gold, refuse to talk or write counter-offers: Claude answers;
- it plays by the human's difficulty rules (costs, upkeep, unit supply, inflation, war weariness,
  upgrade prices, production decay, animal/barbarian combat);
- handing it to Claude clears war plans the built-in AI left behind.

Python additions: CyPlayer.isClaude/setClaude, handleDiploEvent (answer an AI's request with the
game's own effects), AI_considerOfferText, implementDealText; CyTeam.isClaude, CyGame.castVote, CyPlayer.claudeApplyEvent, CySelectionGroup.claudePathTurns.

## Build (on the Mac, MSVC 7.1 under CrossOver)

The toolchain lives in ~/civai-sdk (VC++ Toolkit 2003 unpacked from Leoreth's SDK installer, the
2003 SP1 Platform SDK headers/libs, a CrossOver bottle `civ4sdk`). Sources: ~/civai-sdk/src/claude
(a git repo: Firaxis' code, then our commits; `civai-engine.patch` here is that diff).

    ~/civai-sdk/build.sh ~/civai-sdk/src/claude ~/civai-sdk/build/claude 6    # about a minute

Install: copy build/claude/CvGameCoreDLL.dll to Mods/CIVAI/Assets/ (needs a game restart; the
stock DLL in Beyond the Sword/Assets stays untouched). The bridge works with both engines.
