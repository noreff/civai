#!/usr/bin/env python3
"""Director's watch: prints one line per problem in a running CIVAI game, nothing otherwise.

  - a wake-up (claude_wake / player_waiting) the playing agent hasn't answered for a while
  - `civ py` code that looks at other players (possible peeking past the fog of war)
  - errors in the bridge log

Usage: director_watch.py [--stuck-seconds N]   (meant to run under a monitor; never exits)
"""
import json
import os
import re
import subprocess
import sys
import time

BRIDGE = os.path.expanduser("~/Library/Application Support/CrossOver/Bottles/civ4/drive_c/claude_bridge")
EVENTS, EXEC_LOG, BRIDGE_LOG = (os.path.join(BRIDGE, n) for n in ("events.jsonl", "exec.log", "bridge.log"))
STUCK = int(sys.argv[sys.argv.index("--stuck-seconds") + 1]) if "--stuck-seconds" in sys.argv else 300


def my_player():
    try:
        out = subprocess.run([os.path.expanduser("~/civai/civ"), "ping"], capture_output=True, text=True, timeout=30).stdout
        return int(re.search(r"Claude = player (\d+)", out).group(1))
    except Exception:
        return None


def follow(path):
    """Generator of new lines appended to path (starts at the end; survives the file appearing later)."""
    pos = os.path.getsize(path) if os.path.exists(path) else 0
    while True:
        if os.path.exists(path):
            size = os.path.getsize(path)
            if size < pos:
                pos = 0
            if size > pos:
                with open(path, "rb") as f:
                    f.seek(pos)
                    data = f.read()
                pos += len(data)
                for line in data.decode("utf-8", "replace").splitlines():
                    yield line
                continue
        yield None


def say(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def peeking(code, me):
    if me is None:
        return None
    for m in re.finditer(r"getPlayer\(\s*(\d+)\s*\)", code):
        if int(m.group(1)) != me:
            return "touches player %s" % m.group(1)
    if re.search(r"range\(\s*gc\.getMAX_(CIV_)?PLAYERS|getPlayer\(\s*[a-z_]\w*\s*\)", code):
        return "loops over players"
    if re.search(r"isVisible|plotByIndex|getNumUnits", code) and "ClaudeBridge" not in code:
        return "scans the map"
    return None


def main():
    me = my_player()
    say("director watch started (agent plays player %s, stuck after %ds)" % (me, STUCK))
    ev, ex, bl = follow(EVENTS), follow(EXEC_LOG), follow(BRIDGE_LOG)
    pending = None          # (kind, turn, since) of an unanswered wake-up
    warned = False
    block = []
    while True:
        busy = False
        for line in iter(lambda: next(ev), None):
            busy = True
            try:
                d = json.loads(line)
            except ValueError:
                continue
            k = d.get("kind")
            if k in ("claude_wake", "player_waiting") and pending is None:
                pending, warned = (k, d.get("turn"), time.time()), False
            elif k in ("claude_ready", "auto_ready"):
                pending = None
        for line in iter(lambda: next(ex), None):
            busy = True
            if line.startswith("---- "):
                code = "\n".join(block)
                why = peeking(code, me)
                if why:
                    say("PEEK? civ py %s: %s" % (why, code.strip().replace("\n", " | ")[:300]))
                block = []
            else:
                block.append(line)
        for line in iter(lambda: next(bl), None):
            busy = True
            if "FAILED" in line or "Traceback" in line:
                say("BRIDGE ERROR: " + line.strip()[:300])
        if pending and not warned and time.time() - pending[2] > STUCK:
            say("STUCK: %s on turn %s unanswered for %d min" % (pending[0], pending[1], STUCK // 60))
            warned = True
        if not busy:
            time.sleep(2)


if __name__ == "__main__":
    main()
