#!/usr/bin/env python3
"""Replay one past turn of a game of several AI leaders, for the video: the same save, the same orders.

Civ IV is deterministic given a save and the same inputs. So: load the autosave made at the start of
turn T, send the orders the agents gave during turn T in their original order, and the turn plays again
the same way while the camera records it.

  replay.py <game> index                  every turn: its save, how many orders each seat gave, what stands
                                          in the way of an exact replay
  replay.py <game> plan T [--thoughts]    the replay script of turn T: the save, then every order in order
                                          (--thoughts: the agents' thoughts in between, not replayed)
  replay.py <game> run T [--dry-run] [--pace S] [--with-failed]
                                          load turn T's save and send its orders, then compare the game's
                                          record of turn T+1 with the original (--dry-run: print the steps)
Add --bridge DIR to read an archived bridge folder instead of the live one, --games DIR for another
games folder (the default is games/ next to this file).

Which turn a command belongs to comes from the game's clock, not from the wake-up file names (a wake-up
can start in one turn and end in the next). Every turn start (truth.jsonl, the turn wake-up events) and
every loaded save (bridge.log) opens a window of wall-clock time; a command belongs to the window it was
given in. A save loaded at turn R closes the windows of turn R and later that were opened before it:
what was done in them never happened in the game as it went on.
"""
import bisect
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GAMES = os.path.join(HERE, "games")
DRIVE_C = os.path.expanduser("~/Library/Application Support/CrossOver/Bottles/%s/drive_c"
                             % os.environ.get("CIV_BOTTLE", "civ4"))
BRIDGE = os.path.join(DRIVE_C, "claude_bridge")
QUICKSAVE = os.path.join(DRIVE_C, "users/crossover/Documents/My Games/Beyond the Sword/Saves/single/quick",
                         "QuickSave.CivBeyondSwordSave")
CIV_WINDOW = os.environ.get("CIV_WINDOW", "Civ4BeyondSword")   # part of the game's process name in System Events
# the bridge the game runs (installed in the game's mod folder), else the repo's copy
BRIDGE_SOURCES = (os.path.join(DRIVE_C, "GOG Games/Civilization IV Complete/Civ4/Beyond the Sword/Mods/CIVAI/Assets/Python",
                               "ClaudeBridge.py"), os.path.join(HERE, "mod/CIVAI/Assets/Python/ClaudeBridge.py"))

# the orders `civ` can send; whether one of them only looks is civ's own read_only() (see is_order)
ORDERS = {"move", "do", "offer", "give", "answer", "religion", "civics", "war", "ratify", "reject", "cancel",
          "budget", "raze", "research", "build", "hurry", "hold", "gate", "claim", "release", "ready", "say",
          "py", "raw"}
# the bridge's commands (COMMANDS in ClaudeBridge.py) that change the game, for `civ raw`
BRIDGE_ORDERS = (ORDERS - {"raw", "py", "give"}) | {"exec"}
# the bridge's own files that live outside the save (unit and city claims, open questions, the gate...)
SIDE_FILES = ("claims.json", "city_claims.json", "proposals.json", "gate.json", "choices.json", "offers.json",
              "seal.json", "timeline.json")
FIELDS = ("alive", "score", "cities", "pop", "units", "military", "gold", "techs", "era", "religion", "war", "met")


def load_civ():
    # the civ CLI as a module: its LOOKUPS and read_only() decide what is an order
    loader = importlib.machinery.SourceFileLoader("civcli", os.path.join(HERE, "civ"))
    spec = importlib.util.spec_from_loader("civcli", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


CIV = load_civ()


# ---------- reading the logs

def read_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass   # a line cut by a crash
    return rows


def epoch(stamp):
    return time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))


def clock(t):
    return time.strftime("%H:%M:%S", time.localtime(t))


def seats(gdir):
    return json.load(open(os.path.join(gdir, "seats.json")))["seats"]


def clock_offset(bridge):
    # the game (under Wine) writes its own clock, which can be hours off the Mac's: compare the last line
    # of bridge.log with the moment the file was last written, rounded to a quarter of an hour
    lines = log_lines(bridge)
    if not lines:
        return 0
    last = lines[-1][0]
    return round((last - os.path.getmtime(os.path.join(bridge, "bridge.log"))) / 900.0) * 900


def log_lines(bridge):
    # bridge.log as (time on the game's clock, text) for every line that starts with a time
    path = os.path.join(bridge, "bridge.log")
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, errors="replace"):
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)", line)
        if m:
            out.append((epoch(m.group(1)), m.group(2)))
    return out


# ---------- the turn clock

class Window(object):
    """A stretch of wall-clock time in which the game was at one turn."""

    def __init__(self, turn, start, how):
        self.turn, self.start, self.how = turn, start, how
        self.end = None          # the next window's start; None while the game is still in it
        self.current = True      # False: a later load threw this stretch away
        self.truth = None        # the game's record written as this turn began (truth.jsonl)
        self.next_truth = None   # the record written as it ended: what a replay of this turn must give again


def turn_marks(bridge, offset, span):
    """(time on the Mac clock, turn, how) for every turn start and every loaded save the bridge saw."""
    lo, hi = span
    marks = []
    for r in read_jsonl(os.path.join(bridge, "truth.jsonl")):
        t = epoch(r["time"]) - offset
        if lo <= t <= hi:
            marks.append((t, r["turn"], "start", r))
    for when, text in log_lines(bridge):
        m = re.match(r"dump ok: (load_game|game_start) turn=(\d+)", text)
        t = when - offset
        if m and lo <= t <= hi:
            how = "start"
            if m.group(1) == "load_game":
                how = "load"
            marks.append((t, int(m.group(2)), how, None))
    for t, turn in wake_marks(bridge, offset, lo):
        # the seats' turn wake-ups say when each turn began too (older bridges wrote no truth rows; the
        # director can write one late by hand): a turn's window opens at the first of its marks
        if lo <= t <= hi:
            marks.append((t, turn, "start", None))
    marks.sort(key=lambda m: (m[0], m[2] != "load"))
    return marks


def wake_marks(bridge, offset, first):
    # events only carry the time of day: the date is the game's first day, plus one each time the clock wraps
    out = []
    for name in sorted(os.listdir(bridge)) if os.path.isdir(bridge) else []:
        path = os.path.join(bridge, name, "events.jsonl")
        if not re.match(r"p\d+$", name) or not os.path.exists(path):
            continue
        day = time.strftime("%Y-%m-%d", time.localtime(first + offset))
        prev = None
        for e in read_jsonl(path):
            if not e.get("time"):
                continue
            t = epoch(day + " " + e["time"])
            if prev is not None and t < prev - 6 * 3600:
                t += 86400
                day = time.strftime("%Y-%m-%d", time.localtime(t))
            prev = t
            if e.get("kind") == "claude_wake" and "turn" in (e.get("reasons") or []):
                out.append((t - offset, e["turn"]))
    return out


def windows_from(marks):
    """The game's turns as windows of time, oldest first; a load closes what it throws away."""
    wins, open_by_turn = [], {}
    for t, turn, how, row in marks:
        last = wins[-1] if wins else None
        if last is not None and last.turn == turn and how != "load":
            if row is not None and last.truth is None and t - last.start <= 5:
                last.truth = row       # the same turn start seen twice (truth row and wake-up event); a row
                                       # written later in the turn (by hand) is no record of the turn change
            continue
        if how == "load":
            for k, w in open_by_turn.items():
                if k >= turn:
                    w.current = False   # turn R and later, as played before this load, never happened
            open_by_turn = dict((k, w) for k, w in open_by_turn.items() if k < turn)
        w = Window(turn, t, how)
        w.truth = row
        if turn in open_by_turn:
            open_by_turn[turn].current = False
        open_by_turn[turn] = w
        if last is not None:
            last.end = t
        wins.append(w)
    for a, b in zip(wins, wins[1:]):
        # truth.jsonl's row of turn T+1 is written as turn T ends, before the game plays the turn change
        if b.turn == a.turn + 1 and b.truth is not None:
            a.next_truth = b.truth
    return wins


def window_at(wins, starts, t):
    # the window a command given at t belongs to; one given in the very second a window opens belongs to
    # the one before (nobody reacts to a new turn within its first second: the loop gathers events first)
    i = bisect.bisect_left(starts, t) - 1
    return wins[i] if i >= 0 else None


# ---------- commands

def is_order(words):
    """Does this command change the game? Lookups, notes and help questions don't."""
    if not words or words[0] not in ORDERS:
        return False
    if "--help" in words[1:] or "-h" in words[1:]:
        return False
    if words[0] == "raw":
        return raw_is_order(words[1:])
    return not CIV.read_only(words)


def raw_is_order(rest):
    # only the bridge's own orders change the game (`raw units` is an unknown command, `raw notice` a line
    # on screen); `raw gate` looks, `raw gate '{"on": true}'` sets
    if not rest or rest[0] not in BRIDGE_ORDERS:
        return False
    args = " ".join(rest[1:]).strip()
    if rest[0] in CIV.SHOW_WITHOUT_ARGS:
        return args not in ("", "{}")
    return True


DEAL_WORDS = ("open_borders", "defensive_pact", "permanent_alliance", "peace", "map", "vassal")


def starts_item(word):
    first = word.split(",")[0].lower()
    return ":" in first or first in DEAL_WORDS


def split_argv(text):
    """The log keeps " ".join(argv): the words come back, the quoting doesn't. Put back together what
    civ reads as one argument: a player's name, a deal item with spaces ("tech:Code of Laws")."""
    words = []
    for x in text.split():
        if re.fullmatch(r"-?\d+,-?\d+", x):
            words += x.split(",")   # coordinates written "18,21" mean 18 21 (as civ reads them)
        else:
            words.append(x)
    if not words:
        return words
    cmd, rest = words[0], words[1:]
    if cmd in ("offer", "give"):
        # the player's name runs up to --give/--get (offer) or up to the first item (give)
        head = []
        while rest and rest[0] not in ("--give", "--get") and not (cmd == "give" and starts_item(rest[0])):
            head.append(rest.pop(0))
        return [cmd] + joined(head) + join_items(rest)
    if cmd == "war":
        flags = [w for w in rest if w.startswith("--")]
        return [cmd] + joined([w for w in rest if not w.startswith("--")]) + flags
    return words


def joined(words):
    if not words:
        return []
    return [" ".join(words)]


def join_items(words):
    out = []
    for w in words:
        if w in ("--give", "--get") or starts_item(w) or not out or out[-1] in ("--give", "--get"):
            out.append(w)
        else:
            out[-1] += " " + w
    return out


def say_argv(text, said):
    """`civ say`: the full text and the leader it went to come from said.jsonl (the command log cuts long
    lines and can't tell a two-word name from the message)."""
    if said is None:
        return text.split()
    msg = said["text"]
    argv = ["say"]
    if text.startswith("say --popup"):
        argv.append("--popup")
    elif text.startswith("say --to "):
        # the name as it was typed: what stands between --to and the message
        cut = text.find(" " + msg[:40], len("say --to "))
        if cut > 0:
            to = text[len("say --to "):cut]
        else:
            to = (said.get("to") or "").split(" (")[0]   # "Joao II (Portugal)" as the bridge wrote it
        to = re.split(r" --(?:aim|think) ", to)[0]   # the private note before the message isn't part of the name
        argv += ["--to", to.strip()]
    return argv + [msg]


class Order(object):
    def __init__(self, seat, player, wall, text, by):
        self.seat, self.player, self.wall, self.text, self.by = seat, player, wall, text, by
        self.argv = split_argv(text)
        self.code, self.error = None, None   # from the broker's calls.jsonl, when it has the row
        self.wake = None                     # the wake-up file it was given in
        self.truncated = len(text) >= 500    # civ logs at most 500 characters
        self.notes = []


def seat_orders(gdir, seat):
    """Every order one seat gave, in its own order, with its wall time."""
    key = seat["key"]
    d = os.path.join(gdir, key)
    said = read_jsonl(os.path.join(d, "said.jsonl"))
    out = []
    for r in read_jsonl(os.path.join(d, "commands.jsonl")):
        text = (r.get("cmd") or "").strip()
        if not is_order(text.split()):
            continue
        o = Order(key, seat["player"], epoch(r["wall"]), text, r.get("by", "agent"))
        if o.argv[0] == "say":
            s = match_said(said, o)
            o.argv = say_argv(text, s)
            if s is None:
                o.notes.append("message text not found in said.jsonl")
            else:
                o.truncated = False
        out.append(o)
    attach_wakes(d, out)
    return out


def match_said(said, o):
    # said.jsonl is written when the message is shown, a moment after the command started
    body = o.text[len("say"):].strip()
    for s in said:
        t = epoch(s["wall"])
        if o.wall <= t <= o.wall + 30 and s["text"][:30] in body:
            said.remove(s)
            return s
    return None


def attach_wakes(d, orders):
    spans = []
    for w in read_jsonl(os.path.join(d, "wake_stats.jsonl")):
        if w.get("wall") and w.get("file"):
            end = epoch(w["wall"])
            spans.append((end - float(w.get("seconds") or 0) - 5, end + 1, w["file"]))
    for o in orders:
        for a, b, name in spans:
            if a <= o.wall <= b:
                o.wake = name


def attach_calls(gdir, orders):
    # the broker's record says how each call ended (from the turn it was added); match by seat and text
    calls = {}
    for c in read_jsonl(os.path.join(gdir, "calls.jsonl")):
        calls.setdefault((c["seat"], c["argv"]), []).append(c)
    for o in orders:
        for c in calls.get((o.seat, o.text[:300]), []):
            t = epoch(c["wall"])
            if o.wall - 1 <= t <= o.wall + float(c.get("seconds") or 0) + 3:
                o.code, o.error = c["code"], c.get("error")
                calls[(o.seat, o.text[:300])].remove(c)
                break


def director_code(bridge, offset, span):
    """Python the director ran inside the game (exec.log): it changed the game outside any seat's orders."""
    path = os.path.join(bridge, "exec.log")
    out, cur = [], None
    if not os.path.exists(path):
        return out
    for line in open(path, errors="replace"):
        m = re.match(r"---- (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) turn (\d+)", line)
        if m:
            cur = {"wall": epoch(m.group(1)) - offset, "turn": int(m.group(2)), "code": []}
            if span[0] <= cur["wall"] <= span[1]:
                out.append(cur)
        elif cur is not None:
            cur["code"].append(line.rstrip("\n"))
    return [c for c in out if not looks_only(c["code"])]


def looks_only(lines):
    # a bare `result = ...` reads; anything else may change the game
    body = [l for l in lines if l.strip()]
    return all(l.startswith("result =") or re.match(r"g = CyGame\(\)(; m = CyMap\(\))?$", l) for l in body)


def bridge_reloads(bridge, offset):
    # new bridge code in the middle of the game: a replay runs today's bridge, not that one
    out = []
    for when, text in log_lines(bridge):
        m = re.match(r"hot-reloaded bridge v(\d+)", text)
        if m:
            out.append((when - offset, "v" + m.group(1)))
        elif text.startswith("bridge loaded from"):
            out.append((when - offset, "restart"))
    return out


def bridge_version_now():
    for path in BRIDGE_SOURCES:
        if os.path.exists(path):
            m = re.search(r"^BRIDGE_VERSION = (\d+)", open(path, errors="replace").read(), re.M)
            if m:
                return int(m.group(1))
    return None


# ---------- saves

def year_turns(bridge, wins):
    years = {}
    for name in os.listdir(bridge) if os.path.isdir(bridge) else []:
        for e in read_jsonl(os.path.join(bridge, name, "events.jsonl")) if re.match(r"p\d+$", name) else []:
            if isinstance(e.get("turn"), int) and "year" in e:
                years[e["year"]] = e["turn"]
    for w in wins:
        if w.truth and "year" in w.truth:
            years[w.truth["year"]] = w.turn
    return years


def save_turn(name, years):
    m = re.match(r"T(\d+)_", name)
    if m:
        return int(m.group(1))
    m = re.match(r"AutoSave_(?:Initial_)?(BC|AD)-(\d+)", name)
    if not m:
        return None
    year = int(m.group(2)) * (-1 if m.group(1) == "BC" else 1)
    return years.get(year)


def saves_by_turn(gdir, years, loads):
    """turn -> the autosave made as it began. A save older than a load of an earlier turn belongs to a
    timeline that was thrown away."""
    d = os.path.join(gdir, "saves")
    out = {}
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not name.endswith(".CivBeyondSwordSave"):
            continue
        turn = save_turn(name, years)
        if turn is None:
            continue
        path = os.path.join(d, name)
        stale = any(lt < turn and t > os.path.getmtime(path) for t, lt in loads)
        if turn not in out or name.startswith("T"):
            out[turn] = {"path": path, "stale": stale, "written": os.path.getmtime(path)}
    return out


# ---------- the whole game

class Game(object):
    def __init__(self, game, bridge=BRIDGE, games=GAMES):
        self.id = game
        self.dir = os.path.join(games, game)
        self.bridge = bridge
        self.seats = seats(self.dir)
        self.offset = clock_offset(bridge)
        orders = []
        for s in self.seats:
            orders += seat_orders(self.dir, s)
        attach_calls(self.dir, orders)
        walls = [o.wall for o in orders] or [time.time()]
        self.span = (min(walls) - 3600, max(walls) + 3600)
        self.wins = windows_from(turn_marks(bridge, self.offset, self.span))
        self.starts = [w.start for w in self.wins]
        self.loads = [(w.start, w.turn) for w in self.wins if w.how == "load"]
        self.years = year_turns(bridge, self.wins)
        self.saves = saves_by_turn(self.dir, self.years, self.loads)
        self.director = director_code(bridge, self.offset, self.span)
        self.reloads = bridge_reloads(bridge, self.offset)
        self.by_turn, self.abandoned, self.unplaced = {}, {}, []
        for o in sorted(orders, key=lambda o: o.wall):   # stable: a seat's own order is kept within a second
            w = window_at(self.wins, self.starts, o.wall)
            if w is None:
                self.unplaced.append(o)
            elif w.current:
                self.by_turn.setdefault(w.turn, []).append(o)
            else:
                self.abandoned.setdefault(w.turn, []).append(o)
        self.proposals = proposal_turns(bridge, self.seats)

    def window(self, turn):
        found = [w for w in self.wins if w.turn == turn and w.current]
        return found[-1] if found else None

    def turns(self):
        return sorted(set(w.turn for w in self.wins if w.current))

    def year(self, turn):
        for y, t in self.years.items():
            if t == turn:
                return y
        return None


def proposal_turns(bridge, seat_list):
    # seat key -> proposal number -> (turn it was made, its text), for `civ answer N`
    out = {}
    for s in seat_list:
        rows = read_jsonl(os.path.join(bridge, "p%d" % s["player"], "events.jsonl"))
        for e in rows:
            if e.get("kind") == "proposal" and e.get("id") is not None:
                out.setdefault(s["key"], {})[int(e["id"])] = (e.get("turn"), e.get("text"))
    return out


def turn_notes(g, turn):
    """What stands in the way of replaying this turn exactly."""
    w = g.window(turn)
    notes = []
    orders = g.by_turn.get(turn, [])
    save = g.saves.get(turn)
    if save is None:
        notes.append("no save")
    elif save.get("stale"):
        notes.append("save from an abandoned timeline")
    if w is None:
        return notes + ["no turn window"]
    if w.end is None:
        notes.append("turn not over")
    elif w.next_truth is None:
        notes.append("no record of turn %d to compare" % (turn + 1))
    if w.how == "load":
        notes.append("save reloaded mid-turn")
    readied = set(o.seat for o in orders if o.argv[0] == "ready")
    missing = [s["key"] for s in g.seats if s["key"] not in readied]
    if missing and w.end is not None:
        # something else ended it (a reload before the seats were held, the director): no replay can say ready
        # at the same moment
        notes.append("ended without ready from " + ", ".join(missing))
    if g.abandoned.get(turn):
        notes.append("%d orders thrown away by a reload" % len(g.abandoned[turn]))
    end = w.end or float("inf")
    if any(w.start <= c["wall"] < end for c in g.director):
        notes.append("director ran Python")
    for t, what in g.reloads:
        if w.start <= t < end:
            notes.append("bridge %s mid-turn" % what)
    late = [o for o in orders if o.argv[0] == "answer" and earlier_proposal(g, o, turn)]
    if late:
        notes.append("%d answers to proposals made before the save" % len(late))
    same = same_second(orders)
    if same:
        notes.append("%d same-second orders of different seats" % same)
    return notes


def earlier_proposal(g, o, turn):
    # a proposal made before the save was written is not in the save: the bridge keeps it outside, and a
    # load clears it, so `civ answer N` finds nothing in the replay
    if len(o.argv) < 2 or not o.argv[1].isdigit():
        return False
    made = g.proposals.get(o.seat, {}).get(int(o.argv[1]))
    return made is not None and made[0] is not None and made[0] < turn


def same_second(orders):
    # orders of two seats in the same second: their order in the game can't be told from the logs
    n = 0
    for a, b in zip(orders, orders[1:]):
        if int(a.wall) == int(b.wall) and a.seat != b.seat:
            n += 1
    return n


# ---------- index / plan

def cmd_index(g):
    keys = [s["key"] for s in g.seats]
    print("Game %s: %d seats (%s); game clock %+d min from the Mac's" % (
        g.id, len(keys), ", ".join("%s=p%d" % (s["key"], s["player"]) for s in g.seats), g.offset // 60))
    print("%-5s %-8s %-36s %s  %s" % ("turn", "year", "save", " ".join("%8s" % k[:8] for k in keys), "notes"))
    ok = []
    for turn in g.turns():
        orders = g.by_turn.get(turn, [])
        counts = " ".join("%8d" % len([o for o in orders if o.seat == k]) for k in keys)
        save = "-"
        if turn in g.saves:
            save = os.path.basename(g.saves[turn]["path"])[:36]
        notes = turn_notes(g, turn)
        print("%-5d %-8s %-36s %s  %s" % (turn, year_text(g, turn), save, counts, "; ".join(notes)))
        if replayable(notes):
            ok.append(turn)
    print()
    print("replayable (a save, the turn over, a record of the next turn to compare): %s" % (
        compact(ok) if ok else "none"))
    if g.unplaced:
        print("%d orders given before the first known turn start" % len(g.unplaced))
    first_call = first_call_wall(g)
    if first_call:
        w = window_at(g.wins, g.starts, first_call)
        print("calls.jsonl (how each call ended) starts at %s, turn %s" % (clock(first_call), w.turn if w else "?"))


def replayable(notes):
    blocking = ("no save", "save from an abandoned", "no turn window", "turn not over", "no record of turn",
                "ended without ready")
    return not any(n.startswith(blocking) for n in notes)


def compact(turns):
    # [54, 55, 56, 60] -> "54-56, 60"
    out, start, prev = [], None, None
    for t in turns + [None]:
        if start is not None and t == prev + 1:
            prev = t
            continue
        if start is not None:
            out.append("%d" % start if start == prev else "%d-%d" % (start, prev))
        start, prev = t, t
    return ", ".join(out)


def first_call_wall(g):
    rows = read_jsonl(os.path.join(g.dir, "calls.jsonl"))
    return epoch(rows[0]["wall"]) if rows else None


def replay_steps(g, turn, with_failed=False):
    """The orders the replay sends, in order: (order, skip reason or None)."""
    out = []
    for o in g.by_turn.get(turn, []):
        why = None
        if o.code not in (None, 0) and not with_failed:
            why = "failed then: %s" % (o.error or "code %s" % o.code)
        out.append((o, why))
    return out


def cmd_plan(g, turn, thoughts=False):
    w = g.window(turn)
    if w is None:
        print("turn %d: the logs have no stretch of time for it" % turn)
        return 1
    print("Turn %d (%s) of %s" % (turn, year_text(g, turn), g.id))
    save = g.saves.get(turn)
    if save is None:
        print("save:    NONE - this turn can't be loaded")
    elif save["stale"]:
        print("save:    %s (FROM AN ABANDONED TIMELINE)" % save["path"])
    else:
        print("save:    %s" % save["path"])
    if w.end is None:
        print("window:  %s - (still on)" % clock(w.start))
    else:
        print("window:  %s - %s (%d s)" % (clock(w.start), clock(w.end), w.end - w.start))
    if w.next_truth:
        print("compare: the game's record of turn %d (truth.jsonl, %s)" % (turn + 1, clock(w.end)))
    else:
        print("compare: nothing - no record of turn %d" % (turn + 1))
    end = w.end or float("inf")
    changes = ["%s at %s" % (what, clock(t)) for t, what in g.reloads if t < end]
    if changes:
        print("bridge:  now v%s; the last reload before this turn ended: %s" % (bridge_version_now(), changes[-1]))
    else:
        print("bridge:  now v%s; no reload logged" % bridge_version_now())
    notes = turn_notes(g, turn)
    if notes:
        print("notes:   " + "; ".join(notes))
    print()
    rows = [(o.wall, "order", o) for o in g.by_turn.get(turn, [])]
    rows += [(c["wall"], "director", c) for c in g.director if w.start <= c["wall"] < end]
    if thoughts:
        for s in g.seats:
            for t in read_jsonl(os.path.join(g.dir, s["key"], "thoughts.jsonl")):
                tw = epoch(t["wall"])
                if w.start < tw <= end:
                    rows.append((tw, "thought", dict(t, seat=s["key"])))
    rows.sort(key=lambda r: r[0])
    skips = dict((id(o), why) for o, why in replay_steps(g, turn))
    n = 0
    for t, kind, x in rows:
        if kind == "order":
            n += 1
            print("%3d  %s  %-9s p%-2d civ %s%s" % (n, clock(t), x.seat, x.player, show_argv(x.argv),
                                                    order_notes(g, turn, x, skips.get(id(x)))))
        elif kind == "director":
            code = " | ".join(l.strip() for l in x["code"] if l.strip())
            print("     %s  director  python (NOT replayed): %s" % (clock(t), code[:160]))
        else:
            print("     %s  %-9s thinks: %s" % (clock(t), x["seat"], x["text"][:160]))
    if not rows:
        print("(no orders in this turn)")
    for o in g.abandoned.get(turn, []):
        print("     %s  %-9s (thrown away by a reload, NOT replayed) civ %s" % (clock(o.wall), o.seat, o.text[:100]))
    return 0


def order_notes(g, turn, o, skip):
    note = list(o.notes)
    if skip:
        note.append("SKIPPED: " + skip)
    if o.truncated:
        note.append("cut at 500 characters in the log")
    if o.by != "agent":
        note.append("by the %s (not the agent)" % o.by)   # the seat's loop runs civ as "director"
    if o.argv[0] == "answer" and earlier_proposal(g, o, turn):
        note.append("proposal made before the save: not in the replay")
    out = ""
    if note:
        out += "   [" + "; ".join(note) + "]"
    if o.wake:
        out += "   (%s)" % o.wake
    return out


def year_text(g, turn):
    y = g.year(turn)
    if y is None:
        return "?"
    return CIV.year(y)


def show_argv(argv):
    return " ".join('"%s"' % a if " " in a or not a else a for a in argv)


# ---------- run

def seat_by_key(g, key):
    return next(s for s in g.seats if s["key"] == key)


def running_parts(g):
    # the seats' loops and the broker must be stopped: a loaded save would wake them
    out = []
    run = os.path.join(os.path.dirname(os.path.dirname(g.dir)), "run")   # multi.py's pid files, next to games/
    for name in [s["key"] for s in g.seats] + ["broker"]:
        path = os.path.join(run, "%s-%s.pid" % (g.id, name))
        try:
            os.kill(int(open(path).read()), 0)
            out.append(name)
        except (OSError, ValueError):
            pass
    return out


def quick_load():
    """UNTESTED: press Ctrl+L (the game's Quick Load) in the Civ IV window through System Events.
    Needs Accessibility permission for the terminal; CIV_WINDOW names the game's process if it differs."""
    script = ('tell application "System Events"\n'
              '  set civ to first process whose name contains "%s"\n'
              '  set frontmost of civ to true\n'
              '  delay 1\n'
              '  key code 37 using control down\n'     # 37 = L
              'end tell' % CIV_WINDOW)
    subprocess.run(["osascript", "-e", script], check=True, timeout=30)


def bridge_files(bridge):
    # what a replay changes in the bridge folder: the records and the side files, per seat and shared
    out = []
    for name in sorted(os.listdir(bridge)):
        path = os.path.join(bridge, name)
        if os.path.isfile(path) and (name.endswith(".json") or name.endswith(".jsonl")):
            out.append(name)
        elif os.path.isdir(path) and re.match(r"p\d+$", name):
            out += [os.path.join(name, f) for f in sorted(os.listdir(path)) if os.path.isfile(os.path.join(path, f))]
    return out


def copy_files(names, src, dst):
    for name in names:
        if os.path.exists(os.path.join(src, name)):
            os.makedirs(os.path.dirname(os.path.join(dst, name)), exist_ok=True)
            shutil.copy2(os.path.join(src, name), os.path.join(dst, name))


def wait_for(what, check, timeout, every=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = check()
        if r:
            return r
        time.sleep(every)
    raise SystemExit("gave up waiting for %s after %d s" % (what, timeout))


def new_lines(path, pos):
    if not os.path.exists(path):
        return []
    with open(path, errors="replace") as f:
        f.seek(pos)
        return f.read().splitlines()


def size(path):
    return os.path.getsize(path) if os.path.exists(path) else 0


def send(g, order, log_dir, argv):
    # as broker.run_civ: the real civ with that seat's player number, its records kept apart from the game's
    env = dict((k, v) for k, v in os.environ.items() if not k.startswith("CIV_") or k == "CIV_BOTTLE")
    env.update({"CIV_PLAYER": str(order.player), "CIV_GAME": "%s/%s" % (log_dir, order.seat), "CIV_ACTOR": "replay"})
    if argv[0] == "say":
        # civ pairs every message with a thought written just before it
        d = os.path.join(HERE, "games", log_dir, order.seat)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, ".last_thought"), "w").write("replay")
    r = subprocess.run([os.path.join(HERE, "civ")] + argv, capture_output=True, text=True, env=env, timeout=300)
    return r.returncode, (r.stdout + r.stderr).strip()


def map_answer(g, order, events_pos):
    """`civ answer N`: the bridge numbers proposals outside the save, so the same proposal can get another
    number in the replay; find it by its text."""
    if order.argv[0] != "answer" or len(order.argv) < 3 or not order.argv[1].isdigit():
        return order.argv
    made = g.proposals.get(order.seat, {}).get(int(order.argv[1]))
    if made is None:
        return order.argv
    path = os.path.join(g.bridge, "p%d" % order.player, "events.jsonl")
    for line in new_lines(path, events_pos.get(order.player, 0)):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("kind") == "proposal" and e.get("text") == made[1]:
            return ["answer", str(e["id"])] + order.argv[2:]
    return order.argv


def truth_row(path, pos, turn):
    # the game's record of `turn`, written after pos
    for line in new_lines(path, pos):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("turn") == turn:
            return r
    return None


def compare(recorded, replayed):
    out = []
    a = dict((c["id"], c) for c in recorded["civs"])
    b = dict((c["id"], c) for c in replayed["civs"])
    for i in sorted(set(a) | set(b)):
        x, y = a.get(i, {}), b.get(i, {})
        for f in FIELDS:
            if x.get(f) != y.get(f):
                out.append("%s: %s %s -> %s" % (x.get("name") or y.get("name") or i, f, x.get(f), y.get(f)))
    return out


def stamped(*words):
    print(time.strftime("%H:%M:%S"), *words, flush=True)


def cmd_run(g, turn, dry, pace, with_failed):
    w = g.window(turn)
    save = g.saves.get(turn)
    if w is None or save is None:
        print("turn %d can't be replayed: %s" % (turn, "; ".join(turn_notes(g, turn))))
        return 1
    log_dir = "%s/replays/T%03d" % (g.id, turn)
    out_dir = os.path.join(g.dir, "replays", "T%03d" % turn)
    snap = os.path.join(g.dir, "saves", "T%03d_bridge" % turn)
    steps = replay_steps(g, turn, with_failed)
    tell = print
    if dry:
        print("DRY RUN - nothing is changed. A real run would:")
    else:
        tell = stamped
    busy = running_parts(g)
    if busy:
        tell("0. check that the seats' loops and the broker are stopped: now RUNNING: %s (a real run refuses)"
             % ", ".join(busy))
    else:
        tell("0. check that the seats' loops and the broker are stopped: they are")
    if busy and not dry:
        print("stop them first: ./multi.py %s stop" % g.id)
        return 1
    files = bridge_files(g.bridge)
    tell("1. keep a copy of the bridge's records and side files (%d files) in %s/bridge-before" % (len(files), out_dir))
    tell("2. copy %s\n   to   %s" % (save["path"], QUICKSAVE))
    tell("3. press Ctrl+L in the Civ IV window (UNTESTED: osascript, process name contains %r)" % CIV_WINDOW)
    tell("4. wait until bridge.log says the game loaded turn %d (up to 3 min)" % turn)
    if os.path.isdir(snap):
        tell("5. put back the bridge's side files as they were when turn %d began, from %s" % (turn, snap))
    else:
        tell("5. (no snapshot of the bridge's side files for turn %d: unit claims, open proposals and the gate are "
            "today's, not that turn's)" % turn)
    tell("6. send %d orders through civ, as their seats (CIV_PLAYER, CIV_GAME=%s/<seat>), %.1f s apart:" % (
        len([s for s in steps if not s[1]]), log_dir, pace))
    for o, why in steps:
        line = "   %s %-9s p%d civ %s" % (clock(o.wall), o.seat, o.player, show_argv(o.argv))
        if why:
            line += "   SKIPPED: " + why
        elif o.argv[0] == "ready" and played_at_once(g, o.player, turn):
            line += "   (then waits until p%d's part of the turn is played, as in the game)" % o.player
        tell(line)
    readied = set(o.seat for o, why in steps if o.argv[0] == "ready" and not why)
    rest = [s["key"] for s in g.seats if s["key"] not in readied]
    if rest:
        tell("7. say ready for the seats that never did in this turn: %s" % ", ".join(rest))
    if w.next_truth:
        tell("8. wait for the game's record of turn %d (truth.jsonl) and compare it with the original" % (turn + 1))
    else:
        tell("8. wait for the game's record of turn %d (truth.jsonl); THERE IS NO ORIGINAL TO COMPARE" % (turn + 1))
    tell("9. keep the replay's bridge records in %s/bridge-after and put the originals back; then load the "
        "game's latest save to go on with it" % out_dir)
    if dry:
        return 0

    os.makedirs(out_dir, exist_ok=True)
    copy_files(files, g.bridge, os.path.join(out_dir, "bridge-before"))
    try:
        play(g, turn, w, save, snap, steps, rest, log_dir, pace, tell)
    finally:
        # the replay wrote into the game's own records (and a rewind marker): keep its copy, put the originals back
        copy_files(bridge_files(g.bridge), g.bridge, os.path.join(out_dir, "bridge-after"))
        copy_files(files, os.path.join(out_dir, "bridge-before"), g.bridge)
        tell("bridge records put back; load the game's latest save before the seats go on")
    return 0


def play(g, turn, w, save, snap, steps, rest, log_dir, pace, tell):
    """The real run (NEVER TRIED ON THE GAME YET): load the save, send the orders, compare."""
    # read from the original record before the replay adds its own rows to it
    at_once = set(o.player for o, why in steps if o.argv[0] == "ready" and played_at_once(g, o.player, turn))
    os.makedirs(os.path.dirname(QUICKSAVE), exist_ok=True)
    shutil.copy2(save["path"], QUICKSAVE)
    log_path = os.path.join(g.bridge, "bridge.log")
    truth_path = os.path.join(g.bridge, "truth.jsonl")
    log_pos, truth_pos = size(log_path), size(truth_path)
    quick_load()
    wait_for("the load of turn %d" % turn, lambda: any(
        re.search(r"dump ok: load_game turn=%d\b" % turn, l) for l in new_lines(log_path, log_pos)), 180)
    if os.path.isdir(snap):
        # after the load: the load itself clears open proposals and claimed units' targets; the gate stays
        # as the load set it (every seat held)
        keep = [f for f in bridge_files(snap) if os.path.basename(f) in SIDE_FILES
                and os.path.basename(f) not in ("gate.json", "timeline.json")]
        copy_files(keep, snap, g.bridge)
    events_pos = dict((s["player"], size(seat_events(g, s["player"]))) for s in g.seats)
    for o, why in steps:
        if why:
            continue
        time.sleep(pace)
        argv = map_answer(g, o, events_pos)
        begins = size(seat_events(g, o.player))
        code, text = send(g, o, log_dir, argv)
        tell("%s civ %s -> %s" % (o.seat, show_argv(argv), outcome(code, text)))
        if argv[0] == "ready" and o.player in at_once:
            # in the game this civ's part of the turn was played right after its ready, before the next order
            # came: let the game do that again before going on
            if not soft_wait(lambda: '"my_turn_begins"' in "".join(new_lines(seat_events(g, o.player), begins)), 60):
                tell("   (p%d's turn did not begin within 60 s; going on)" % o.player)
    for key in rest:
        s = seat_by_key(g, key)
        code, text = send(g, Order(key, s["player"], time.time(), "ready", "replay"), log_dir, ["ready"])
        tell("%s civ ready (added by the replay) -> %s" % (key, outcome(code, text)))
    row = wait_for("the record of turn %d" % (turn + 1), lambda: truth_row(truth_path, truth_pos, turn + 1), 600)
    if w.next_truth:
        diffs = compare(w.next_truth, row)
        if not diffs:
            tell("turn %d replayed EXACTLY: the record of turn %d matches" % (turn, turn + 1))
        else:
            tell("turn %d replayed with %d differences in the record of turn %d:" % (turn, len(diffs), turn + 1))
        for d in diffs:
            print("   " + d)


def outcome(code, text):
    if code == 0:
        return "ok"
    lines = text.splitlines()
    if not lines:
        return "code %d" % code
    return "code %d: %s" % (code, lines[-1][:200])


def seat_events(g, player):
    return os.path.join(g.bridge, "p%d" % player, "events.jsonl")


def soft_wait(check, timeout):
    try:
        return wait_for("", check, timeout)
    except SystemExit:
        return False


def played_at_once(g, player, turn):
    """Did this civ play its part of `turn` right after its ready (no earlier seat still thinking)?
    The bridge's events: my_turn_begins within 3 s of the first claude_ready of that turn."""
    ready, begins = None, None
    for e in read_jsonl(seat_events(g, player)):
        if e.get("turn") != turn or not e.get("time"):
            continue
        h, m, s = [int(x) for x in e["time"].split(":")]
        t = h * 3600 + m * 60 + s
        if e.get("kind") == "claude_ready" and ready is None:
            ready = t
        elif e.get("kind") == "my_turn_begins" and ready is not None and begins is None:
            begins = t
    return ready is not None and begins is not None and (begins - ready) % 86400 <= 3


def main(argv):
    opts = {"--bridge": BRIDGE, "--games": GAMES}
    for name in opts:
        if name in argv:
            i = argv.index(name)
            opts[name] = os.path.expanduser(argv[i + 1])
            argv = argv[:i] + argv[i + 2:]
    if len(argv) < 2 or argv[1] not in ("index", "plan", "run"):
        print(__doc__.strip())
        return 2
    g = Game(argv[0], opts["--bridge"], opts["--games"])
    if argv[1] == "index":
        cmd_index(g)
        return 0
    if len(argv) < 3:
        print("which turn? replay.py %s %s T" % (argv[0], argv[1]))
        return 2
    turn = int(argv[2].lstrip("T"))
    if argv[1] == "plan":
        return cmd_plan(g, turn, "--thoughts" in argv)
    pace = float(argv[argv.index("--pace") + 1]) if "--pace" in argv else 3.0
    return cmd_run(g, turn, "--dry-run" in argv, pace, "--with-failed" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
