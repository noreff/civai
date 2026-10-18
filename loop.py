#!/usr/bin/env python3
"""CIVAI loop: plays a civ with any model, one fresh call per wake-up.

Nothing piles up in a model's context: every wake-up gets the playbook, the game's
memory files and a fresh brief (state + what happened since the last wake-up), the
model acts through `civ` commands and updates its files, and the call ends.

  ./loop.py                 play with the model command from loop.json ("agent")
  ./loop.py --once          handle one wake-up now and exit (for testing)
  ./loop.py --dry-run       print the prompt of the next wake-up and exit (--v2: the new prompt; --system: its system part)

loop.json (next to this file):
  {"agent": ["claude", "-p", "{prompt}", ...], "timeout_minutes": 15}
"{prompt}" is replaced by the prompt; without it the prompt goes to stdin.
Each wake-up is logged for the video in games/<id>/wakes/.
"""
import json
import os
import re
import subprocess
import sys
import time

import timeline

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "system_prompt.md")
BRIDGE = os.path.expanduser("~/Library/Application Support/CrossOver/Bottles/%s/drive_c/claude_bridge" % os.environ.get("CIV_BOTTLE", "civ4"))
EVENTS = os.path.join(BRIDGE, "events.jsonl")
CHAT = os.path.join(BRIDGE, "chat.jsonl")
WAKE_KINDS = ("message_from_player", "claude_wake", "player_waiting", "deal_done", "deal_declined",
              "deal_failed", "native_deal", "proposal")
NOISE = ("auto_ready", "claude_ready", "my_turn_begins", "player_turn_begins", "combat_animal")
MEMORY = ("persona.md", "ambitions.md", "plan.md", "secrets.md", "chronicle.md")
CHAT_LINES = 30             # recent chat shown on every wake-up, new lines marked
AMBITIONS_STALE = 30        # turns: past this, the brief says the ambitions haven't been revised
MEMORY_TOKENS_WARN = 12000  # past this, the brief asks the agent to trim its memory files
GATHER_SECONDS = 4          # a burst of events (chat + turn start...) becomes one wake-up
SYSTEM_FILE_V2 = os.path.join(HERE, "out", "system_prompt_v2.md")
LOOP_SKIP = ("## Start of a session",)   # playbook sections for a person starting a session by hand, not the loop
BRIEF_CHAT_LINES = 12       # v2: chat shown (at least the last 5 turns' worth, up to this many lines)
BRIEF_CHAT_TURNS = 5
BRIEF_EVENTS = 40           # v2: events since the last wake-up, the rest behind `civ events`
SHADOW = "_shadow"          # games/_shadow: the test copy a shadow run plays in (read-only to the game)


SEAT = {}   # a game of several agents: this loop plays one seat (see seats.json, broker.py)


def seat_setup(game, key):
    """Play seat `key` of games/<game>/seats.json: its player number, its bridge files (claude_bridge/p<N>),
    its memory folder (games/<game>/<key>), its model and harness; the agent runs sandboxed and reaches
    the game only through the broker."""
    global EVENTS, CHAT
    conf = json.load(open(os.path.join(HERE, "games", game, "seats.json")))
    seat = next(x for x in conf["seats"] if x["key"] == key)
    SEAT.update(seat, game=game)
    EVENTS = os.path.join(BRIDGE, "p%d" % seat["player"], "events.jsonl")
    CHAT = os.path.join(BRIDGE, "p%d" % seat["player"], "chat.jsonl")
    os.environ["CIV_PLAYER"] = str(seat["player"])          # the loop's own lookups act as this seat
    os.environ["CIV_GAME"] = "%s/%s" % (game, key)


def seat_dir():
    d = os.path.join(HERE, "games", SEAT["game"], SEAT["key"])
    ign = os.path.join(d, ".gitignore")
    if os.path.isdir(d) and not os.path.exists(ign):
        # the seat's memory history keeps notes and logs, never tokens, logins or harness sessions
        open(ign, "w").write(".seat_token\n.system_prompt.md\n.codex-home/\n.pi-sessions/\n.last_thought\n")
    return d


def sandbox_profile():
    """What a seat's agent may not touch: the game's raw files, the other seats, every transcript and note
    that knows more than its civilization does. It reaches the game only through `civ` (the broker)."""
    home = os.path.expanduser("~")
    own = seat_dir()
    claude_own = os.path.join(home, ".claude", "projects", own.replace("/", "-").replace(".", "-"))
    deny = [os.path.join(home, "Library/Application Support/CrossOver"), os.path.join(HERE, "games"),
            os.path.join(HERE, "paper"), os.path.join(HERE, "out"), os.path.join(HERE, "docs"),
            os.path.join(home, ".claude", "projects"), os.path.join(home, ".codex"),
            os.path.join(home, ".pi", "agent", "sessions"), os.path.join(home, "research"),
            "/private/tmp/claude-501/-Users-volod"]   # the director's own sessions; a seat's Claude keeps its temp dir
    allow = [own, claude_own]
    q = lambda p: '(subpath "%s")' % os.path.realpath(p).replace('"', '\\"')
    text = "(version 1)\n(allow default)\n(deny file-read* file-write* %s)\n(allow file-read* file-write* %s)\n" % (
        " ".join(q(p) for p in deny), " ".join(q(p) for p in allow))
    # the folders above the seat's own: their attributes only (tools resolve full paths), never a listing or a file
    up, parents = os.path.realpath(own), []
    while os.path.dirname(up) != up:
        up = os.path.dirname(up)
        parents.append(up)
    text += "(allow file-read-metadata %s)\n" % " ".join('(literal "%s")' % x for x in parents)
    if SEAT.get("harness") == "codex":
        # only the GPT seat may use the ChatGPT login file, and nothing else in ~/.codex
        text += '(allow file-read* file-write* (literal "%s"))\n' % os.path.realpath(os.path.join(home, ".codex", "auth.json"))
    path = os.path.join(HERE, "run", "sandbox-%s.sb" % SEAT["key"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)
    return path


def civ(*args):
    r = subprocess.run([os.path.join(HERE, "civ")] + list(args), capture_output=True, text=True, timeout=180)
    return (r.stdout + r.stderr).strip()


def game_dir():
    if SEAT:
        d = seat_dir()
        os.makedirs(os.path.join(d, "wakes"), exist_ok=True)
        return "%s/%s" % (SEAT["game"], SEAT["key"]), d
    gid = open(os.path.join(HERE, "games", "CURRENT")).read().strip()
    d = os.path.join(HERE, "games", gid)
    os.makedirs(os.path.join(d, "wakes"), exist_ok=True)
    return gid, d


def load_state(d):
    try:
        return json.load(open(os.path.join(d, "loop_state.json")))
    except (OSError, ValueError):
        return {"events_pos": os.path.getsize(EVENTS) if os.path.exists(EVENTS) else 0,
                "chat_pos": os.path.getsize(CHAT) if os.path.exists(CHAT) else 0, "wakes": 0}


def save_state(d, st):
    tmp = os.path.join(d, "loop_state.json.tmp")
    json.dump(st, open(tmp, "w"))
    os.replace(tmp, os.path.join(d, "loop_state.json"))


def read_from(path, pos):
    if not os.path.exists(path):
        return [], pos
    with open(path, "rb") as f:
        f.seek(pos)
        data = f.read()
    rows = []
    for line in data.decode("utf-8", "replace").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows, pos + len(data)


_human = []


def human_name():
    # the human leader's name, as the game shows it ("V (India)"), so the brief never says "the human"
    gid = os.path.basename(game_dir()[1])
    if not _human or _human[0][0] != gid:   # per game: a new game has a new human leader
        m = re.search(r"^  (.+?) of (.+?) \[HUMAN\]", civ("status"), re.M)
        if m:
            del _human[:]
            _human.append((gid, "%s (%s)" % (m.group(1), m.group(2))))
    return _human[0][1] if _human else "the human leader"


def fmt_event(e):
    skip = ("kind", "turn", "year", "time")
    rest = ", ".join("%s=%s" % (k, v) for k, v in e.items() if k not in skip)
    return "T%s %s %s" % (e.get("turn"), e.get("kind"), rest)


def game_turn():
    # the turn the game is on now (after loading an older save, files can hold later turns)
    m = re.search(r"Turn (\d+),", civ("ping"))
    return int(m.group(1)) if m else 10 ** 6


def brief(events, chat, reasons):
    parts = ["# Wake-up: " + "; ".join(reasons), "",
             "## Since your last wake-up", ""]
    shown = [fmt_event(e) for e in events if e.get("kind") not in NOISE]
    parts += shown[-100:] or ["(no game events)"]
    parts += ["", "## Chat (the last %d lines; NEW = written to you since your last wake-up)" % CHAT_LINES, ""]
    new_ids = set(json.dumps(c, sort_keys=True) for c in chat)
    recent = timeline.read(CHAT, timeline.chat_rewind)   # not the abandoned turns of a reload
    parts += ["%sT%s %s: %s" % ("NEW " if json.dumps(c, sort_keys=True) in new_ids and c.get("from") != "claude" else "    ", c.get("turn"),
              "you" if c.get("from") == "claude" else human_name(), c.get("text")) for c in recent[-CHAT_LINES:]] or ["(none)"]
    parts += ["", "## Your last wake-ups (what you did)", ""]
    parts += recent_wakes(3) or ["(none)"]
    status = civ("status")
    parts += ambitions_note(status)
    parts += ["", "## State now", "", status, "", civ("research"), "", civ("proposals"), "", civ("offers"), "",
              "### Ongoing deals", "", civ("deals"), "", "### Budget", "", civ("budget"), "", civ("gate")]
    parts += ["", "## Map of my land", "", my_land_map()]
    return "\n".join(parts)


def ambitions_note(status):
    # a nudge, like the memory-size one: goals nobody revisits stop driving anything
    try:
        _, d = game_dir()
        turns = [int(t) for t in re.findall(r"\bT(\d+)", open(os.path.join(d, "ambitions.md")).read())]
        now = int(re.search(r"Turn (\d+),", status).group(1))
    except (OSError, AttributeError, ValueError):
        return []
    if turns and now - max(turns) > AMBITIONS_STALE:
        return ["", "**Your ambitions were last revised at T%d, %d turns ago. Are they still what you want, "
                "and are you winning? Revise ambitions.md on this wake-up.**" % (max(turns), now - max(turns))]
    return []


def my_land_map():
    # places, the 8 tiles around every hot spot, battle cards, and pictures saved for the Read tool
    # (a picture inside the prompt would stop the prompt cache; see mapview.py)
    sys.path.insert(0, HERE)
    import mapview
    _, d = game_dir()
    try:
        return mapview.brief(mapview.live_state())   # no pictures: none were opened in 241 wake-ups
    except Exception as e:
        return "(map unavailable: %s)" % e


def recent_wakes(n):
    # short-term memory: the final words of the last few wake-ups of this timeline
    _, d = game_dir()
    names = sorted(os.listdir(os.path.join(d, "wakes")), key=lambda x: os.path.getmtime(os.path.join(d, "wakes", x)))
    # a wake-up written before a reload, about a turn at or after the reloaded one, belongs to the abandoned timeline
    cuts = [(time.mktime(time.strptime(w, "%Y-%m-%d %H:%M:%S")), t) for w, t in timeline.rewinds(EVENTS)]
    def abandoned(x):
        m = re.match(r"T(\d+)-", x)
        mt = os.path.getmtime(os.path.join(d, "wakes", x))
        return bool(m) and any(mt < w and int(m.group(1)) >= t for w, t in cuts)
    names = [x for x in names if not abandoned(x)]
    out = []
    for name in names[-n:]:
        text = open(os.path.join(d, "wakes", name)).read()
        head = text.splitlines()[0].lstrip("# ")
        why = next((l for l in text.splitlines() if l.startswith("**Why:**")), "")
        words = text.split("**Final words:**", 1)[-1].split("\n_")[0].strip()
        out.append("- %s. %s %s" % (head, why.replace("**Why:**", "Why:").strip(), " ".join(words.split())[:600]))
    return out


def prompt_for(d, events, chat, reasons):
    playbook = open(os.path.join(HERE, "PLAYBOOK.md")).read()
    memory = []
    for name in MEMORY:
        p = os.path.join(d, name)
        if os.path.exists(p):
            memory.append("### %s\n\n%s" % (name, open(p).read().strip()))
    dossiers = os.path.join(d, "dossiers")
    for name in sorted(os.listdir(dossiers)) if os.path.isdir(dossiers) else []:
        memory.append("### dossiers/%s\n\n%s" % (name, open(os.path.join(dossiers, name)).read().strip()))
    notes = os.path.join(d, "director_notes.md")
    if os.path.exists(notes) and open(notes).read().strip():
        memory.append("### director_notes.md (from the CIVAI director: about tools and process only, never game info)\n\n"
                      + open(notes).read().strip())
    size = sum(len(m) for m in memory) // 4
    warn = ""
    if size > MEMORY_TOKENS_WARN:
        warn = ("\n\n**Your memory files are ~%d tokens (over %d). Trim them on this wake-up: rewrite plan.md to "
                "about a page, compress old chronicle eras, keep dossiers as summaries.**" % (size, MEMORY_TOKENS_WARN))
    # the unchanging part goes into the system prompt (cached between wake-ups); the user message has
    # the memory files (they change on most wake-ups) and the brief
    system = "\n\n".join([
        "You are the leader in persona.md, playing the current CIVAI game to win. Each message is ONE wake-up: act on it and finish. "
        "You remember nothing between wake-ups except the files in the game folder, so before you finish, "
        "write down in them whatever your future self must know. The playbook below is your full instruction set; "
        "skip its 'Start of a session' and 'Turn loop' listening steps: the loop wakes you.",
        "# PLAYBOOK\n\n" + playbook,
    ])
    with open(SYSTEM_FILE, "w") as f:
        f.write(system)
    return "\n\n".join([
        "# YOUR MEMORY FILES (game folder: %s)\n\n" % d + "\n\n".join(memory),
        "# BRIEF\n\n" + brief(events, chat, reasons) + warn,
    ])


# ---------------------------------------------------------------- v2 prompt: what a ruler needs, in that order
def playbook_for_loop():
    # the playbook without the sections for a person starting a session by hand
    text, out, skip = open(os.path.join(HERE, "PLAYBOOK.md")).read(), [], False
    for line in text.splitlines():
        if line.startswith("## "):
            skip = line.startswith(LOOP_SKIP)
        if not skip:
            out.append(line)
    return "\n".join(out)


def wake_files(d):
    # this timeline's wake-up logs, oldest first (a wake-up written before a reload, about a turn at or
    # after the reloaded one, belongs to the abandoned timeline)
    w = os.path.join(d, "wakes")
    if not os.path.isdir(w):
        return []
    names = sorted(os.listdir(w), key=lambda x: os.path.getmtime(os.path.join(w, x)))
    cuts = [(time.mktime(time.strptime(t, "%Y-%m-%d %H:%M:%S")), n) for t, n in timeline.rewinds(EVENTS)]
    def abandoned(x):
        m = re.match(r"T(\d+)-", x)
        return bool(m) and any(os.path.getmtime(os.path.join(w, x)) < t and int(m.group(1)) >= n for t, n in cuts)
    return [os.path.join(w, x) for x in names if not abandoned(x)]


def summarize_commands(cmds):
    # what a wake-up did, from the commands it really ran (never from its own retelling)
    said, moves, dos, other, looks = [], {}, {}, [], 0
    for c in cmds:
        words = c.split()
        if not words:
            continue
        if words[0] == "say":
            said.append('"%s"' % " ".join(words[1:])[:200])
        elif words[0] == "move" and len(words) >= 4:
            moves.setdefault("%s,%s" % (words[2], words[3]), []).append("#" + words[1])
        elif words[0] == "do" and len(words) >= 3:
            dos.setdefault(" ".join(words[2:]), []).append("#" + words[1])
        elif words[0] in LOOKUPS or (words[0] in ("research", "budget", "religion", "civics", "gate") and len(words) == 1):
            looks += 1
        elif words[0] != "think":
            other.append("civ " + c[:120])
    parts = ["said " + " / ".join(said) if said else "said nothing"]
    parts += ["moved %s to %s" % (" ".join(ids), xy) for xy, ids in moves.items()]
    parts += ["%s: %s" % (a, " ".join(ids)) for a, ids in dos.items()]
    parts += other
    return "; ".join(parts)


def record_of_wakes(d, n=3):
    out = []
    for path in wake_files(d)[-n:]:
        text = open(path).read()
        head = text.splitlines()[0].lstrip("# ")
        why = next((l.replace("**Why:**", "").strip() for l in text.splitlines() if l.startswith("**Why:**")), "")
        cmds = re.findall(r"^- `civ (.*)`$", text.split("**Commands:**", 1)[-1].split("**Final words:**")[0], re.M)
        out.append("- %s (%s): %s" % (head, why[:160], summarize_commands(cmds)))
    return out


def chat_lines(new_chat):
    # the chat of the last few turns: at least BRIEF_CHAT_LINES lines, at most twice that
    rows = timeline.read(CHAT, timeline.chat_rewind)
    now = game_turn()
    recent = sum(1 for c in rows if isinstance(c.get("turn"), int) and c["turn"] > now - BRIEF_CHAT_TURNS)
    rows = rows[-min(max(recent, BRIEF_CHAT_LINES), 2 * BRIEF_CHAT_LINES):]
    new_ids = set(json.dumps(c, sort_keys=True) for c in new_chat)
    return ["%sT%s %s: %s" % ("NEW " if json.dumps(c, sort_keys=True) in new_ids and c.get("from") != "claude" else "",
            c.get("turn"), speaker(c), c.get("text")) for c in rows]


def speaker(c):
    # who wrote a chat line, as this seat sees it; private lines say so
    who = "you" if c.get("from") == "claude" else human_name() if c.get("from") == "player" else c.get("from")
    to = c.get("to")
    if to == "you":
        return who + " (privately to you)"
    if to and to != "all":
        return who + " (privately to %s)" % to
    return who + (" (to all)" if to == "all" else "")


def raw(cmd):
    try:
        return json.loads(civ("raw", cmd))
    except ValueError:
        return {}


def waiting_lines():
    # what waits for an answer: proposals and our own open offers, one line each
    out = [l for l in raw("proposals").get("open", []) if l != "none"]
    o = raw("offers")
    out += ["our offer waiting: %s" % l for l in o.get("open", []) if l != "none"]
    out += ["deal waiting for your seal: %s" % l for l in o.get("waiting_for_your_seal", []) if l != "none"]
    return out


def state_section():
    r, b = raw("research"), raw("budget")
    lines = [civ("status", "--brief"), ""]
    if r:
        lines.append("Research: %s, %s turns (%s beakers/turn; queue: %s). Can research: %s." % (
            r.get("researching"), r.get("turns"), r.get("beakers_per_turn"), ", ".join(r.get("queue") or []) or "-",
            ", ".join(r.get("can_research") or [])))
    if b:
        lines.append("Budget: %s (%s); per turn %s." % (b.get("split"), b.get("chosen_by"), b.get("per_turn")))
    deals = raw("deals").get("deals") or []
    lines.append("Ongoing deals:" + ("" if deals else " none"))
    lines += ["  " + l for l in deals]
    return "\n".join(lines)


GOLD = re.compile(r"^(\d+) gold$")


def ledger_lines():
    """What went each way between us and every other leader, from the game's own records (deals, gifts,
    cities, wars) - never from anyone's notes. Facts only; what they mean is the leader's to judge."""
    me = re.search(r"I am (.+?) of (.+?) \(player", civ("status", "--brief"))
    me = me and "%s (%s)" % (me.group(1), me.group(2))
    book = {}
    side = lambda who: book.setdefault(who, {"gave": [], "got": [], "gave_gold": 0, "got_gold": 0, "cities": [], "wars": []})
    def add(who, key, items, turn):
        b = side(who)
        for it in items or []:
            m = GOLD.match(it)
            if m:
                b[key + "_gold"] += int(m.group(1))
            else:
                b[key].append("%s (T%s)" % (it, turn))
    for e in timeline.read(EVENTS, timeline.event_rewind):
        k, t = e.get("kind"), e.get("turn")
        if k == "deal_done" and e.get("with"):
            add(e["with"], "gave", e.get("gave"), t)
            add(e["with"], "got", e.get("got"), t)
        elif k == "gift_received" and e.get("from"):
            add(e["from"], "got", e.get("got"), t)
        elif k == "city_changed_hands" and me and me in (e.get("from"), e.get("to")):
            other = e["to"] if e.get("from") == me else e.get("from")
            side(other)["cities"].append("%s %s (T%s)" % ("you took" if e.get("to") == me else "they took", e.get("name"), t))
        elif k in ("war_declared", "peace_made") and me and e.get("team") and e.get("against"):
            mine = me.split(" (")[0]
            if mine in (e["team"], e["against"]):
                other = e["against"] if e["team"] == mine else e["team"]
                who = next((w for w in book if w.startswith(other)), other)
                what = "war" if k == "war_declared" else "peace"
                side(who)["wars"].append("%s %s (T%s)" % ("you declared" if e["team"] == mine else "they declared", what, t))
    out = []
    for who, b in sorted(book.items()):
        if who == me:
            continue
        line = ["- **%s**" % who,
                "you gave: %s%s" % (", ".join(b["gave"]) or "-", "; %d gold" % b["gave_gold"] if b["gave_gold"] else ""),
                "you got: %s%s" % (", ".join(b["got"]) or "-", "; %d gold" % b["got_gold"] if b["got_gold"] else "")]
        if b["cities"]:
            line.append("cities: " + ", ".join(b["cities"]))
        if b["wars"]:
            line.append("war: " + ", ".join(sorted(set(b["wars"]))))
        out.append(" | ".join(line))
    return out


def inbox(d):
    p = os.path.join(d, "director_inbox.md")
    return open(p).read().strip() if os.path.exists(p) else ""


def prompt_v2(d, events, chat, reasons, rec_dir=None):
    """The wake-up message: why you are woken first, then who you are and what you planned, what you
    really did lately (from the logs), the others, the state, the chat, the map; the reason again last."""
    rec_dir = rec_dir or d
    read = lambda name: open(os.path.join(d, name)).read().strip() if os.path.exists(os.path.join(d, name)) else ""
    turn = game_turn()
    turn_wake = any(r.startswith(("turn ", "player_waiting")) for r in reasons)
    status = civ("status", "--brief").splitlines()
    W = ["# TURN %s. %s" % (turn, " ".join(status[1:3]) if len(status) > 2 else ""), "",
         "Woken by: " + "; ".join(reasons), ""]
    shown = [fmt_event(e) for e in events if e.get("kind") not in NOISE]
    W += ["## Since your last wake-up", ""] + (shown[-BRIEF_EVENTS:] or ["(no game events)"])
    if len(shown) > BRIEF_EVENTS:
        W.append("(%d earlier events: `civ events %d`)" % (len(shown) - BRIEF_EVENTS, len(shown)))
    wait = waiting_lines()
    if wait:
        W += ["", "## Waiting for your answer", ""] + ["- " + l for l in wait]
    notes = inbox(d)
    if notes:
        W += ["", "## From the director (about tools and process, never game advice; shown once)", "", notes]
    memory = [read(m) for m in MEMORY] + [open(os.path.join(d, "dossiers", n)).read() for n in
              (sorted(os.listdir(os.path.join(d, "dossiers"))) if os.path.isdir(os.path.join(d, "dossiers")) else [])]
    size = sum(len(m) for m in memory) // 4
    nudges = ambitions_note(civ("ping"))
    if size > MEMORY_TOKENS_WARN:
        nudges.append("**Your memory files are ~%d tokens (over %d). Trim them on this wake-up.**" % (size, MEMORY_TOKENS_WARN))
    W += [n for n in nudges if n]
    parts = ["\n".join(W)]
    parts.append("# WHO YOU ARE, YOUR AIMS AND PLAN (game folder: %s)\n\n### persona.md\n\n%s\n\n### ambitions.md\n\n%s\n\n### plan.md\n\n%s"
                 % (d, read("persona.md"), read("ambitions.md"), read("plan.md")))
    parts.append("### secrets.md\n\n" + (read("secrets.md") or "(empty)"))
    parts.append("# WHAT YOU REALLY DID ON YOUR LAST WAKE-UPS (from the game's log)\n\n" +
                 ("\n".join(record_of_wakes(rec_dir)) or "(none yet)"))
    dd = os.path.join(d, "dossiers")
    dossiers = ["### dossiers/%s\n\n%s" % (n, open(os.path.join(dd, n)).read().strip())
                for n in (sorted(os.listdir(dd)) if os.path.isdir(dd) else [])]
    parts.append("# YOUR LEDGER WITH THE OTHER LEADERS (the game's records: deals, gifts, cities, wars; your notes "
                 "can't change it)\n\n" + ("\n".join(ledger_lines()) or "(nothing has passed between you and anyone yet)"))
    parts.append("# THE OTHER LEADERS (your dossiers)\n\n" + ("\n\n".join(dossiers) or "(none yet)"))
    parts.append("### chronicle.md\n\n" + (read("chronicle.md") or "(empty)"))
    parts.append("# STATE NOW\n\n" + state_section())
    parts.append("# HEARD AT COURT (the chat: lines to everyone and private ones to you; NEW = since your last "
                 "wake-up)\n\n" + ("\n".join(chat_lines(chat)) or "(nothing yet)"))
    parts.append("# MAP\n\n" + my_land_map())
    parts.append("# YOUR MOVE\n\nWhat do you want to have happened by your next review? Decide, act with `civ` commands, "
                 "and update your files.%s End with a short private journal entry: what you wanted, what you got, "
                 "what you are holding back." % (" Finish the turn with `civ ready`." if turn_wake else ""))
    system = "\n\n".join([
        "You are the leader in persona.md, playing the current CIVAI game to win. Each message is ONE wake-up: act on it and "
        "finish. You remember nothing between wake-ups except the files in the game folder, so before you finish, write "
        "down in them whatever your future self must know. The playbook below is your full instruction set.",
        "How you act: the Bash tool runs your `civ` commands (`~/civai/civ ...`; run independent lookups in parallel); "
        "Read, Write and Edit work on your files in the game folder (read a file before you change it). "
        "Keep tool output small: ask for what you need, not everything.",
        "# PLAYBOOK\n\n" + playbook_for_loop()])
    return system, "\n\n".join(parts)


CODEX_HOME = os.path.join(HERE, "out", "codex-home")   # a clean Codex config: the login only, no skills, MCP or memory


def codex_home():
    # the user's ChatGPT login is linked, never copied; everything else is empty so every seat starts equal.
    # A seat keeps its own Codex home (its sessions are its private thoughts) inside its folder.
    home = os.path.join(seat_dir(), ".codex-home") if SEAT else CODEX_HOME
    os.makedirs(home, exist_ok=True)
    link = os.path.join(home, "auth.json")
    if not os.path.lexists(link):
        os.symlink(os.path.expanduser("~/.codex/auth.json"), link)
    conf = os.path.join(home, "config.toml")
    if not os.path.exists(conf):
        open(conf, "w").write("# CIVAI seat: no MCP servers, no project docs\nproject_doc_max_bytes = 0\n")
    return home


def harness_of(cfg):
    return cfg.get("harness") or ("claude" if os.path.basename(cfg["agent"][0]) == "claude" else "other")


def agent_command(cfg, system_file, resume):
    """The command line for one call. Every harness gets our text as its whole system prompt, the same
    four tools (shell, read, write, edit) and the prompt on stdin."""
    h = harness_of(cfg)
    if h == "codex":
        cmd = ["codex", "exec"] + (["resume", resume] if resume else []) + [
            "--skip-git-repo-check", "--json", "--dangerously-bypass-approvals-and-sandbox",
            "-c", "model_instructions_file=" + system_file]
        if cfg.get("model"):
            cmd += ["-m", cfg["model"]]
        if cfg.get("effort"):
            cmd += ["-c", "model_reasoning_effort=" + cfg["effort"]]
        return cmd + ["-"], {"CODEX_HOME": codex_home()}
    if h == "pi":
        cmd = ["pi", "-p", "--mode", "json", "--provider", cfg.get("provider", "openrouter"), "--model",
               cfg["model"] + (":" + cfg["effort"] if cfg.get("effort") else ""),
               "--system-prompt", open(system_file).read(), "--tools", "read,bash,edit,write",
               "--session-dir", os.path.join(seat_dir(), ".pi-sessions") if SEAT else os.path.join(HERE, "out", "pi-sessions")]
        return cmd + (["--session", resume] if resume else []), {}
    cmd = [a.replace("{prompt}", "") for a in cfg["agent"]]
    if resume:
        cmd += ["--resume", resume]
    if h == "claude":
        if cfg.get("system") == "replace":
            # our text is the whole system prompt: the leader first, no coding-assistant identity
            cmd += ["--system-prompt-file", system_file, "--output-format", "json"]
        else:
            cmd += ["--append-system-prompt-file", system_file, "--output-format", "json",
                    "--exclude-dynamic-system-prompt-sections"]
        if cfg.get("model"):
            cmd += ["--model", cfg["model"]]
        if cfg.get("effort"):
            cmd += ["--effort", cfg["effort"]]
    return cmd, {}


def parse_output(h, stdout):
    """(final words, meta, error) from a harness's output. meta: session_id, model, cost, tokens."""
    out = stdout.strip()
    if h == "claude" and out.startswith("{"):
        data = json.loads(out)
        meta = {k: data.get(k) for k in ("session_id", "total_cost_usd", "num_turns", "duration_ms", "usage", "modelUsage")}
        text = data.get("result") or ""
        return text, meta, (text or data.get("subtype") or "error") if data.get("is_error") else None
    rows = []
    for line in out.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    if h == "codex":
        texts = [r["item"].get("text", "") for r in rows if r.get("type") == "item.completed"
                 and r.get("item", {}).get("type") == "agent_message"]
        usage = [r.get("usage") for r in rows if r.get("type") == "turn.completed"]
        sid = next((r.get("thread_id") for r in rows if r.get("type") == "thread.started"), None)
        errs = [r.get("message") or r.get("error") for r in rows if r.get("type") in ("error", "turn.failed")]
        meta = {"session_id": sid, "usage": usage[-1] if usage else None,
                "num_turns": sum(1 for r in rows if r.get("type") == "item.completed")}
        return (texts[-1] if texts else ""), meta, (str(errs[-1])[:300] if errs and not texts else None)
    if h == "pi":
        sid = next((r.get("id") for r in rows if r.get("type") == "session"), None)
        end = next((r for r in reversed(rows) if r.get("type") == "agent_end"), None)
        msgs = [m for m in (end or {}).get("messages", []) if m.get("role") == "assistant"]
        text = "".join(c.get("text", "") for c in (msgs[-1]["content"] if msgs else []) if c.get("type") == "text")
        cost = sum(((m.get("usage") or {}).get("cost") or {}).get("total", 0) for m in msgs)
        usage = {k: sum((m.get("usage") or {}).get(k, 0) for m in msgs) for k in ("input", "output", "cacheRead", "reasoning")}
        meta = {"session_id": sid, "total_cost_usd": round(cost, 5), "usage": usage, "num_turns": len(msgs),
                "model": msgs[-1].get("model") if msgs else None}
        stop = msgs[-1].get("stopReason") if msgs else None
        return text, meta, ("no answer" if end is None else ("stopped: %s" % stop if stop == "error" else None))
    return out, {}, None


def run_agent(cfg, prompt, resume=None, system_file=SYSTEM_FILE, extra_env=None):
    h = harness_of(cfg)
    cwd = HERE
    if SEAT:
        # the seat's own copy of the system prompt: the sandbox lets the harness read only the seat's folder
        own = os.path.join(seat_dir(), ".system_prompt.md")
        open(own, "w").write(open(system_file).read())
        system_file = own
    cmd, henv = agent_command(cfg, system_file, resume)
    stdin = None if any("{prompt}" in a for a in cfg["agent"]) and h not in ("codex", "pi") else prompt
    if stdin is None:
        cmd = [a.replace("{prompt}", prompt) for a in cfg["agent"]]
    if SEAT:
        cmd = ["sandbox-exec", "-f", sandbox_profile()] + cmd
        cwd = seat_dir()
        henv = dict(henv, CIV_BROKER=os.path.join(HERE, "run", "broker.sock"),
                    CIV_TOKEN_FILE=os.path.join(seat_dir(), ".seat_token"))
    t0 = time.time()
    error, meta = None, {}
    try:
        env = {k: v for k, v in os.environ.items() if not k.startswith("CIV_") or k in ("CIV_BOTTLE", "CIV_GAME")}
        env["CIV_ACTOR"] = "agent"   # marks the player's own commands in the logs
        env.update(henv)
        env.update(extra_env or {})
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, cwd=cwd, env=env,
                           timeout=cfg.get("timeout_minutes", 15) * 60)
        try:
            out, meta, error = parse_output(h, r.stdout)
        except (ValueError, KeyError, TypeError) as e:
            out, error = r.stdout.strip(), "unreadable output: %s" % e
        if not out and r.stderr.strip() and r.returncode != 0:
            out = r.stderr.strip()
        if r.returncode != 0 and not error:
            error = (out or "exit code %d" % r.returncode)[-300:]
    except subprocess.TimeoutExpired:
        out = "(timed out)"
    except OSError as e:
        out = error = "could not start the agent: %s" % e
    meta["harness"] = h
    return out, time.time() - t0, meta, error


LOOKUPS = {"ping", "status", "map", "tile", "odds", "city", "unit", "player", "actions", "offers", "proposals",
           "tradeable", "relations", "victory", "rules", "area", "around", "where", "card", "chat", "events", "gate",
           "think", "director", "deals"}


def memory_added(d, base="HEAD", head=None):
    # the lines the agent added to its memory files on this wake-up (before the snapshot commits them)
    files = [m for m in MEMORY if m != "persona.md"] + ["dossiers"]
    try:
        diff = subprocess.run(["git", "diff", "--no-color", "-U0", base] + ([head] if head else []) + ["--"] + files,
                              cwd=d, capture_output=True, text=True).stdout
        new = [] if head else [f for f in subprocess.run(["git", "ls-files", "-z", "--others", "--exclude-standard", "--",
                                                          "dossiers"], cwd=d, capture_output=True, text=True).stdout.split("\0") if f]
    except OSError:
        return []
    out, name = [], ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[6:]
        elif line.startswith("+") and line[1:].strip():
            out.append("%s: %s" % (name, line[1:].strip()))
    for f in new:
        out += ["%s: %s" % (f, l.strip()) for l in open(os.path.join(d, f)) if l.strip()]
    return out


CHECK_TURNS = 5             # the self-check compares notes with the chat of this many recent turns


def check_prompt(cmds, added, final_words, now=None):
    # the game's own record (this wake-up's actions, the recent chat) next to what the agent believes it did
    acts = ["civ " + c["cmd"] for c in cmds if c.get("cmd", "").split(" ")[0] not in LOOKUPS and c["cmd"].split(" ")[0] != "say"]
    now = game_turn() if now is None else now
    chat = [c for c in timeline.read(CHAT, timeline.chat_rewind)
            if isinstance(c.get("turn"), int) and c["turn"] >= now - CHECK_TURNS]
    return "\n".join([
        "CHECK before this wake-up ends. Your notes are your only memory, so they must match what really happened.",
        "",
        "## The chat of the last %d turns (the game's record: you said only what is here; where anything you saw "
        "earlier disagrees, this record is right)" % CHECK_TURNS,
        "",
        "\n".join("- T%s %s: %s" % (c["turn"], speaker(c), c.get("text")) for c in chat) or "- (no messages)",
        "",
        "## Everything else you did this wake-up (the game's log)",
        "",
        "\n".join("- " + a for a in acts) or "- (no deals, answers or orders)",
        "",
        "## What you added to your memory files",
        "",
        "\n".join("- " + a for a in added) or "- (nothing)",
        "",
        "## Your final words",
        "",
        final_words.strip() or "(none)",
        "",
        "Compare with this record the lines you added, your final words, and every note in your memory files "
        "about the last %d turns. If one says you said, offered, gave, answered, ordered or did something "
        "that is not in this record, either do it now with the real command or correct the note. If you promised "
        "something in a message, it must be in plan.md with its turn. Then reply with one line: what you fixed, "
        "or 'checked'." % CHECK_TURNS,
    ])


def lines_since(path, pos):
    rows, _ = read_from(path, pos)
    return rows


def handle(cfg, d, st, events, chat, reasons):
    gid = os.path.basename(d)
    turn = next((e.get("turn") for e in reversed(events) if e.get("turn") is not None), "?")
    cmds_path, thoughts_path = os.path.join(d, "commands.jsonl"), os.path.join(d, "thoughts.jsonl")
    if cfg.get("shadow"):
        shadow_run(cfg, d, events, chat, reasons)
    v2 = cfg.get("prompt") == "v2"
    if v2:
        system, prompt = prompt_v2(d, events, chat, reasons)   # the loop's own lookups happen here, before the marks
        with open(SYSTEM_FILE_V2, "w") as f:
            f.write(system)
    else:
        prompt = prompt_for(d, events, chat, reasons)
    sysf = SYSTEM_FILE_V2 if v2 else SYSTEM_FILE
    m = re.search(r"[Tt]urn (\d+)[,:]", prompt)
    if m:
        turn = m.group(1)
    cmds_pos = os.path.getsize(cmds_path) if os.path.exists(cmds_path) else 0
    th_pos = os.path.getsize(thoughts_path) if os.path.exists(thoughts_path) else 0
    deep = re.search(r"wrote|proposal|deal|review|war|city_changed|lost|enemy_near|first_contact", " ".join(reasons))
    wcfg = dict(cfg, effort=cfg.get("effort_deep", "high")) if deep and cfg.get("effort_deep", "high") else cfg
    out, secs, meta, error = run_agent(wcfg, prompt, system_file=sysf)
    meta["effort"] = wcfg.get("effort")
    if v2 and not error:
        archive_inbox(d)
    agent_cmds = [c for c in lines_since(cmds_path, cmds_pos) if c.get("by", "agent") == "agent"]   # not the director's
    check = None
    added = memory_added(d)
    if not error and meta.get("session_id") and (added or any(c.get("cmd", "").startswith("say") for c in agent_cmds)):
        # the same session checks its notes against the game's log and fixes what doesn't match
        pos = os.path.getsize(cmds_path) if os.path.exists(cmds_path) else 0
        check, csecs, cmeta, cerr = run_agent(cfg, check_prompt(agent_cmds, added, out), resume=meta["session_id"],
                                              system_file=sysf)
        fixed = [c for c in lines_since(cmds_path, pos) if c.get("by", "agent") == "agent"]
        agent_cmds += fixed
        secs += csecs
        meta["check"] = {"result": check[-500:], "commands": [c.get("cmd") for c in fixed], "error": cerr,
                         "total_cost_usd": cmeta.get("total_cost_usd"), "seconds": round(csecs, 1)}
    # the human must never be stuck: if the agent forgot `civ ready` on a turn wake-up, say it for it
    gate = civ("gate")
    forced = False
    if ("claude_wake" in " ".join(reasons) or "player_waiting" in " ".join(reasons)) and "ready:           no" in gate:
        civ("ready")
        forced = True
    st["wakes"] = st.get("wakes", 0) + 1
    log = ["# Wake-up %d, turn %s (%s)" % (st["wakes"], turn, time.strftime("%Y-%m-%d %H:%M:%S")), "",
           "**Why:** " + "; ".join(reasons), "",
           "**Thoughts:**", ""]
    log += ["- " + t.get("text", "") for t in lines_since(thoughts_path, th_pos)] or ["- (none)"]
    log += ["", "**Commands:**", ""]
    log += ["- `civ %s`" % c.get("cmd", "") for c in agent_cmds] or ["- (none)"]
    if error:
        log += ["", "**FAILED:** " + error]
    if check is not None:
        log += ["", "**Self-check:** " + " ".join(check.split())[:600]]
    log += ["", "**Final words:**", "", out[-3000:], "",
            "_%.0f s, prompt ~%d tokens%s_" % (secs, len(prompt) // 4, ", ready said by the loop" if forced else "")]
    name = "T%s-%s.md" % (str(turn).zfill(3), time.strftime("%H%M%S"))
    open(os.path.join(d, "wakes", name), "w").write("\n".join(log))
    with open(os.path.join(d, "wake_stats.jsonl"), "a") as f:
        f.write(json.dumps(dict(meta, wake=st["wakes"], turn=turn, file=name, seconds=round(secs, 1), reasons=reasons,
                                forced_ready=forced, error=error, wall=time.strftime("%Y-%m-%d %H:%M:%S")),
                           ensure_ascii=False) + "\n")
    snapshot_memory(d, "wake %d, turn %s" % (st["wakes"], turn))
    print(time.strftime("%H:%M:%S"), "wake-up FAILED: " + error if error else "wake-up done:", "; ".join(reasons),
          "(%.0f s)%s" % (secs, " +forced ready" if forced else ""), flush=True)
    return error


def notice(text):
    # a line on the human's screen from CIVAI itself (not from the leader), so a silent leader is explained
    civ("raw", "notice", json.dumps({"text": text}))


def archive_inbox(d):
    # director answers are shown once, then kept in the archive
    p = os.path.join(d, "director_inbox.md")
    if os.path.exists(p) and open(p).read().strip():
        with open(os.path.join(d, "director_notes_archive.md"), "a") as f:
            f.write("\n" + open(p).read().strip() + "\n")
        open(p, "w").close()


SHADOW_FILES = ("persona.md", "ambitions.md", "plan.md", "secrets.md", "chronicle.md", "director_inbox.md")


def shadow_run(cfg, d, events, chat, reasons):
    """The v2 prompt on the same wake-up, before the live one, in a copy of the memory, with `civ` read-only:
    what it would have done goes to games/_shadow (commands, final words, the prompt itself) for comparison."""
    sd = os.path.join(HERE, "games", SHADOW)
    import shutil
    if os.path.isdir(os.path.join(sd, "dossiers")):
        shutil.rmtree(os.path.join(sd, "dossiers"))
    for sub in ("wakes", "prompts"):
        os.makedirs(os.path.join(sd, sub), exist_ok=True)
    for name in SHADOW_FILES:
        if os.path.exists(os.path.join(d, name)):
            shutil.copy(os.path.join(d, name), os.path.join(sd, name))
    if os.path.isdir(os.path.join(d, "dossiers")):
        shutil.copytree(os.path.join(d, "dossiers"), os.path.join(sd, "dossiers"))
    system, prompt = prompt_v2(sd, events, chat, reasons, rec_dir=d)
    with open(SYSTEM_FILE_V2, "w") as f:
        f.write(system)
    stamp = time.strftime("%H%M%S")
    turn = game_turn()
    with open(os.path.join(sd, "prompts", "T%03d-%s-v2.md" % (turn, stamp)), "w") as f:
        f.write(prompt)
    with open(os.path.join(sd, "prompts", "T%03d-%s-v1.md" % (turn, stamp)), "w") as f:
        f.write(prompt_for(d, events, chat, reasons))   # the live prompt, for side-by-side reading
    cmds_path = os.path.join(sd, "commands.jsonl")
    pos = os.path.getsize(cmds_path) if os.path.exists(cmds_path) else 0
    out, secs, meta, error = run_agent(cfg, prompt, system_file=SYSTEM_FILE_V2,
                                       extra_env={"CIV_READONLY": "1", "CIV_GAME": SHADOW})
    cmds = [c.get("cmd", "") for c in lines_since(cmds_path, pos)]
    log = ["# Shadow wake-up, turn %s (%s)" % (turn, time.strftime("%Y-%m-%d %H:%M:%S")), "", "**Why:** " + "; ".join(reasons),
           "", "**Commands:**", ""] + ["- `civ %s`" % c for c in cmds] + ["", "**Final words:**", "", out[-3000:], "",
           "_%.0f s, prompt ~%d tokens, %s_" % (secs, len(prompt) // 4, error or "ok")]
    open(os.path.join(sd, "wakes", "T%03d-%s.md" % (turn, stamp)), "w").write("\n".join(log))
    with open(os.path.join(sd, "wake_stats.jsonl"), "a") as f:
        f.write(json.dumps(dict(meta, turn=turn, seconds=round(secs, 1), reasons=reasons, prompt_tokens=len(prompt) // 4,
                                error=error, wall=time.strftime("%Y-%m-%d %H:%M:%S")), ensure_ascii=False) + "\n")
    print(time.strftime("%H:%M:%S"), "shadow done (%.0f s, %d commands)" % (secs, len(cmds)), flush=True)


def snapshot_memory(d, message):
    # the game folder as a git history: every wake-up's memory files can be read back later
    try:
        if not os.path.isdir(os.path.join(d, ".git")):
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(["git", "add", "-A"], cwd=d, check=True)
        subprocess.run(["git", "-c", "user.name=civai-loop", "-c", "user.email=civai@localhost", "commit", "-q",
                        "--allow-empty", "-m", message], cwd=d, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        print("memory snapshot failed:", e, flush=True)


def reasons_of(events):
    out = []
    for e in events:
        k = e.get("kind")
        if k not in WAKE_KINDS:
            continue
        if k in ("deal_done", "deal_failed") and "id" not in e:
            continue   # an AI's answer or our own gift: we saw it when we made it; it waits for the next wake-up
        if k == "claude_wake":
            out.append("turn %s: %s" % (e.get("turn"), ", ".join(e.get("reasons", []))))
        elif k == "message_from_player":
            out.append('%s wrote: "%s"' % (human_name(), e.get("text")))
        else:
            out.append(k)
    return out


def main():
    cfg = json.load(open(os.path.join(HERE, "loop.json")))
    once, dry = "--once" in sys.argv, "--dry-run" in sys.argv
    if "--seat" in sys.argv:
        seat_setup(sys.argv[sys.argv.index("--game") + 1], sys.argv[sys.argv.index("--seat") + 1])
        cfg = dict(cfg, prompt="v2", shadow=False, **{k: v for k, v in SEAT.items() if k not in ("key", "player", "game")})
    gid, d = game_dir()
    st = load_state(d)
    print("CIVAI loop on game %s (agent: %s)" % (gid, cfg["agent"][0]), flush=True)
    failures = 0
    resume = bool(SEAT)
    while True:
        events, epos = read_from(EVENTS, st["events_pos"])
        reasons = reasons_of(events)
        if resume and not reasons:
            # a seat's loop (re)started while its civ waits on this turn: the game won't move until it plays
            resume = False
            if not raw("gate").get("ready", True):
                reasons = ["turn %d: turn (the loop restarted while the turn waits for you)" % game_turn()]
        if not reasons and not (once or dry):
            time.sleep(1)
            continue
        if reasons:
            time.sleep(GATHER_SECONDS)              # let the burst finish
            events, epos = read_from(EVENTS, st["events_pos"])
            reasons = reasons_of(events) or reasons
        chat, cpos = read_from(CHAT, st["chat_pos"])
        if dry:
            if "--v2" in sys.argv:
                system, prompt = prompt_v2(d, events, chat, reasons or ["(dry run)"])
                print(prompt if "--system" not in sys.argv else system)
            else:
                print(prompt_for(d, events, chat, reasons or ["(dry run)"]))
            return
        try:
            error = handle(cfg, d, st, events, chat, reasons or ["manual run"])
        except Exception:
            # a bug in the loop must not stop the game (it waits for this seat): log it and try again
            import traceback
            error = "loop error: " + traceback.format_exc().strip().splitlines()[-1]
            print(time.strftime("%H:%M:%S"), traceback.format_exc(), flush=True)
        if error and not once:
            # the agent never got to play (usage limit, network, crash): keep these events for the next try,
            # say so on screen once, and wait longer each time; the turn itself was already released
            failures += 1
            if failures == 1:
                notice("the AI leader could not play this wake-up (%s). The game goes on; the leader catches up "
                       "when the AI is reachable again." % error.splitlines()[0][:120])
            time.sleep(min(60 * 2 ** (failures - 1), 900))
            continue
        if failures:
            notice("the AI leader is playing again.")
            failures = 0
        st["events_pos"], st["chat_pos"] = epos, cpos
        save_state(d, st)
        if once:
            return


if __name__ == "__main__":
    main()
