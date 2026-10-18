#!/usr/bin/env python3
"""Run a game of several AI leaders: the broker plus one loop per seat.

  multi.py <game-id> config     write the bridge's config.txt for this game's seats (before or after loading it)
  multi.py <game-id> start      start the broker and every seat's loop (logs in games/<id>/<seat>/loop.log)
  multi.py <game-id> stop       stop them
  multi.py <game-id> restart    restart the broker, then each seat's loop once it is between wake-ups (new code)
  multi.py <game-id> status     who is running, each seat's last wake-up

games/<id>/seats.json:
  {"seats": [{"key": "claude", "player": 1, "harness": "claude", "agent": ["claude", "-p", ...], "model": "opus",
              "system": "replace"},
             {"key": "gpt", "player": 2, "harness": "codex", "model": "gpt-6-astra", "effort": "high"},
             {"key": "deepseek", "player": 3, "harness": "pi", "model": "deepseek/deepseek-v4-pro-0813"}]}
Every seat gets the same playbook, tools, memory layout and wake-up brief; only the model and its harness differ.
"""
import json
import re
import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.expanduser("~/Library/Application Support/CrossOver/Bottles/%s/drive_c/claude_bridge"
                            % os.environ.get("CIV_BOTTLE", "civ4"))


def seats(game):
    return json.load(open(os.path.join(HERE, "games", game, "seats.json")))["seats"]


def pidfile(game, name):
    return os.path.join(HERE, "run", "%s-%s.pid" % (game, name))


def alive(path):
    try:
        os.kill(int(open(path).read()), 0)
        return True
    except (OSError, ValueError):
        return False


def spawn(game, name, cmd, log):
    os.makedirs(os.path.join(HERE, "run"), exist_ok=True)
    p = subprocess.Popen(cmd, cwd=HERE, stdout=open(log, "a"), stderr=subprocess.STDOUT, start_new_session=True)
    open(pidfile(game, name), "w").write(str(p.pid))
    return p.pid


def config(game):
    # the bridge reads config.txt live: these players are agents, each with its own files in claude_bridge/p<N>
    players = ",".join(str(s["player"]) for s in seats(game))
    with open(os.path.join(BRIDGE, "config.txt"), "w") as f:
        f.write("players = %s\nmulti = yes\n" % players)
    print("config.txt: players = %s" % players)


def manifest(game):
    """What this game ran on, for the paper: seats and models, file hashes, the game's own settings."""
    import hashlib
    h = lambda path: hashlib.sha256(open(path, "rb").read()).hexdigest()[:16] if os.path.exists(path) else None
    bts = os.path.join(os.path.dirname(BRIDGE), "GOG Games/Civilization IV Complete/Civ4/Beyond the Sword/Mods/CIVAI/Assets")
    files = {"bridge": os.path.join(HERE, "mod/CIVAI/Assets/Python/ClaudeBridge.py"), "playbook": os.path.join(HERE, "PLAYBOOK.md"),
             "loop": os.path.join(HERE, "loop.py"), "civ": os.path.join(HERE, "civ"), "mapview": os.path.join(HERE, "mapview.py"),
             "engine_dll": os.path.join(bts, "CvGameCoreDLL.dll")}
    env = dict(os.environ, CIV_DEV="1")
    code = ("g = CyGame(); m = CyMap()\n"
            "result = {'turn': g.getGameTurn(), 'max_turns': g.getMaxTurns(), 'speed': gc.getGameSpeedInfo(g.getGameSpeedType()).getType(),"
            " 'map_size': gc.getWorldInfo(m.getWorldSize()).getType(), 'map_w': m.getGridWidth(), 'map_h': m.getGridHeight(),"
            " 'difficulty': gc.getHandicapInfo(g.getHandicapType()).getType(),"
            " 'players': [(i, gc.getPlayer(i).getName(), gc.getPlayer(i).getCivilizationShortDescription(0), gc.getPlayer(i).isHuman()) "
            "for i in range(gc.getMAX_CIV_PLAYERS()) if gc.getPlayer(i).isEverAlive()]}")
    r = subprocess.run([os.path.join(HERE, "civ"), "py", code], capture_output=True, text=True, env=env)
    m = {"game": game, "written": time.strftime("%Y-%m-%d %H:%M:%S"), "seats": seats(game),
         "hashes": {k: h(v) for k, v in files.items()}, "game_settings": r.stdout.strip()}
    path = os.path.join(HERE, "games", game, "manifest.json")
    history = json.load(open(path)) if os.path.exists(path) else []
    history.append(m)   # one entry per start: a change of tools mid-game shows up here
    json.dump(history, open(path, "w"), indent=1)
    print("manifest: %d entries" % len(history))


def screen_names(game):
    """The names the screen shows (seats.json: "display" per seat, "spectator_name"): the video sees which model
    plays whom. The seats keep reading the leaders' own names (the bridge's realName; broker.neutral maps any
    screen name back), so no model learns who its rivals are. Kept in games/<id>/names.json."""
    conf = json.load(open(os.path.join(HERE, "games", game, "seats.json")))
    names = {s["player"]: s["display"] for s in conf["seats"] if s.get("display")}
    if conf.get("spectator_name"):
        names[conf.get("spectator", 0)] = conf["spectator_name"]
    if not names:
        return
    code = "\n".join(["p = gc.getPlayer(%d)\nif hasattr(p, 'claudeSetName'): p.claudeSetName(%r)" % (i, n)
                      for i, n in names.items()]) + \
        "\nimport ClaudeBridge as B\nresult = dict([(i, (gc.getPlayer(i).getName(), B.realName(i))) for i in %r])" % list(names)
    out = subprocess.run([os.path.join(HERE, "civ"), "py", code], capture_output=True, text=True,
                         env=dict(os.environ, CIV_DEV="1"), timeout=60).stdout
    pairs = dict((int(i), (a, b)) for i, a, b in re.findall(r"(\d+): \(u?'([^']*)', u?'([^']*)'\)", out))
    mapping = {a: b for i, (a, b) in pairs.items() if a != b and i != conf.get("spectator", 0)}
    json.dump(mapping, open(os.path.join(HERE, "games", game, "names.json"), "w"), indent=1)
    print("screen names:", ", ".join("%s = %s" % (a, b) for i, (a, b) in sorted(pairs.items())) or out.strip())


def start(game):
    config(game)
    manifest(game)
    screen_names(game)
    if not alive(pidfile(game, "broker")):
        spawn(game, "broker", [sys.executable, os.path.join(HERE, "broker.py"), game],
              os.path.join(HERE, "games", game, "broker.log"))
        time.sleep(1)
    for s in seats(game):
        if alive(pidfile(game, s["key"])):
            continue
        d = os.path.join(HERE, "games", game, s["key"])
        os.makedirs(d, exist_ok=True)
        pid = spawn(game, s["key"], [sys.executable, os.path.join(HERE, "loop.py"), "--game", game, "--seat", s["key"]],
                    os.path.join(d, "loop.log"))
        print("seat %s (player %d, %s %s): pid %d" % (s["key"], s["player"], s.get("harness"), s.get("model"), pid))


def stop(game):
    for name in [s["key"] for s in seats(game)] + ["broker"]:
        path = pidfile(game, name)
        if alive(path):
            os.killpg(int(open(path).read()), signal.SIGTERM)
            print("stopped", name)


def busy(path):
    # a seat's loop is in a wake-up while its agent (a child process) runs
    try:
        return subprocess.run(["pgrep", "-P", open(path).read().strip()], capture_output=True).returncode == 0
    except OSError:
        return False


def restart(game):
    # the broker at once (seats mid-wake get a short "not reachable"); each seat only between wake-ups:
    # a restart mid-wake would throw away that turn's work
    manifest(game)
    if alive(pidfile(game, "broker")):
        os.killpg(int(open(pidfile(game, "broker")).read()), signal.SIGTERM)
        time.sleep(1)
    spawn(game, "broker", [sys.executable, os.path.join(HERE, "broker.py"), game], os.path.join(HERE, "games", game, "broker.log"))
    todo = [s for s in seats(game)]
    while todo:
        for s in list(todo):
            path = pidfile(game, s["key"])
            if alive(path) and busy(path):
                continue
            if alive(path):
                os.killpg(int(open(path).read()), signal.SIGTERM)
                time.sleep(1)
            d = os.path.join(HERE, "games", game, s["key"])
            pid = spawn(game, s["key"], [sys.executable, os.path.join(HERE, "loop.py"), "--game", game, "--seat", s["key"]],
                        os.path.join(d, "loop.log"))
            print("seat %s restarted: pid %d" % (s["key"], pid), flush=True)
            todo.remove(s)
        time.sleep(5)


def status(game):
    for s in seats(game):
        d = os.path.join(HERE, "games", game, s["key"])
        log = os.path.join(d, "loop.log")
        last = open(log).read().strip().splitlines()[-1:] if os.path.exists(log) else ["(no log)"]
        print("%-10s %-8s %s" % (s["key"], "running" if alive(pidfile(game, s["key"])) else "stopped", last[0][:120]))
    print("%-10s %s" % ("broker", "running" if alive(pidfile(game, "broker")) else "stopped"))


if __name__ == "__main__":
    game, what = sys.argv[1], sys.argv[2]
    {"config": config, "start": start, "stop": stop, "restart": restart, "status": status}[what](game)
