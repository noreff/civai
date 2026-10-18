# /// script
# requires-python = ">=3.11"
# dependencies = ["obsws-python==1.8.0", "pyobjc-framework-Quartz"]
# ///
"""The studio: films a CIVAI game for the video while it plays.

On every big event of the game (a war declared or ended, a city taken or razed, a wonder or project built, a
spaceship launched, a religion founded, a civilization eliminated) it:
  - points the camera at the place (the bridge's director camera already jumps to captures and battles),
  - takes a screenshot of the game window a few seconds later  -> games/<id>/media/shots/,
  - saves OBS's replay buffer (the last 30 s) a few seconds after that -> games/<id>/media/clips/,
  - writes one line to games/<id>/clips.jsonl: what happened, turn, wall time, files, and where it is in the
    continuous recording (the stream file and the second in it), so the edit can find every moment.
Every 10 turns it also takes an overview shot of the map.

  uv run studio.py [<game-id>]      (default: games/CURRENT; runs until stopped)
"""
import glob
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

import Quartz
import obsws_python as obs

HERE = os.path.dirname(os.path.realpath(__file__))
GAME = sys.argv[1] if len(sys.argv) > 1 else open(os.path.join(HERE, "games", "CURRENT")).read().strip()
G = os.path.join(HERE, "games", GAME)
BRIDGE = os.path.expanduser("~/Library/Application Support/CrossOver/Bottles/%s/drive_c/claude_bridge"
                            % os.environ.get("CIV_BOTTLE", "civ4"))
SHOTS, CLIPS = os.path.join(G, "media", "shots"), os.path.join(G, "media", "clips")
STREAMS = os.path.expanduser("~/youtube/raw/civai/streams")
SHOT_AFTER, CLIP_AFTER = 4, 10        # seconds after the event: the camera has arrived; the clip holds 20 s before
OVERVIEW_EVERY = 10

for d in (SHOTS, CLIPS):
    os.makedirs(d, exist_ok=True)
env = dict(l.split("=", 1) for l in pathlib.Path.home().joinpath("youtube/rec/.env").read_text().split("\n") if "=" in l)
cl = obs.ReqClient(host="localhost", port=int(env.get("OBS_WS_PORT", 4455)), password=env["OBS_WS_PASSWORD"], timeout=30)


def say(text):
    print(time.strftime("%H:%M:%S"), text, flush=True)


def civ(*args):
    e = dict(os.environ, CIV_DEV="1")
    return subprocess.run([os.path.join(HERE, "civ")] + list(args), capture_output=True, text=True, env=e, timeout=60).stdout


def civ_window():
    wins = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
    for w in wins:
        if "Beyond The Sword" in (w.get("kCGWindowName") or "") and w.get("kCGWindowLayer", 1) == 0:
            return w["kCGWindowNumber"]
    return None


def shot(name):
    wid = civ_window()
    if not wid:
        return None
    path = os.path.join(SHOTS, name + ".png")
    r = subprocess.run(["screencapture", "-x", "-o", "-l%d" % wid, path], capture_output=True)
    return path if r.returncode == 0 and os.path.exists(path) else None


def replay_buffer_on():
    try:
        if not cl.get_replay_buffer_status().output_active:
            cl.start_replay_buffer()
            say("replay buffer started")
        return True
    except Exception as e:
        say("no replay buffer (%s): clips will come from the recording" % str(e)[:80])
        return False


def clip(name):
    try:
        cl.save_replay_buffer()
        time.sleep(3)
        src = cl.get_last_replay_buffer_replay().saved_replay_path
    except Exception as e:
        say("clip failed: %s" % str(e)[:120])
        return None
    if not src or not os.path.exists(src):
        return None
    dst = os.path.join(CLIPS, name + os.path.splitext(src)[1])
    shutil.move(src, dst)
    return dst


def in_stream(wall):
    # the continuous recording: the game's stream file holding this moment, and the second in it
    best = None
    for f in glob.glob(os.path.join(STREAMS, "*_game*.mp4")):
        m = re.match(r"(\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d)_", os.path.basename(f))
        if not m:
            continue
        t0 = time.mktime(time.strptime(m.group(1), "%Y-%m-%d_%H-%M-%S"))
        if t0 <= wall and (best is None or t0 > best[1]):
            best = (f, t0)
    return best and {"file": os.path.basename(best[0]), "second": round(wall - best[1], 1)}


def model_names():
    # the screen calls each leader by the model playing it: "Claude Sonnet · Asoka"
    try:
        return {v: k for k, v in json.load(open(os.path.join(G, "names.json"))).items() if k != v}
    except (OSError, ValueError):
        return {}


def on_screen(text):
    for leader, model in model_names().items():
        text = re.sub(r"\b%s(?: \([^)]*\))?" % re.escape(leader), "%s \u00b7 %s" % (model, leader), text)
    return text


def caption(text):
    civ("py", "import ClaudeBridge as B; B.caption(%r); result = 'ok'" % on_screen(text))


def look_at(x, y):
    civ("py", "import ClaudeBridge as B; B.cameraHold(%d, %d); result = 'ok'" % (int(x), int(y)))


def city_xy(name):
    out = civ("py", "r = None\nfor i in range(gc.getMAX_CIV_PLAYERS()):\n"
                    "    (c, it) = gc.getPlayer(i).firstCity(False)\n"
                    "    while c and not c.isNone():\n"
                    "        if c.getName() == %r:\n            r = (c.getX(), c.getY())\n"
                    "        (c, it) = gc.getPlayer(i).nextCity(it, False)\nresult = r" % name)
    m = re.search(r"\((\d+), (\d+)\)", out)
    return m and (int(m.group(1)), int(m.group(2)))


def city_owner(name):
    out = civ("py", "import ClaudeBridge as B\nr = None\nfor i in range(gc.getMAX_CIV_PLAYERS()):\n"
                    "    (c, it) = gc.getPlayer(i).firstCity(False)\n"
                    "    while c and not c.isNone():\n"
                    "        if c.getName() == %r:\n            r = '%%s (%%s)' %% (B.realName(i), gc.getPlayer(i).getCivilizationShortDescription(0))\n"
                    "        (c, it) = gc.getPlayer(i).nextCity(it, False)\nresult = r" % name)
    m = re.search(r"u?'([^']+)'", out)
    return m and m.group(1)


def capital_xy(leader):
    # by the leader's real name: the game's own name now shows the model playing it
    out = civ("py", "import ClaudeBridge as B\nr = None\nfor i in range(gc.getMAX_CIV_PLAYERS()):\n"
                    "    p = gc.getPlayer(i)\n"
                    "    if p.isAlive() and %r.startswith(B.realName(i)) and not p.getCapitalCity().isNone():\n"
                    "        r = (p.getCapitalCity().getX(), p.getCapitalCity().getY())\nresult = r" % leader)
    m = re.search(r"\((\d+), (\d+)\)", out)
    return m and (int(m.group(1)), int(m.group(2)))


WONDERS = set()


def wonders():
    out = civ("py", "result = [gc.getBuildingInfo(b).getType() for b in range(gc.getNumBuildingInfos()) "
                    "if gc.getBuildingClassInfo(gc.getBuildingInfo(b).getBuildingClassType()).getMaxGlobalInstances() == 1]")
    return set(re.findall(r"BUILDING_[A-Z_]+", out))


def nice(t):
    return re.sub(r"^(BUILDING|PROJECT|RELIGION)_", "", t or "").replace("_", " ").title()


def moment(e):
    """(key, kind, one line, where to look) for the events worth filming; None for the rest."""
    k = e.get("kind")
    if k == "city_changed_hands":
        # conquest 0: no army took it (its people joined the stronger culture, or it changed hands in a deal)
        how = "%s takes %s from %s" if e.get("conquest", 1) else "%s gains %s: it leaves %s without a fight"
        return ("cap:%s:%s" % (e.get("name"), e.get("turn")), e.get("conquest", 1) and "capture" or "flip",
                how % (e.get("to"), e.get("name"), e.get("from")), (e.get("x"), e.get("y")))
    if k == "city_razed":
        return ("raze:%s:%s" % (e.get("name"), e.get("turn")), "razed", "%s is razed" % e.get("name"), None)
    if k == "war_declared":
        return ("war:%s:%s:%s" % (e.get("team"), e.get("against"), e.get("turn")), "war",
                "%s declares war on %s" % (e.get("team"), e.get("against")), ("leader", e.get("team")))
    if k == "peace_made":
        pair = sorted([e.get("team") or "", e.get("against") or ""])
        return ("peace:%s:%s:%s" % (pair[0], pair[1], e.get("turn")), "peace", "%s and %s make peace" % tuple(pair),
                ("leader", e.get("team")))
    if k == "building_built" and e.get("building") in WONDERS:
        owner = e.get("owner")
        if not owner or "unknown" in owner:
            owner = city_owner(e.get("city")) or owner   # the seat that saw it may not have met the builder
        return ("wonder:%s" % e.get("building"), "wonder", "%s builds %s in %s" % (owner, nice(e.get("building")),
                e.get("city")), ("city", e.get("city")))
    if k == "project_built":
        return ("project:%s:%s:%s" % (e.get("owner"), e.get("project"), e.get("turn")), "project",
                "%s completes %s" % (e.get("owner"), nice(e.get("project"))), ("leader", e.get("owner")))
    if k == "spaceship_launched" and e.get("by") != "us":
        return ("launch:%s" % e.get("by"), "launch", "%s launches a spaceship" % e.get("by"), ("leader", e.get("by")))
    if k == "religion_founded" and e.get("by") != "an unknown civilization":
        return ("religion:%s" % e.get("religion"), "religion", "%s founds %s" % (e.get("by"), nice(e.get("religion"))),
                ("leader", e.get("by")))
    if k == "proposal" and "Diplomatic Victory" in (e.get("text") or "") and "Requires" in (e.get("text") or ""):
        # the United Nations (or the Apostolic Palace) puts a diplomatic victory to the vote
        return ("dvote:%s" % e.get("turn"), "vote", "The world votes: a diplomatic victory is on the table", None)
    if k == "first_contact":
        return None
    return None


def winner():
    out = civ("py", "import ClaudeBridge as B\ng = gc.getGame()\nw = g.getWinner()\n"
                    "result = w >= 0 and '%s|%s' % (B.realName(gc.getTeam(w).getLeaderID()), "
                    "gc.getVictoryInfo(g.getVictory()).getDescription()) or ''")
    m = re.search(r"'([^'|]+)\|([^']+)'", out)
    return m and (m.group(1), m.group(2))


def follow():
    pos = {}
    for p in glob.glob(os.path.join(BRIDGE, "p*", "events.jsonl")):
        pos[p] = os.path.getsize(p)
    return pos


def new_events(pos):
    out = []
    for p in glob.glob(os.path.join(BRIDGE, "p*", "events.jsonl")):
        size = os.path.getsize(p)
        start = pos.get(p, 0)
        if size < start:
            start = 0
        if size > start:
            with open(p, errors="ignore") as f:
                f.seek(start)
                for line in f.read().splitlines():
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
        pos[p] = size
    return out


def alive_now():
    rows = []
    try:
        for line in open(os.path.join(BRIDGE, "truth.jsonl")):
            rows.append(json.loads(line))
    except (OSError, ValueError):
        return None, {}
    if not rows:
        return None, {}
    last = rows[-1]
    return last.get("turn"), {p.get("name"): p.get("alive") for p in last.get("civs", []) if isinstance(p, dict) and p.get("agent")}


def record(kind, turn, text, files):
    wall = time.time()
    row = {"kind": kind, "turn": turn, "wall": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(wall)), "what": text,
           "stream": in_stream(wall)}
    row.update(files)
    with open(os.path.join(G, "clips.jsonl"), "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    say("%s T%s: %s %s" % (kind, turn, text, " ".join("%s=%s" % (k, os.path.basename(v)) for k, v in files.items() if v)))


def main():
    global WONDERS
    WONDERS = wonders()
    buffer = replay_buffer_on()
    pos = follow()
    seen, alive, last_overview = set(), {}, None
    won, won_check = False, 0
    say("studio on %s: %d wonders known, replay buffer %s" % (GAME, len(WONDERS), buffer and "on" or "off"))
    while True:
        todo = []
        for e in new_events(pos):
            m = moment(e)
            if m and m[0] not in seen:
                seen.add(m[0])
                todo.append((m, e.get("turn")))
        turn, now_alive = alive_now()
        for name, a in now_alive.items():
            if alive.get(name) and not a:
                todo.append((("elim:%s" % name, "eliminated", "%s is eliminated" % name, None), turn))
        alive.update(now_alive)
        if time.time() - won_check > 15 and not won:
            won_check = time.time()
            w = winner()
            if w:
                won = True
                todo.append((("win", "victory", "%s wins: %s victory" % w, ("leader", w[0])), turn))
        if isinstance(turn, int) and turn % OVERVIEW_EVERY == 0 and turn != last_overview:
            last_overview = turn
            record("overview", turn, "the map at turn %d" % turn, {"shot": shot("T%03d-overview" % turn)})
        for (key, kind, text, where), t in todo:
            try:
                if where and where[0] == "leader":
                    xy = capital_xy(where[1] or "")
                elif where and where[0] == "city":
                    xy = city_xy(where[1] or "")
                else:
                    xy = where
                if xy and kind not in ("capture", "flip"):   # the bridge's camera already flies to captures
                    look_at(*xy)
                caption(text)
                stem = "T%03d-%s-%s" % (t or 0, kind, re.sub(r"[^A-Za-z0-9]+", "-", text)[:60].strip("-"))
                time.sleep(SHOT_AFTER)
                files = {"shot": shot(stem)}
                if buffer:
                    time.sleep(max(0, CLIP_AFTER - SHOT_AFTER))
                    files["clip"] = clip(stem)
                record(kind, t, text, files)
            except Exception as ex:
                say("FAILED on %s: %s" % (text, ex))
        time.sleep(2)


if __name__ == "__main__":
    main()
