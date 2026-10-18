#!/usr/bin/env python3
"""Cut a short clip for every moment the studio marked (games/<id>/clips.jsonl) out of the continuous recording.

The studio marks each big event with its wall time; this finds the game's stream file that holds that moment now
(files are named by their real start time, also after trims) and copies the stretch around it, without
re-encoding: 20 s before an event and 10 s after it (an overview: 2 s before, 6 s after). Moments inside a
stretch a rewind threw away are skipped, and so are files still being written (run it again later).

  clips.py <game-id> [--before S] [--after S]      -> games/<id>/media/clips/<the shot's name>.mp4
"""
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
STREAMS = os.path.expanduser("~/youtube/raw/civai/streams")


def stamp(s):
    return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def streams():
    out = []
    for f in glob.glob(os.path.join(STREAMS, "*_game*.mp4")):
        m = re.match(r"(\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d)_", os.path.basename(f))
        if m:
            out.append((time.mktime(time.strptime(m.group(1), "%Y-%m-%d_%H-%M-%S")), f))
    return sorted(out)


def main(game, before=20.0, after=10.0):
    g = os.path.join(HERE, "games", game)
    rows = [json.loads(l) for l in open(os.path.join(g, "clips.jsonl")) if l.strip()]
    gone = []
    if os.path.exists(os.path.join(g, "rewinds.jsonl")):
        gone = [(stamp(r["from_wall"]), stamp(r["to_wall"])) for r in map(json.loads, open(os.path.join(g, "rewinds.jsonl")))]
    out_dir = os.path.join(g, "media", "clips")
    os.makedirs(out_dir, exist_ok=True)
    files = streams()
    made = skipped = 0
    for r in rows:
        t = stamp(r["wall"])
        name = os.path.splitext(os.path.basename(r.get("shot") or ""))[0] or "T%03d-%s" % (r.get("turn") or 0, r["kind"])
        dst = os.path.join(out_dir, name + ".mp4")
        if os.path.exists(dst):
            continue
        if any(a <= t <= b for a, b in gone):
            print("skip (thrown away by a rewind): %s" % r["what"])
            skipped += 1
            continue
        b, a = (2.0, 6.0) if r["kind"] == "overview" else (before, after)
        cand = [(t0, f) for t0, f in files if t0 <= t]
        if not cand:
            print("no recording holds %s (%s)" % (r["what"], r["wall"]))
            continue
        t0, f = cand[-1]
        if time.time() - os.path.getmtime(f) < 900:
            print("still being written, later: %s" % r["what"])
            continue
        dur = duration(f) or 0
        at = t - t0
        if at > dur:
            print("in a recording gap: %s (%s)" % (r["what"], r["wall"]))
            continue
        s, e = max(0.0, at - b), min(dur, at + a)
        res = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "%.2f" % s, "-to", "%.2f" % e, "-i", f, "-map", "0:v",
                              "-c", "copy", "-avoid_negative_ts", "make_zero", dst])
        if res.returncode == 0 and os.path.exists(dst):
            made += 1
            print("clip %s: %s (%s %.0f-%.0f s)" % (os.path.basename(dst), r["what"], os.path.basename(f), s, e))
    print("%d clips made, %d skipped (rewinds), in %s" % (made, skipped, out_dir))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], float(a[a.index("--before") + 1]) if "--before" in a else 20.0,
         float(a[a.index("--after") + 1]) if "--after" in a else 10.0)
