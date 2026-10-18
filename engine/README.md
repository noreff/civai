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

Python additions: CyPlayer.isClaude/setClaude, handleDiploEvent (answer an AI's request with the
game's own effects), AI_considerOfferText, implementDealText; CyTeam.isClaude.

## Build (on the Mac, MSVC 7.1 under CrossOver)

The toolchain lives in ~/civai-sdk (VC++ Toolkit 2003 unpacked from Leoreth's SDK installer, the
2003 SP1 Platform SDK headers/libs, a CrossOver bottle `civ4sdk`). Sources: ~/civai-sdk/src/claude
(a git repo: Firaxis' code, then our commits; `civai-engine.patch` here is that diff).

    ~/civai-sdk/build.sh ~/civai-sdk/src/claude ~/civai-sdk/build/claude 6    # about a minute

Install: copy build/claude/CvGameCoreDLL.dll to Mods/CIVAI/Assets/ (needs a game restart; the
stock DLL in Beyond the Sword/Assets stays untouched). The bridge works with both engines.
