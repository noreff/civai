"""Timelines: loading an older save starts a new timeline from that turn.

The bridge's logs (events.jsonl, chat.jsonl) are append-only, so after a reload they still hold
what happened in the abandoned later turns. A rewind marker (event "rewind" with to_turn; a chat
row with rewind_to) says where the new timeline starts: everything logged before the marker for
that turn or later never happened in the game being played now.
"""
import json
import os


def event_rewind(row):
    return row.get("to_turn") if row.get("kind") == "rewind" else None


def chat_rewind(row):
    return row.get("rewind_to")


def current(rows, marker, keep_markers=False):
    # the rows of the timeline being played now, in order
    out = []
    for r in rows:
        t = marker(r)
        if t is not None:
            out = [x for x in out if not isinstance(x.get("turn"), int) or x["turn"] < t]
            if not keep_markers:
                continue
        out.append(r)
    return out


def read(path, marker, keep_markers=False):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return current(rows, marker, keep_markers)


def rewinds(events_path):
    # (wall time "YYYY-mm-dd HH:MM:SS", to_turn) of every reload, for files that only have a modification time
    if not os.path.exists(events_path):
        return []
    out = []
    with open(events_path) as f:
        for line in f:
            if '"rewind"' in line:
                r = json.loads(line)
                if r.get("kind") == "rewind" and r.get("wall"):
                    out.append((r["wall"], r["to_turn"]))
    return out
