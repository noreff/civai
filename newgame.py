#!/usr/bin/env python3
"""Pick who plays each slot of a new game, then start the AIs once the game is on screen.

  ./newgame.py <game-id> new                           # then pick in Custom Game: a row's difficulty "Claude Opus",
                                                       # "Claude Sonnet", "GPT-5.6" or "DeepSeek V4.1" = that model plays it
  ./newgame.py <game-id> 1=opus 2=builtin 3=sonnet     # or pick here: player 0 is you; 1.. are the Custom Game's rows 2..
  ./newgame.py <game-id> start                         # after Launch, when the map is on screen

Models: opus, sonnet, gpt, deepseek; builtin = the game's own AI (labelled "Civ IV AI (<leader>)" on screen).
On screen every model plays under its name ("Claude Opus"), the seats themselves keep reading the leaders' names.
The first step archives the bridge files of the last game (nothing is deleted) and makes the new game current."""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.expanduser("~/Library/Application Support/CrossOver/Bottles/civ4/drive_c/claude_bridge")
MODELS = {
    "opus":     {"display": "Claude Opus", "harness": "claude", "model": "opus", "system": "replace"},
    "sonnet":   {"display": "Claude Sonnet", "harness": "claude", "model": "sonnet", "system": "replace"},
    "gpt":      {"display": "GPT-5.6 Luna", "harness": "codex", "model": "gpt-5.6-luna"},
    "deepseek": {"display": "DeepSeek V4.1 Flash", "harness": "pi", "model": "deepseek/deepseek-v4.1-flash-1017"},
}


LEVELS = {"HANDICAP_MODEL_OPUS": "opus", "HANDICAP_MODEL_SONNET": "sonnet", "HANDICAP_MODEL_GPT": "gpt",
          "HANDICAP_MODEL_DEEPSEEK": "deepseek"}


def archive_last(game):
    # the last game's bridge files go to the archive (moved, never deleted); the new game becomes current
    last = open(os.path.join(HERE, "games", "CURRENT")).read().strip()
    keep = os.path.join(BRIDGE, "archive", last)
    moved = []
    for f in sorted(os.listdir(BRIDGE)):
        if (f.startswith("p") and f[1:].isdigit()) or f in ("chat_all.jsonl", "truth.jsonl", "timeline.json"):
            os.makedirs(keep, exist_ok=True)
            os.rename(os.path.join(BRIDGE, f), os.path.join(keep, f))
            moved.append(f)
    if moved:
        print("archived %s -> archive/%s" % (", ".join(moved), last))
    os.makedirs(os.path.join(HERE, "games", game), exist_ok=True)
    open(os.path.join(HERE, "games", "CURRENT"), "w").write(game + "\n")


def new(game):
    """The models are picked in the Custom Game screen (difficulty per row); the bridge treats those rows as agents
    from the first turn ("players = auto"), so their turns wait for the models."""
    archive_last(game)
    with open(os.path.join(BRIDGE, "config.txt"), "w") as f:
        f.write("players = auto\nmulti = yes\n")
    print("config.txt: players = auto. Custom Game: set a row's difficulty to a model; then ./newgame.py %s start" % game)


def picked_in_game():
    out = subprocess.run([os.path.join(HERE, "civ"), "py", "result=[(i, gc.getHandicapInfo(gc.getPlayer(i).getHandicapType()).getType()) "
                          "for i in range(gc.getMAX_CIV_PLAYERS()) if gc.getPlayer(i).isEverAlive() and not gc.getPlayer(i).isHuman()]"],
                         env=dict(os.environ, CIV_DEV="1"), capture_output=True, text=True).stdout
    import re
    return ["%s=%s" % (i, LEVELS[t]) for i, t in re.findall(r"\((\d+), u?'(\w+)'\)", out) if t in LEVELS]


def setup(game, picks):
    seats = []
    for pick in picks:
        n, name = pick.split("=")
        if name == "builtin":
            continue
        if name not in MODELS:
            sys.exit("unknown model %r; pick one of: %s, builtin" % (name, ", ".join(MODELS)))
        seats.append(dict({"key": "%s%s" % (name, n), "player": int(n), "effort": "high", "effort_deep": "high"}, **MODELS[name]))
    if not seats:
        sys.exit("no AI seats picked")
    archive_last(game)
    d = os.path.join(HERE, "games", game)
    json.dump({"spectator_name": "V", "seats": seats}, open(os.path.join(d, "seats.json"), "w"), indent=1)
    subprocess.run([os.path.join(HERE, "multi.py"), game, "config"], check=True)
    print("\n".join("player %d (row %d): %s" % (s["player"], s["player"] + 1, s["display"]) for s in seats))
    print("Now: Custom Game, you in row 1, the rows above as AI, Launch; then ./newgame.py %s start" % game)


def start(game):
    if not os.path.exists(os.path.join(HERE, "games", game, "seats.json")):
        picks = picked_in_game()
        if not picks:
            sys.exit("no row is set to a model level in this game")
        seats = [dict({"key": "%s%s" % (m, n), "player": int(n), "effort": "high", "effort_deep": "high"}, **MODELS[m])
                 for n, m in (p.split("=") for p in picks)]
        json.dump({"spectator_name": "V", "seats": seats}, open(os.path.join(HERE, "games", game, "seats.json"), "w"), indent=1)
        print("picked in the game:", ", ".join("player %d = %s" % (x["player"], x["display"]) for x in seats))
    subprocess.run([os.path.join(HERE, "multi.py"), game, "start"], check=True)
    time.sleep(3)
    env = dict(os.environ, CIV_DEV="1")
    civ = os.path.join(HERE, "civ")
    subprocess.run([civ, "py", "import ClaudeBridge as B; B.forEachSeat(B.seatTurnStart, gc.getGame().getGameTurn()); result='ok'"], env=env)
    out = subprocess.run([civ, "py", "result=[(i, gc.getPlayer(i).getName(), gc.getPlayer(i).getCivilizationShortDescription(0), "
                          "gc.getPlayer(i).isHuman() and 'you' or (gc.getPlayer(i).isClaude() and 'model' or 'game AI')) "
                          "for i in range(gc.getMAX_CIV_PLAYERS()) if gc.getPlayer(i).isEverAlive()]"],
                         env=env, capture_output=True, text=True).stdout
    print("on screen:", out.strip())


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    if sys.argv[2] == "start":
        start(sys.argv[1])
    elif sys.argv[2] == "new":
        new(sys.argv[1])
    else:
        setup(sys.argv[1], sys.argv[2:])
