#!/usr/bin/env python3
"""Go back to the start of an earlier turn: the game, every seat's memory and the logs the seats read.

When a bug changed the game (a tool lied, a wrong item went into a deal), the turn it happened is loaded again and
everything after it is set aside, so no seat remembers a future that never happened:

  - the seats stop (multi.py stop);
  - each seat's memory files (persona, ambitions, plan, secrets, chronicle, dossiers/) go back to the snapshot of
    its last wake-up before that turn (games/<id>/history/<seat>.git); its wake-up logs and log rows of that turn
    and later move to games/<id>/rewound/T###-<stamp>/<seat>/ (nothing is deleted);
  - each seat's loop state reads the bridge's logs from now on (the bridge marks the reload itself: a "rewind"
    event, after which the abandoned turns never happened);
  - the bridge handles its own files when the save loads (ClaudeBridge.rewindCheck: unit orders cleared, build
    lists from the save, open proposals closed, "rewind" markers in the logs); later saves move to the archive;
  - the turn's save is put first in the game's autosave list, so Load Game -> auto -> the newest file loads it;
  - games/<id>/rewinds.jsonl records the stretch of wall time that is no longer the game, for the video
    (~/youtube/rec/trim_idle.py --rewinds cuts it out of the recordings).

  rewind.py <game> <turn> [--reason "..."] [--go]      (without --go: only says what it would do)

Then: load the save in Civ (Single Player -> Load Game -> auto -> newest -> OK), `multi.py <game> start`, and check
`civ ping` shows the turn.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
sys.argv, _argv = sys.argv[:1], sys.argv   # loop.py reads sys.argv when imported
import loop   # noqa: E402  (memgit, snapshot_memory, MEMORY)
sys.argv = _argv

BRIDGE = os.path.expanduser("~/Library/Application Support/CrossOver/Bottles/%s/drive_c/claude_bridge"
                            % os.environ.get("CIV_BOTTLE", "civ4"))
AUTOSAVES = os.path.expanduser("~/Library/Application Support/CrossOver/Bottles/%s/drive_c/users/crossover/Documents/"
                               "My Games/Beyond the Sword/Saves/single/auto" % os.environ.get("CIV_BOTTLE", "civ4"))
LOGS = ("said.jsonl", "thoughts.jsonl", "commands.jsonl", "wake_stats.jsonl", "to_director.jsonl")

ap = argparse.ArgumentParser()
ap.add_argument("game")
ap.add_argument("turn", type=int)
ap.add_argument("--reason", default="")
ap.add_argument("--go", action="store_true")
ap.add_argument("--no-stop", action="store_true", help="the seats are already stopped")
a = ap.parse_args()

G = os.path.join(HERE, "games", a.game)
SAVES = os.path.join(G, "saves")
T = a.turn
STAMP = time.strftime("%Y%m%d-%H%M%S")
ARCH = os.path.join(G, "rewound", "T%03d-%s" % (T, STAMP))
done = []


def say(text):
    print(("  " if a.go else "  would: ") + text, flush=True)


def move(src, dst):
    if a.go:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)


def turn_of(name):
    m = re.match(r"T(\d{3})", os.path.basename(name))
    return m and int(m.group(1))


def row_turn(r):
    t = r.get("turn")
    try:
        return int(t)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ what to load
saves = sorted(glob.glob(os.path.join(SAVES, "T%03d_*.CivBeyondSwordSave" % T)), key=os.path.getmtime)
if not saves:
    sys.exit("no save of turn %d in %s" % (T, SAVES))
save = saves[-1]
FROM_WALL = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(save)))   # when turn T began
seats = json.load(open(os.path.join(G, "seats.json")))["seats"]
print("Rewind %s to the start of turn %d (it began %s): %s" % (a.game, T, FROM_WALL, os.path.basename(save)))
print("archive: %s" % ARCH)

# ------------------------------------------------------------------ stop the seats
if not a.no_stop:
    say("stop the seats and the broker")
    if a.go:
        subprocess.run([os.path.join(HERE, "multi.py"), a.game, "stop"], check=False)

# ------------------------------------------------------------------ later saves
later = [p for p in glob.glob(os.path.join(SAVES, "T*")) if (turn_of(p) or 0) > T]
say("set aside %d later saves (turns after %d)" % (len(later), T))
for p in later:
    move(p, os.path.join(ARCH, "saves", os.path.basename(p)))

# ------------------------------------------------------------------ each seat
for s in seats:
    key, d = s["key"], os.path.join(G, s["key"])
    if not os.path.isdir(d):
        continue
    print("seat %s (player %d)" % (key, s["player"]))
    g = loop.memgit(d)
    # the memory as it was after the seat's last wake-up before turn T
    commit = None
    for line in subprocess.run(g + ["log", "--format=%H %s"], cwd=d, capture_output=True, text=True).stdout.splitlines():
        h, msg = line.split(" ", 1)
        m = re.search(r"turn (\d+)", msg)
        if m and int(m.group(1)) < T:
            commit = (h, msg)
            break
    if not commit:
        say("no memory snapshot before turn %d: memory files left as they are" % T)
    else:
        say("memory back to '%s' (%s)" % (commit[1], commit[0][:8]))
        if a.go:
            for name in loop.MEMORY + ("dossiers",):
                p = os.path.join(d, name)
                there = subprocess.run(g + ["cat-file", "-e", "%s:%s" % (commit[0], name)], cwd=d).returncode == 0
                if os.path.exists(p):
                    move(p, os.path.join(ARCH, key, "memory", name))   # the snapshot's version comes back below
                if there:
                    subprocess.run(g + ["checkout", commit[0], "--", name], cwd=d, check=True)
    # wake-up logs of turn T and later
    wakes = [p for p in glob.glob(os.path.join(d, "wakes", "T*.md")) if (turn_of(p) or 0) >= T]
    say("set aside %d wake-up logs" % len(wakes))
    for p in wakes:
        move(p, os.path.join(ARCH, key, "wakes", os.path.basename(p)))
    # log rows of turn T and later (by turn when the row has one, else by wall time)
    for name in LOGS:
        p = os.path.join(d, name)
        if not os.path.exists(p):
            continue
        keep, gone = [], []
        for line in open(p):
            try:
                r = json.loads(line)
            except ValueError:
                keep.append(line)
                continue
            t = row_turn(r)
            late = (t >= T) if t is not None else (r.get("wall", "") >= FROM_WALL)
            (gone if late else keep).append(line)
        if gone:
            say("%s: set aside %d rows" % (name, len(gone)))
            if a.go:
                os.makedirs(os.path.join(ARCH, key), exist_ok=True)
                open(os.path.join(ARCH, key, name), "w").writelines(gone)
                open(p, "w").writelines(keep)
    # the loop reads the bridge's logs from here on; the turn's own wake-up comes from the gate
    sp = os.path.join(d, "loop_state.json")
    if os.path.exists(sp):
        st = json.load(open(sp))
        ev = os.path.join(BRIDGE, "p%d" % s["player"], "events.jsonl")
        ch = os.path.join(BRIDGE, "p%d" % s["player"], "chat.jsonl")
        new = dict(st, events_pos=os.path.getsize(ev) if os.path.exists(ev) else 0,
                   chat_pos=os.path.getsize(ch) if os.path.exists(ch) else 0, turn_woken=None)
        for k in ("audiences", "refusals", "cut_off"):
            new.pop(k, None)
        if isinstance(st.get("last_council"), int) and st["last_council"] >= T:
            new["last_council"] = T - 1
        if st.get("fallen") is not None and st["fallen"] >= T:
            for k in ("fallen", "fall_done", "end_kind"):
                new.pop(k, None)
        say("loop state: read the bridge from now on%s" % (", no longer fallen/ended" if "fallen" in st and
                                                          "fallen" not in new else ""))
        if a.go:
            os.makedirs(os.path.join(ARCH, key), exist_ok=True)
            shutil.copy2(sp, os.path.join(ARCH, key, "loop_state.json"))
            json.dump(new, open(sp, "w"))
    if a.go:
        loop.snapshot_memory(d, "rewind to turn %d" % T)

# ------------------------------------------------------------------ the save first in the load list
name = re.sub(r"^T\d{3}_", "", os.path.basename(save))
say("put %s first in the autosave list" % name)
if a.go:
    dst = os.path.join(AUTOSAVES, name)
    shutil.copy2(save, dst)
    os.utime(dst, None)   # newest: Load Game -> auto shows it first

# ------------------------------------------------------------------ the record
row = {"turn": T, "from_wall": FROM_WALL, "to_wall": time.strftime("%Y-%m-%d %H:%M:%S"), "save": os.path.basename(save),
       "archive": os.path.relpath(ARCH, G), "reason": a.reason}
say("record in rewinds.jsonl: %s" % json.dumps(row))
if a.go:
    with open(os.path.join(G, "rewinds.jsonl"), "a") as f:
        f.write(json.dumps(row) + "\n")
    print("\nDone. Now: load the save in Civ (Single Player -> Load Game -> auto -> newest -> OK), then\n"
          "  ./multi.py %s start\n  ./civ ping      (turn %d)\n"
          "and cut the abandoned stretch from the recordings: ~/youtube/rec/trim_idle.py <dirs> --rewinds --go" % (a.game, T))
else:
    print("\n(report only; --go to do it)")
