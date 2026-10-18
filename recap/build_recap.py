#!/usr/bin/env python3
"""Recap of one CIVAI game as one self-contained HTML page (for the author, the video editor and the paper).

  python3 ~/civai/recap/build_recap.py [<game-id>] [--bridge DIR] [--no-probe]

Reads the game's logs read-only (games/<id>/, the bridge folder, the seats' git history, the recordings'
file names and lengths, the git history of ~/civai and ~/civai-sdk) and writes, under ~/civai/recap/<id>/:
  data.json    every number and quote the page shows, computed from the logs
  recap.html   the page
The hand-written part (Russian prose, which pairs/scenes to show) lives in ~/civai/recap/<id>/editorial.json;
it names quotes only by their thought id or by an exact substring of a memory file, so every quote on the page
is pulled verbatim from the logs by this script (a reference that no longer matches is dropped and reported).
Rerun it any time while the game goes on: the numbers, the timeline and the charts follow the logs.
"""
import collections
import datetime as D
import glob
import html
import json
import os
import re
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CIVAI = os.path.dirname(HERE)
GAMES = os.path.join(CIVAI, "games")
SDK = os.path.expanduser("~/civai-sdk/src/claude")
BRIDGE_LIVE = os.path.expanduser("~/Library/Application Support/CrossOver/Bottles/%s/drive_c/claude_bridge"
                                 % os.environ.get("CIV_BOTTLE", "civ4"))
STREAMS = os.path.expanduser("~/youtube/raw/civai/streams")
BRIDGE_CLOCK_AHEAD = D.timedelta(hours=1)      # the game's clock runs one hour ahead of the Mac's
sys.path.insert(0, CIVAI)
import timeline  # noqa: E402  (the repo's rewind rules)

RU_LEADER = {"Sitting Bull": "Сидящий Бык", "Genghis Khan": "Чингисхан", "Peter": "Пётр",
             "Montezuma": "Монтесума", "Willem van Oranje": "Виллем ван Оранье", "Justinian I": "Юстиниан I",
             "Victoria": "Виктория", "Zara Yaqob": "Зара Якоб", "Hannibal": "Ганнибал", "Hatshepsut": "Хатшепсут",
             "Charlemagne": "Карл Великий", "Boudica": "Боудикка", "Shaka": "Шака", "Joao II": "Жуан II"}
RU_CIV = {"Native America": "индейцы", "Mongolia": "Монголия", "Russia": "Россия", "Aztec": "ацтеки",
          "Netherlands": "Нидерланды"}
WONDERS = {"ORACLE", "GREAT_LIBRARY", "GREAT_LIGHTHOUSE", "GREAT_WALL", "HANGING_GARDEN", "PYRAMID", "STONEHENGE",
           "COLOSSUS", "PARTHENON", "TEMPLE_OF_ARTEMIS", "STATUE_OF_ZEUS", "MAUSOLEUM_OF_MAUSSOLLOS", "MOAI_STATUES",
           "APOSTOLIC_PALACE", "NOTRE_DAME", "SANKORE", "SISTINE_CHAPEL", "SPIRAL_MINARET", "TAJ_MAHAL",
           "CHICHEN_ITZA", "ANGKOR_WAT", "HAGIA_SOPHIA", "MACHU_PICCHU", "KREMLIN", "SHWEDAGON_PAYA", "HIMEJI_CASTLE",
           "LEANING_TOWER", "VERSAILLES", "STATUE_OF_LIBERTY", "BROADWAY", "ROCKNROLL", "HOLLYWOOD", "EIFFEL_TOWER",
           "CRISTO_REDENTOR", "THREE_GORGES_DAM", "PENTAGON", "UNITED_NATIONS", "SPACE_ELEVATOR", "INTERNET",
           "MAGNA_CARTA", "UNIVERSITY_OF_SANKORE"}
def marker(w):
    # rows of wake_stats.jsonl that are not wake-ups: a refused audience left for later, a turn passed after refusals
    return "skipped" in w or "passed" in w


REFUSED = re.compile(r"safeguards flagged|Usage Policy|content filter|refus", re.I)
TREATIES = ("open borders", "peace", "defensive pact", "permanent alliance")
KIND_RU = {"tech": "технологии", "gold": "золото", "treaty": "договоры", "city": "города", "war": "войны"}


# ---------------------------------------------------------------- small helpers
def rows(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def jload(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def git(cwd, *args):
    try:
        return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True,
                              errors="replace").stdout
    except OSError:
        return ""


def pdt(s):
    return D.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def year_ru(y):
    if y is None:
        return ""
    return "%d г. до н. э." % -y if y < 0 else "%d г." % y


def tname(tech):
    return " ".join(w.capitalize() for w in tech.replace("TECH_", "").split("_")).replace(" Of ", " of ")


def bname(b):
    return " ".join(w.capitalize() for w in b.replace("BUILDING_", "").split("_"))


def with_dates(raw, start_date):
    """Give rows that carry only a time of day ("time": "HH:MM:SS", the game's clock) a full date: the logs are
    written in wall-clock order, so a time earlier than the previous one by hours means midnight passed."""
    day = start_date
    prev = None
    for r in raw:
        t = r.get("time")
        if r.get("wall") and len(str(r["wall"])) >= 19:
            try:
                w = pdt(r["wall"])
                r["_dt"] = w
                day, prev = w.date(), w.time()
                continue
            except ValueError:
                pass
        if not t or not re.match(r"^\d\d:\d\d:\d\d$", str(t)):
            r["_dt"] = None
            continue
        tt = D.datetime.strptime(t, "%H:%M:%S").time()
        if prev is not None and (D.datetime.combine(day, tt) < D.datetime.combine(day, prev) - D.timedelta(hours=6)):
            day = day + D.timedelta(days=1)
        prev = tt
        r["_dt"] = D.datetime.combine(day, tt)
    return raw


# ---------------------------------------------------------------- one game's logs
class Game:
    def __init__(self, gid, bridge):
        self.gid = gid
        self.dir = os.path.join(GAMES, gid)
        self.bridge = bridge
        self.seats = jload(os.path.join(self.dir, "seats.json"), {}).get("seats", [])
        man = jload(os.path.join(self.dir, "manifest.json"), [])
        self.manifest = man if isinstance(man, list) else [man]
        self.truth = rows(os.path.join(bridge, "truth.jsonl"))
        # one row per turn (the last one written wins: a reload rewrites the turns it replays)
        bt = collections.OrderedDict()
        for r in self.truth:
            bt[r["turn"]] = r
        self.turns = [bt[k] for k in sorted(bt)]
        self.by_turn = {r["turn"]: r for r in self.turns}
        self.last = self.turns[-1] if self.turns else {"turn": 0, "civs": [], "year": None}
        civs = self.last.get("civs", [])
        self.name = {c["id"]: "%s (%s)" % (c["name"], c["civ"]) for c in civs}
        self.short = {c["id"]: c["name"] for c in civs}
        self.civ = {c["id"]: c["civ"] for c in civs}
        self.id_of = {}
        for c in civs:
            self.id_of[c["name"]] = c["id"]
            self.id_of["%s (%s)" % (c["name"], c["civ"])] = c["id"]
        self.seat_of = {s["player"]: s for s in self.seats}
        self.players = [s["player"] for s in self.seats]
        self.start_date = pdt(self.turns[0]["time"]).date() if self.turns else D.date.today()
        self.turn_start = {r["turn"]: pdt(r["time"]) - BRIDGE_CLOCK_AHEAD for r in self.turns if r.get("time")}
        self.events = {}
        self.rewinds = []
        for p in sorted(set(self.players) | {c["id"] for c in civs if c.get("agent")}):
            raw = with_dates(rows(os.path.join(bridge, "p%d" % p, "events.jsonl")), self.start_date)
            for r in raw:
                if r.get("kind") == "rewind":
                    w = pdt(r["wall"]) if r.get("wall") else r.get("_dt")
                    key = (fmt(w)[:16] if w else None, r.get("to_turn"))
                    if key not in [(fmt(x[0])[:16] if x[0] else None, x[1]) for x in self.rewinds]:
                        self.rewinds.append((w, r.get("to_turn"), r.get("from_turn")))
            self.events[p] = timeline.current(raw, timeline.event_rewind)
        self.rewinds.sort(key=lambda x: x[0] or D.datetime.min)
        chat = with_dates(rows(os.path.join(bridge, "chat_all.jsonl")), self.start_date)
        self.chat = [c for c in chat if not self.abandoned(c.get("turn"), c.get("_dt"))]
        self.chat_dropped = len(chat) - len(self.chat)

    def abandoned(self, turn, dt_bridge):
        # logged before a reload, for a turn the reload replayed: it never happened in the game as it went on
        if not isinstance(turn, int) or dt_bridge is None:
            return False
        return any(w and dt_bridge < w and turn >= to for (w, to, _f) in self.rewinds)

    def turn_at(self, mac_dt):
        best = None
        for t, s in self.turn_start.items():
            if s <= mac_dt and (best is None or t > best):
                best = t
        return best

    def year(self, t):
        r = self.by_turn.get(t)
        return r.get("year") if r else None

    def ru(self, pid_or_name, civ=True):
        pid = pid_or_name if isinstance(pid_or_name, int) else self.id_of.get(pid_or_name)
        if pid is None:
            return str(pid_or_name)
        n = RU_LEADER.get(self.short.get(pid), self.short.get(pid))
        return "%s (%s)" % (n, RU_CIV.get(self.civ.get(pid), self.civ.get(pid))) if civ else n

    def pid(self, name):
        if name is None:
            return None
        if name in self.id_of:
            return self.id_of[name]
        base = str(name).split(" (")[0]
        return self.id_of.get(base)


# ---------------------------------------------------------------- per-seat logs
def seat_logs(g, s):
    d = os.path.join(g.dir, s["key"])
    out = {"key": s["key"], "player": s["player"], "model": s.get("model"), "harness": s.get("harness"),
           "effort": s.get("effort")}
    th = {t["id"]: t for t in rows(os.path.join(d, "thoughts.jsonl")) if t.get("id")}
    said = []
    for r in rows(os.path.join(d, "said.jsonl")):
        if r.get("by", "agent") != "agent":
            continue
        w = pdt(r["wall"]) if r.get("wall") else None
        r["abandoned"] = g.abandoned(r.get("turn"), w + BRIDGE_CLOCK_AHEAD if w else None)
        t = th.get(r.get("thought_id"))
        r["thought"] = t.get("text") if t else None
        said.append(r)
    out["said"] = said
    out["thoughts"] = list(th.values())
    out["wakes_raw"] = rows(os.path.join(d, "wake_stats.jsonl"))
    out["to_director"] = rows(os.path.join(d, "to_director.jsonl"))
    return out


def git_history(d):
    """Founding persona, every version of ambitions.md, the Stance line of every dossier over time, and the
    director's notes as they arrived (the seat folder is a git repo: one commit per wake-up)."""
    res = {"persona_founding": None, "persona_now": None, "ambitions": [], "stances": [], "director_notes": []}
    if not os.path.isdir(os.path.join(d, ".git")):
        return res
    first = git(d, "log", "--reverse", "--format=%H", "--", "persona.md").split()
    if first:
        res["persona_founding"] = git(d, "show", "%s:persona.md" % first[0]).strip()
    try:
        res["persona_now"] = open(os.path.join(d, "persona.md")).read().strip()
    except OSError:
        pass
    seen = None
    for line in reversed(git(d, "log", "--format=%H|%ad|%s", "--date=iso", "--", "ambitions.md").splitlines()):
        h, ad, subj = line.split("|", 2)
        text = git(d, "show", "%s:ambitions.md" % h).strip()
        if text and text != seen:
            m = re.search(r"turn (\d+)", subj)
            res["ambitions"].append({"turn": int(m.group(1)) if m else None, "wall": ad[:19], "text": text})
            seen = text
    cur_file, cur_turn = None, None
    for line in git(d, "log", "--reverse", "-p", "--format=@@C %ad|%s", "--date=iso", "--", "dossiers").splitlines():
        if line.startswith("@@C "):
            ad, subj = line[4:].split("|", 1)
            m = re.search(r"turn (\d+)", subj)
            cur_turn = int(m.group(1)) if m else None
        elif line.startswith("+++ b/"):
            cur_file = os.path.basename(line[6:])
        elif line.startswith("+") and not line.startswith("+++"):
            m = re.match(r"^\+\W*Stance:?\**\s*(.+)$", line, re.I)
            if m and cur_file:
                res["stances"].append({"turn": cur_turn, "file": cur_file, "stance": m.group(1).strip()})
    cur_turn, cur_wall = None, None
    for line in git(d, "log", "--reverse", "-p", "--format=@@C %ad|%s", "--date=iso", "--",
                    "director_inbox.md").splitlines():
        if line.startswith("@@C "):
            ad, subj = line[4:].split("|", 1)
            m = re.search(r"turn (\d+)", subj)
            cur_turn, cur_wall = (int(m.group(1)) if m else None), ad[:19]
        elif line.startswith("+- ") or line.startswith("+## "):
            res["director_notes"].append({"turn": cur_turn, "wall": cur_wall, "text": line[1:].strip()})
    return res


# ---------------------------------------------------------------- the game's record, merged across seats
def classify_items(items):
    kinds = set()
    for it in items:
        s = it.lower()
        if re.match(r"^\d+ gold", s):
            kinds.add("gold")
        elif s.startswith("the city of"):
            kinds.add("city")
        elif s.startswith("war on") or s.startswith("war with"):
            kinds.add("war")
        elif s == "peace":
            kinds.add("peace")
        elif s in TREATIES:
            kinds.add("treaty")
        else:
            kinds.add("tech")
    return kinds


def deal_kind(kinds):
    for k in ("city", "war"):
        if k in kinds:
            return k
    if "peace" in kinds:
        return "treaty"
    if "tech" in kinds:
        return "tech"
    if "treaty" in kinds:
        return "treaty"
    return "gold"


def merged_record(g):
    agents = set(g.players)
    deals, gifts, wars, peaces, cities, contacts, wonders, religions, goldens, notices, unexplained = \
        [], [], {}, {}, {}, {}, {}, {}, [], [], []
    founded = collections.Counter()
    great = collections.Counter()
    proposals = []
    answers = []
    for p, evs in g.events.items():
        for e in evs:
            k = e.get("kind")
            t = e.get("turn")
            dt = e.get("_dt") - BRIDGE_CLOCK_AHEAD if e.get("_dt") else None
            if k == "deal_done":
                w = g.pid(e.get("with"))
                if w is None:
                    continue
                a, b = sorted((p, w))
                gave, got = list(e.get("gave") or []), list(e.get("got") or [])
                a_gives, b_gives = (gave, got) if p == a else (got, gave)
                key = (a, b, tuple(sorted(a_gives)), tuple(sorted(b_gives)))
                hit = None
                for dd in deals:
                    if dd["key"] == key and abs(dd["turn"] - t) <= 1 and p not in dd["seen_by"]:
                        hit = dd
                        break
                if hit:
                    hit["seen_by"].append(p)
                    continue
                kinds = classify_items(a_gives + b_gives)
                deals.append({"key": key, "turn": t, "a": a, "b": b, "a_gives": a_gives, "b_gives": b_gives,
                              "kind": deal_kind(kinds), "kinds": sorted(kinds), "seen_by": [p], "wall": fmt(dt),
                              "both_agents": a in agents and b in agents,
                              "no_offer": not e.get("by") and not e.get("their_proposal")})
            elif k == "gift_received":
                gifts.append({"turn": t, "from": g.pid(e.get("from")), "to": p, "got": e.get("got"), "wall": fmt(dt)})
            elif k == "war_declared":
                key = (t, g.pid(e.get("team")), g.pid(e.get("against")))
                wars.setdefault(key, {"turn": t, "by": key[1], "against": key[2], "wall": fmt(dt)})
            elif k == "peace_made":
                a, b = g.pid(e.get("team")), g.pid(e.get("against"))
                key = (t,) + tuple(sorted((a or -1, b or -1)))
                peaces.setdefault(key, {"turn": t, "a": a, "b": b, "wall": fmt(dt)})
            elif k == "city_changed_hands":
                key = (t, e.get("name"), e.get("from"), e.get("to"))
                cities.setdefault(key, {"turn": t, "name": e.get("name"), "from": g.pid(e.get("from")),
                                        "from_name": e.get("from"), "to": g.pid(e.get("to")),
                                        "conquest": bool(e.get("conquest")), "x": e.get("x"), "y": e.get("y"),
                                        "wall": fmt(dt)})
            elif k == "first_contact":
                for w in e.get("with") or []:
                    q = g.pid(w)
                    if q is None:
                        continue
                    key = tuple(sorted((p, q)))
                    if key not in contacts or contacts[key]["turn"] > t:
                        contacts[key] = {"turn": t, "a": key[0], "b": key[1], "wall": fmt(dt)}
            elif k == "building_built" and e.get("owner"):
                bb = e.get("building", "").replace("BUILDING_", "")
                if bb in WONDERS and bb not in wonders:
                    wonders[bb] = {"turn": t, "building": bname(e["building"]), "city": e.get("city"),
                                   "owner": g.pid(e.get("owner")), "wall": fmt(dt)}
            elif k == "religion_founded":
                r = e.get("religion")
                if r not in religions:
                    religions[r] = {"turn": t, "religion": r.replace("RELIGION_", "").capitalize(),
                                    "by": g.pid(e.get("by")), "by_text": e.get("by"), "wall": fmt(dt)}
            elif k == "golden_age":
                goldens.append({"turn": t, "who": p})
            elif k == "city_founded" and e.get("owner") and g.pid(e.get("owner")) == p:
                founded[p] += 1
            elif k == "great_person":
                great[p] += 1
            elif k == "civai_notice":
                notices.append({"turn": t, "who": p, "text": e.get("text"), "wall": fmt(dt)})
            elif k == "unexplained_change":
                unexplained.append({"turn": t, "who": p, "with": g.pid(e.get("with")), "window": e.get("window"),
                                    "permanent": e.get("permanent"), "we_got": e.get("we_got"),
                                    "we_gave": e.get("we_gave"), "wall": fmt(dt)})
            elif k == "proposal" and re.search(r"Apostolic Palace|United Nations", e.get("text", "")):
                text = e["text"]
                key = re.sub(r"\(Requires.*?\)", "", text).strip()[:160]
                found = next((v for v in proposals if v["key"] == key and abs(v["turn"] - t) <= 2), None)
                if found is None:
                    proposals.append({"turn": t, "text": text, "key": key, "resident_choice":
                                      text.startswith("As Resident"), "who_asked": [p]})
                elif p not in found["who_asked"]:
                    found["who_asked"].append(p)
            elif k == "proposal_answered" and re.search(r"Apostolic Palace|United Nations", e.get("what", "")):
                key = re.sub(r"\(Requires.*?\)", "", e["what"]).strip()[:160]
                answers.append((key, t, p, {"turn": t, "answer": e.get("answer"), "why": e.get("why"),
                                            "result": e.get("result")}))
    votes = []
    proposals.sort(key=lambda v: v["turn"])
    for v in proposals:
        v["answers"] = {}
    for key, t, p, a in answers:
        cand = [v for v in proposals if v["key"] == key and v["turn"] <= t <= v["turn"] + 3]
        if cand:
            cand[-1]["answers"][str(p)] = a
    for v in proposals:
        v["outcome"] = vote_outcome(g, v, cities)
        votes.append(v)
    deals.sort(key=lambda x: (x["turn"], x["wall"] or ""))
    for dd in deals:
        dd.pop("key", None)
    # one side gives, the other nothing: a gift or a payment by `civ give` (or a treaty the engine signed alone)
    transfers = [dd for dd in deals if not dd["a_gives"] or not dd["b_gives"]]
    deals = [dd for dd in deals if dd["a_gives"] and dd["b_gives"]]
    for tr in transfers:
        tr["giver"], tr["receiver"] = (tr["a"], tr["b"]) if tr["a_gives"] else (tr["b"], tr["a"])
        tr["items"] = tr["a_gives"] or tr["b_gives"]
    return {"deals": deals, "transfers": transfers, "gifts": gifts, "wars": sorted(wars.values(), key=lambda x: x["turn"]),
            "peaces": sorted(peaces.values(), key=lambda x: x["turn"]),
            "cities": sorted(cities.values(), key=lambda x: x["turn"]),
            "contacts": sorted(contacts.values(), key=lambda x: x["turn"]),
            "wonders": sorted(wonders.values(), key=lambda x: x["turn"]),
            "religions": sorted(religions.values(), key=lambda x: x["turn"]), "golden_ages": goldens,
            "cities_founded": {str(k): v for k, v in founded.items()},
            "great_people": {str(k): v for k, v in great.items()},
            "notices": notices, "unexplained": unexplained, "votes": votes}


def vote_outcome(g, v, cities):
    text = v["text"]
    if v["resident_choice"]:
        return None
    m = re.search(r"Assign the \w+ city of (.+?) to (.+?) \(", text)
    if m:
        name, to = m.group(1), g.pid(m.group(2))
        for (t, n, fr, tto), c in cities.items():
            if n == name and c["to"] == to and not c["conquest"] and v["turn"] <= t <= v["turn"] + 2:
                return {"result": "passed", "evidence": "город сменил хозяина на T%d" % t}
        if g.last["turn"] > v["turn"] + 2:
            return {"result": "failed", "evidence": "%s не сменил хозяина к T%d" % (name, v["turn"] + 2)}
        return None
    m = re.search(r"Stop the war against (.+?) \(", text)
    if m:
        who = g.pid(m.group(1))
        before = g.by_turn.get(v["turn"])
        after = g.by_turn.get(v["turn"] + 2)
        if before and after and who is not None:
            wb = {c["id"]: set(c["war"]) for c in before["civs"]}.get(who, set())
            wa = {c["id"]: set(c["war"]) for c in after["civs"]}.get(who, set())
            if wb and wb & wa:
                return {"result": "failed", "evidence": "война идёт и на T%d" % (v["turn"] + 2)}
            if wb and not wa:
                return {"result": "passed or peace by deal", "evidence": "войны нет на T%d" % (v["turn"] + 2)}
    return None


# ---------------------------------------------------------------- numbers per seat
def seat_measures(g, sl, rec, calls, nturns):
    p = sl["player"]
    wakes = [w for w in sl["wakes_raw"] if not marker(w)]
    skipped = [w for w in sl["wakes_raw"] if "skipped" in w]
    passed = [w for w in sl["wakes_raw"] if "passed" in w]
    ok = [w for w in wakes if not w.get("error")]
    u = [w.get("usage") or {} for w in wakes]
    said = [m for m in sl["said"] if not m["abandoned"]]
    mine = [c for c in calls if c.get("seat") == sl["key"]]
    errs = [c for c in mine if c.get("code") or c.get("error")]
    deals = [d for d in rec["deals"] if p in (d["a"], d["b"])]
    refusals = [w for w in wakes if REFUSED.search(w.get("error") or "")]
    kinds = collections.Counter(w.get("kind") or "?" for w in wakes)
    secs = [w.get("seconds", 0) for w in ok]
    return {
        "seat": sl["key"], "player": p, "model": sl["model"], "leader": g.name.get(p),
        "wakes": len(wakes), "wakes_by_kind": dict(kinds), "skipped_audiences": len(skipped),
        "turns_passed": [w.get("turn") for w in passed],
        "failed_wakes": len(wakes) - len(ok), "refusals": len(refusals),
        "forced_ready": sum(1 for w in wakes if w.get("forced_ready")),
        "self_checks": sum(1 for w in wakes if w.get("check")),
        "self_check_fix_commands": sum(len((w.get("check") or {}).get("commands") or []) for w in wakes),
        "seconds_total": round(sum(secs)), "mean_seconds": round(statistics.mean(secs), 1) if secs else None,
        "median_seconds": round(statistics.median(secs), 1) if secs else None,
        "output_tokens": sum(x.get("output_tokens", 0) for x in u),
        "thinking_tokens": sum((x.get("output_tokens_details") or {}).get("thinking_tokens", 0) for x in u),
        "cache_read_tokens": sum(x.get("cache_read_input_tokens", 0) for x in u),
        "cache_write_tokens": sum(x.get("cache_creation_input_tokens", 0) for x in u),
        "input_tokens": sum(x.get("input_tokens", 0) for x in u),
        # the self-check resumes the wake-up's session, and its total_cost_usd is that session's running total
        "cost_usd": round(sum(max(w.get("total_cost_usd") or 0, (w.get("check") or {}).get("total_cost_usd") or 0)
                              for w in wakes), 2),
        "tool_calls": len(mine), "tool_errors": len(errs),
        "tool_error_rate": round(100.0 * len(errs) / len(mine), 1) if mine else None,
        "messages": len(said), "messages_public": sum(1 for m in said if m.get("to") == "all"),
        "messages_private": sum(1 for m in said if m.get("to") != "all"),
        "messages_per_10_turns": round(10.0 * len(said) / max(1, nturns), 1),
        "messages_abandoned": sum(1 for m in sl["said"] if m["abandoned"]),
        "thoughts": len(sl["thoughts"]),
        "deals": len(deals), "deals_by_kind": dict(collections.Counter(d["kind"] for d in deals)),
        "gifts_given": sum(1 for x in rec["transfers"] if x["giver"] == p),
        "gifts_received": sum(1 for x in rec["transfers"] if x["receiver"] == p),
        "wars_declared": sum(1 for w in rec["wars"] if w["by"] == p),
        "cities_taken": sum(1 for c in rec["cities"] if c["to"] == p and c["from"] in g.players),
        "cities_lost": sum(1 for c in rec["cities"] if c["from"] == p),
        "director_reports": len(sl["to_director"]),
    }


def reply_rates(g, seats):
    # of the private messages a leader received, the share answered by a message to the sender within a turn
    sent = []
    for sl in seats:
        for m in sl["said"]:
            if m["abandoned"]:
                continue
            sent.append((sl["player"], g.pid(m.get("to")) if m.get("to") != "all" else None, m.get("turn"),
                         pdt(m["wall"]), set(g.pid(x) for x in (m.get("read_by") or []))))
    out = {}
    for sl in seats:
        me = sl["player"]
        got = [s for s in sent if s[1] == me]
        n = 0
        for (frm, _to, t, w, _r) in got:
            if any(s[0] == me and (s[1] == frm or (s[1] is None and frm in s[4])) and s[3] > w and
                   isinstance(s[2], int) and isinstance(t, int) and s[2] <= t + 1 for s in sent):
                n += 1
        out[str(me)] = {"received": len(got), "answered": n,
                        "rate": round(100.0 * n / len(got), 1) if got else None}
    return out


# ---------------------------------------------------------------- recordings
def recordings(g, cache_path, probe=True):
    cache = jload(cache_path, {}) or {}
    t0 = min(g.turn_start.values()) - D.timedelta(hours=1) if g.turn_start else None
    out = []
    for f in sorted(glob.glob(os.path.join(STREAMS, "*_game*.mp4"))):
        b = os.path.basename(f)
        m = re.match(r"(\d{4}-\d\d-\d\d)_(\d\d)-(\d\d)-(\d\d)_game", b)
        if not m:
            continue
        start = D.datetime.strptime("%s %s:%s:%s" % m.groups(), "%Y-%m-%d %H:%M:%S")
        if t0 and start < t0 - D.timedelta(hours=1):
            continue
        size = os.path.getsize(f)
        key = "%s|%d" % (b, size)
        dur = cache.get(key)
        if dur is None and probe:
            try:
                o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f],
                                   capture_output=True, text=True, timeout=60).stdout.strip()
                dur = float(o.splitlines()[0]) if o else None
            except (OSError, ValueError, subprocess.TimeoutExpired, IndexError):
                dur = None
            if dur:
                cache[key] = dur
        out.append({"file": b, "start": fmt(start), "seconds": dur, "active_cut": "-active" in b})
    try:
        json.dump(cache, open(cache_path, "w"), indent=0)
    except OSError:
        pass
    return out


def find_recording(recs, mac_dt):
    for r in recs:
        if r["seconds"] is None:
            continue
        s = pdt(r["start"])
        if s <= mac_dt < s + D.timedelta(seconds=r["seconds"]):
            off = int((mac_dt - s).total_seconds())
            return {"file": r["file"], "offset": "%d:%02d:%02d" % (off // 3600, off % 3600 // 60, off % 60),
                    "offset_s": off, "cut": r["active_cut"]}
    return None


# ---------------------------------------------------------------- engineering history
def engineering(g, game_start_mac, bridge_log):
    loads = []
    try:
        with open(bridge_log, errors="replace") as f:
            for line in f:
                m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) hot-reloaded bridge v(\d+)", line)
                if m:
                    loads.append((pdt(m.group(1)) - BRIDGE_CLOCK_AHEAD, int(m.group(2)), "hot reload v" + m.group(2)))
                m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) bridge loaded from", line)
                if m:   # the game was started again: it loads whatever bridge is installed
                    loads.append((pdt(m.group(1)) - BRIDGE_CLOCK_AHEAD, 10 ** 6, "restart"))
    except OSError:
        pass
    out = []
    for repo, label in ((CIVAI, "civai"), (SDK, "civai-sdk")):
        since = (game_start_mac - D.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        for line in git(repo, "log", "--since=" + since, "--format=%h|%ad|%s", "--date=format:%Y-%m-%d %H:%M:%S"
                        ).splitlines():
            h, ad, subj = line.split("|", 2)
            cdt = pdt(ad)
            landed, how = None, None
            vm = re.search(r"Bridge v(\d+)(?:-(\d+))?", subj)
            if vm:
                v = int(vm.group(2) or vm.group(1))
                later = sorted(x for x in loads if x[1] >= v and x[0] >= cdt - D.timedelta(minutes=2))
                if later:
                    landed, how = max(later[0][0], cdt), later[0][2]
            if landed is None and (label == "civai-sdk" or subj.startswith("Engine patch")):
                rw = [w - BRIDGE_CLOCK_AHEAD for (w, _to, _f) in g.rewinds if w and w - BRIDGE_CLOCK_AHEAD >= cdt]
                if rw:
                    landed, how = rw[0], "restart + reload"
            if landed is None and subj.startswith("Loop"):
                landed, how = cdt, "next wake-up"
            out.append({"repo": label, "hash": h, "wall": fmt(cdt), "turn_at_commit": g.turn_at(cdt),
                        "subject": subj, "landed": fmt(landed), "landed_turn": g.turn_at(landed) if landed else None,
                        "how": how})
    out.sort(key=lambda x: x["wall"])
    return out


# ---------------------------------------------------------------- earlier tests, same measures
def summarize(gid, bridge):
    if not os.path.isdir(os.path.join(GAMES, gid)) or not os.path.isdir(bridge):
        return None
    g = Game(gid, bridge)
    rec = merged_record(g)
    calls = rows(os.path.join(g.dir, "calls.jsonl"))
    seats = [seat_logs(g, s) for s in g.seats]
    agent_ids = set(g.players)
    elim = {}
    for r in g.turns:
        for c in r["civs"]:
            if c["id"] in agent_ids and c["cities"] == 0 and r["turn"] > 5 and c["id"] not in elim:
                elim[c["id"]] = r["turn"]
    last_alive = max([elim.get(p, g.last["turn"]) for p in agent_ids] or [g.last["turn"]])
    wake_walls = [pdt(w["wall"]) for sl in seats for w in sl["wakes_raw"] if w.get("wall")]
    per = [seat_measures(g, sl, rec, calls, min(elim.get(sl["player"], g.last["turn"]), g.last["turn"]))
           for sl in seats]
    chat_agents = [c for c in g.chat if g.pid(c.get("from")) in agent_ids]
    return {
        "game": gid, "turns_with_agents": last_alive, "last_turn": g.last["turn"],
        "hours": round((max(wake_walls) - min(wake_walls)).total_seconds() / 3600, 1) if wake_walls else None,
        "seats": per, "eliminated": {g.name[p]: t for p, t in elim.items()},
        "controls": [{"leader": g.name[c["id"]], "score": c["score"], "cities": c["cities"]}
                     for c in g.last["civs"] if not c.get("agent") and not c.get("human")],
        "messages": len(chat_agents),
        "deals_between_agents": sum(1 for d in rec["deals"] if d["both_agents"]),
        "deals_all": len(rec["deals"]), "wars": len(rec["wars"]),
        "models": sorted(set("%s/%s" % (s.get("harness"), s.get("model")) for s in g.seats)),
        "cost_usd": round(sum(x["cost_usd"] for x in per), 2),
        "wakes": sum(x["wakes"] for x in per), "tool_calls": sum(x["tool_calls"] for x in per),
        "tool_errors": sum(x["tool_errors"] for x in per),
        "mean_wake_seconds": round(statistics.mean([x["mean_seconds"] for x in per if x["mean_seconds"]]), 1)
        if per else None,
        "calls_per_wake": round(sum(x["tool_calls"] for x in per) / max(1, sum(x["wakes"] for x in per)), 1),
        "refusals": sum(x["refusals"] for x in per),
        "final_scores": {g.name[c["id"]]: c["score"] for c in g.last["civs"] if c["id"] in agent_ids},
    }


# ---------------------------------------------------------------- editorial references, checked against the logs
class Refs:
    def __init__(self, g, seats, hist):
        self.g = g
        self.msg = {}
        self.warn = []
        for sl in seats:
            for m in sl["said"]:
                if m.get("thought_id"):
                    self.msg[m["thought_id"]] = dict(m, sender=sl["player"])
        self.files = {}
        for sl in seats:
            d = os.path.join(g.dir, sl["key"])
            for fn in ("secrets.md", "chronicle.md", "plan.md", "ambitions.md", "persona.md"):
                try:
                    self.files[(sl["key"], fn)] = open(os.path.join(d, fn)).read()
                except OSError:
                    pass
            for f in glob.glob(os.path.join(d, "dossiers", "*.md")):
                self.files[(sl["key"], "dossiers/" + os.path.basename(f))] = open(f).read()
        self.hist = hist

    def quote(self, tid):
        m = self.msg.get(tid)
        if not m:
            self.warn.append("thought id %s not found" % tid)
            return None
        g = self.g
        to = m.get("to")
        rb = [g.pid(x) for x in (m.get("read_by") or [])]
        return {"id": tid, "turn": m.get("turn"), "year": g.year(m.get("turn")), "wall": m.get("wall"),
                "from": m["sender"], "to": "all" if to == "all" else g.pid(to), "readers": [x for x in rb if x],
                "text": m.get("text"), "thought": m.get("thought"), "abandoned": m.get("abandoned")}

    def note(self, seat, fn, substr, turn=None):
        txt = self.files.get((seat, fn), "")
        if substr and substr in txt:
            return {"seat": seat, "file": fn, "text": substr, "turn": turn}
        # the line may have been trimmed since: look in the seat's git history of that file
        d = os.path.join(self.g.dir, seat)
        out = git(d, "log", "-S", substr, "--format=%h|%s", "--", fn) if substr else ""
        if out.strip():
            h, subj = out.splitlines()[-1].split("|", 1)
            return {"seat": seat, "file": fn, "text": substr, "turn": turn, "from_history": subj}
        self.warn.append("note not found in %s/%s: %s" % (seat, fn, (substr or "")[:60]))
        return None


# ---------------------------------------------------------------- build
def build(gid, bridge, probe=True):
    out_dir = os.path.join(HERE, gid)
    os.makedirs(out_dir, exist_ok=True)
    g = Game(gid, bridge)
    rec = merged_record(g)
    calls = rows(os.path.join(g.dir, "calls.jsonl"))
    seats = [seat_logs(g, s) for s in g.seats]
    hist = {sl["key"]: git_history(os.path.join(g.dir, sl["key"])) for sl in seats}
    nturns = g.last["turn"]
    measures = [seat_measures(g, sl, rec, calls, nturns) for sl in seats]
    rr = reply_rates(g, seats)
    for m in measures:
        m["reply"] = rr.get(str(m["player"]))

    # turns: score series, war state, durations, stalls
    series = {str(p): [] for p in g.players}
    wars_by_turn = []
    for r in g.turns:
        cv = {c["id"]: c for c in r["civs"]}
        for p in g.players:
            c = cv.get(p, {})
            series[str(p)].append([r["turn"], c.get("score"), c.get("cities"), c.get("pop"), c.get("techs"),
                                   c.get("military"), c.get("gold")])
        pairs = set()
        for p in g.players:
            for q in (cv.get(p, {}).get("war") or []):
                if q in g.players:
                    pairs.add(tuple(sorted((p, q))))
        wars_by_turn.append([r["turn"], sorted(pairs)])
    # a civilization that falls: the turn it lost its last city (by the record), else the first turn it shows none
    eliminated = {}
    for r in g.turns:
        for c in r["civs"]:
            if c["id"] in g.players and r["turn"] > 5 and (not c.get("alive") or not c.get("cities")) \
                    and c["id"] not in eliminated:
                lost = [x["turn"] for x in rec["cities"] if x["from"] == c["id"]]
                eliminated[c["id"]] = max(lost) if lost else r["turn"]
    dur = []
    ts = sorted(g.turn_start.items())
    for (t1, s1), (t2, s2) in zip(ts, ts[1:]):
        dur.append([t1, round((s2 - s1).total_seconds() / 60, 1)])
    med = statistics.median([d[1] for d in dur]) if dur else 0
    stalls = [{"turn": t, "minutes": m} for t, m in dur if m >= max(10, 4 * med)]

    # refusals (content filter) by kind and by phase
    ref_rows = []
    for sl in seats:
        for w in sl["wakes_raw"]:
            if REFUSED.search(w.get("error") or "") and not marker(w):
                # the game's turn at that moment (a failed wake-up's own turn label can come from its brief's text)
                t = g.turn_at(pdt(w["wall"])) if w.get("wall") else None
                ref_rows.append({"seat": sl["key"], "turn": t, "kind": w.get("kind") or "?", "effort": w.get("effort"), "wall": w.get("wall")})
    phase_w = 50
    by_phase = collections.defaultdict(lambda: collections.Counter())
    for sl in seats:
        for w in sl["wakes_raw"]:
            t = g.turn_at(pdt(w["wall"])) if w.get("wall") else None
            if t is None:
                continue
            ph = "T%d-%d" % (t // phase_w * phase_w, t // phase_w * phase_w + phase_w - 1)
            if marker(w):
                continue
            by_phase[(sl["key"], ph)]["wakes"] += 1
            if REFUSED.search(w.get("error") or ""):
                by_phase[(sl["key"], ph)]["refusals"] += 1
    kinds_all = collections.defaultdict(lambda: collections.Counter())
    for sl in seats:
        for w in sl["wakes_raw"]:
            if marker(w):
                continue
            k = w.get("kind") or "?"
            kinds_all[sl["key"]]["wakes:" + k] += 1
            if REFUSED.search(w.get("error") or ""):
                kinds_all[sl["key"]]["refused:" + k] += 1

    # messages, all of them (current timeline), for the timeline's detail panel
    msgs = []
    for sl in seats:
        for m in sl["said"]:
            msgs.append({"id": m.get("thought_id"), "turn": m.get("turn"), "from": sl["player"],
                         "to": "all" if m.get("to") == "all" else g.pid(m.get("to")),
                         "readers": [g.pid(x) for x in (m.get("read_by") or [])], "text": m.get("text"),
                         "thought": m.get("thought"), "wall": m.get("wall"), "abandoned": m["abandoned"]})
    msgs.sort(key=lambda m: (m["wall"] or ""))
    pair_msgs = collections.Counter()
    for m in msgs:
        if m["abandoned"]:
            continue
        if m["to"] == "all":
            pair_msgs[(m["from"], "all")] += 1
        else:
            pair_msgs[(m["from"], m["to"])] += 1
    msgs_per_turn = collections.Counter(m["turn"] for m in msgs if not m["abandoned"])

    # recordings and the engineering history
    recs = recordings(g, os.path.join(out_dir, "recordings_cache.json"), probe)
    game_start = min(pdt(m["written"]) for m in g.manifest if m.get("written")) if g.manifest else \
        min(g.turn_start.values())
    eng = engineering(g, game_start, os.path.join(bridge, "bridge.log"))
    reports = []
    for sl in seats:
        for r in sl["to_director"]:
            w = pdt(r["wall"]) if r.get("wall") else None
            reports.append({"seat": sl["key"], "player": sl["player"], "wall": r.get("wall"),
                            "turn": g.turn_at(w) if w else None, "text": r.get("text")})
    reports.sort(key=lambda r: r["wall"] or "")

    # earlier tests
    arch = os.path.join(os.path.dirname(bridge.rstrip("/")), "claude_bridge", "archive") \
        if not bridge.rstrip("/").endswith("claude_bridge") else os.path.join(bridge, "archive")
    compare = {}
    for tid, sub in (("2026-10-17-test-c", "test-c"), ("2026-10-17-test-b", "test-b")):
        if tid != gid:
            try:
                compare[tid] = summarize(tid, os.path.join(arch, sub))
            except Exception as ex:  # an old log format must not stop the page
                compare[tid] = {"error": repr(ex)}
    me_sum = {
        "game": gid, "turns_with_agents": nturns, "last_turn": nturns,
        "hours": round((max(pdt(w["wall"]) for sl in seats for w in sl["wakes_raw"] if w.get("wall")) -
                        min(pdt(w["wall"]) for sl in seats for w in sl["wakes_raw"] if w.get("wall"))
                        ).total_seconds() / 3600, 1),
        "seats": measures, "messages": sum(1 for c in g.chat if g.pid(c.get("from")) in set(g.players)),
        "deals_between_agents": sum(1 for d in rec["deals"] if d["both_agents"]), "deals_all": len(rec["deals"]),
        "wars": len(rec["wars"]), "cost_usd": round(sum(x["cost_usd"] for x in measures), 2),
        "wakes": sum(x["wakes"] for x in measures), "tool_calls": sum(x["tool_calls"] for x in measures),
        "tool_errors": sum(x["tool_errors"] for x in measures),
        "mean_wake_seconds": round(statistics.mean([x["mean_seconds"] for x in measures if x["mean_seconds"]]), 1),
        "calls_per_wake": round(sum(x["tool_calls"] for x in measures) / max(1, sum(x["wakes"] for x in measures)), 1),
        "refusals": sum(x["refusals"] for x in measures),
        "models": sorted(set("%s/%s" % (s.get("harness"), s.get("model")) for s in g.seats)),
        "final_scores": {g.name[p]: series[str(p)][-1][1] for p in g.players},
        "eliminated": {g.name[p]: t for p, t in eliminated.items()}, "controls": [],
    }

    saves = sorted(os.path.basename(f) for f in glob.glob(os.path.join(g.dir, "saves", "T*.CivBeyondSwordSave")))
    save_of = {}
    for s in saves:
        m = re.match(r"T(\d+)_", s)
        if m:
            save_of[int(m.group(1))] = s

    ed = jload(os.path.join(out_dir, "editorial.json"), {}) or {}
    refs = Refs(g, seats, hist)

    data = {
        "game": gid, "built": fmt(D.datetime.now()), "turn": nturns, "year": g.last.get("year"),
        "max_turns": None, "settings": None, "bridge": bridge,
        "players": [{"id": p, "seat": g.seat_of[p]["key"], "model": g.seat_of[p].get("model"),
                     "harness": g.seat_of[p].get("harness"), "effort": g.seat_of[p].get("effort"),
                     "leader": g.short.get(p), "civ": g.civ.get(p), "name": g.name.get(p), "ru": g.ru(p, False),
                     "ru_civ": RU_CIV.get(g.civ.get(p), g.civ.get(p)),
                     "now": {k: v for k, v in ({c["id"]: c for c in g.last["civs"]}.get(p) or {}).items()
                             if k in ("score", "cities", "pop", "techs", "military", "gold", "war", "era", "alive",
                                      "units")}}
                    for p in g.players],
        "turns": [{"turn": r["turn"], "year": r.get("year"), "start_mac": fmt(g.turn_start.get(r["turn"]))}
                  for r in g.turns],
        "turn_minutes": dur, "median_turn_minutes": med, "stalls": stalls,
        "eliminated": {str(p): t for p, t in eliminated.items()},
        "series": series, "wars_by_turn": wars_by_turn, "record": rec,
        "rewinds": [{"wall_mac": fmt(w - BRIDGE_CLOCK_AHEAD) if w else None, "to_turn": to, "from_turn": fr}
                    for (w, to, fr) in g.rewinds],
        "chat_rows_dropped_by_rewinds": g.chat_dropped,
        "measures": measures, "refusals": ref_rows,
        "refusals_by_phase": [{"seat": k[0], "phase": k[1], "wakes": v["wakes"], "refusals": v["refusals"]}
                              for k, v in sorted(by_phase.items())],
        "refusals_by_kind": {k: dict(v) for k, v in kinds_all.items()},
        "messages": msgs, "messages_per_turn": {str(k): v for k, v in msgs_per_turn.items()},
        "pair_messages": [{"from": a, "to": b, "n": n} for (a, b), n in sorted(pair_msgs.items(), key=str)],
        "history": hist, "director_reports": reports, "engineering": eng, "recordings": recs,
        "compare": dict(compare, **{gid: me_sum}), "saves": save_of,
    }
    for m in g.manifest:
        gs = m.get("game_settings")
        if gs:
            mt = re.search(r"'max_turns': (\d+)", gs)
            data["max_turns"] = int(mt.group(1)) if mt else None
            data["settings"] = {k: (re.search(r"'%s': u?'?([A-Z_a-z0-9]+)" % k, gs) or [None, None])[1]
                                for k in ("map_size", "difficulty", "speed", "map_w", "map_h")}
            break
    data["manifest_hashes"] = [{"written": m.get("written"), "turn_at_start": (re.search(r"'turn': (\d+)",
                                m.get("game_settings", "")) or [None, None])[1], "hashes": m.get("hashes")}
                               for m in g.manifest]
    data["editorial"] = resolve_editorial(ed, refs, g, data, recs, save_of)
    data["warnings"] = refs.warn
    json.dump(data, open(os.path.join(out_dir, "data.json"), "w"), ensure_ascii=False, indent=1, default=str)
    page = render(data)
    open(os.path.join(out_dir, "recap.html"), "w").write(page)
    return data


def headline(data):
    rec = data["record"]
    ms = data["measures"]
    out = {
        "turn": data["turn"], "messages": sum(m["messages"] for m in ms),
        "deals_agents": sum(1 for d in rec["deals"] if d["both_agents"]),
        "wars": len(rec["wars"]), "peaces": len(rec["peaces"]),
        "cities_changed": sum(1 for c in rec["cities"] if c["from"] in [p["id"] for p in data["players"]]),
        "cities_conquered": sum(1 for c in rec["cities"] if c["conquest"] and c["from"] in
                                [p["id"] for p in data["players"]]),
        "refusals": len(data["refusals"]), "cost": round(sum(m["cost_usd"] for m in ms), 2),
        "wakes": sum(m["wakes"] for m in ms), "tool_calls": sum(m["tool_calls"] for m in ms),
        "thoughts": sum(m["thoughts"] for m in ms), "votes": sum(1 for v in rec["votes"] if not v["resident_choice"]),
    }
    el = data.get("eliminated") or {}
    names = {str(p["id"]): p["ru"] for p in data["players"]}
    out["eliminated_text"] = ("выбыл " + ", ".join("%s (T%s)" % (names[k], v) for k, v in sorted(el.items(), key=lambda x: x[1]))
                              if el else "никто пока не выбыл")
    for p in data["players"]:
        out["score_" + p["seat"]] = p["now"].get("score")
        out["cities_" + p["seat"]] = p["now"].get("cities")
    for m in ms:
        for k in ("messages", "deals", "cost_usd", "tool_error_rate", "mean_seconds", "wakes", "refusals",
                  "forced_ready", "messages_per_10_turns", "gifts_given", "skipped_audiences", "wars_declared"):
            out["%s_%s" % (k, m["seat"])] = m[k]
        out["reply_" + m["seat"]] = (m.get("reply") or {}).get("rate")
        out["turn_wakes_" + m["seat"]] = m["wakes_by_kind"].get("turn", 0)
    seat = {p["id"]: p["seat"] for p in data["players"]}
    for tr in rec["transfers"]:
        k = "%s_%s" % (seat.get(tr["giver"]), seat.get(tr["receiver"]))
        out["n_" + k] = out.get("n_" + k, 0) + 1
        out["gold_" + k] = out.get("gold_" + k, 0) + sum(int(i.split()[0]) for i in tr["items"]
                                                          if re.match(r"^\d+ gold$", i))
    return out


def resolve_editorial(ed, refs, g, data, recs, save_of):
    """Turn the editorial's references (thought ids, note substrings, turns) into verbatim quotes and timings."""
    out = dict(ed)
    hl = headline(data)
    # the engineering log as attributed in the editorial (commits made while the game ran)
    attr = ed.get("attribution") or {}
    during = [e for e in data["engineering"] if e["turn_at_commit"] is not None]
    hl["eng_total"] = len(during)
    for e in during:
        by = (attr.get(e["hash"][:7]) or {}).get("by") or "unattributed"
        hl["eng_" + by] = hl.get("eng_" + by, 0) + 1
    hl["eng_agents"] = sum(v for k, v in hl.items() if k.startswith("eng_sonnet") or k.startswith("eng_opus"))
    sonnet = [m for m in data["measures"] if m["model"] == "sonnet"]
    for k in ("messages", "cost_usd", "tool_error_rate", "mean_seconds", "deals"):
        vals = [m[k] for m in sonnet if m[k] is not None]
        if vals:
            hl["sonnet_%s_min" % k], hl["sonnet_%s_max" % k] = min(vals), max(vals)
    data["headline"] = hl

    def sub(s):
        if not isinstance(s, str):
            return s
        return re.sub(r"\{\{(\w+)\}\}", lambda m: str(hl.get(m.group(1), m.group(0))), s)

    def walk(x):
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return sub(x)
    out = walk(out)

    def q(tid):
        return refs.quote(tid)

    for item in out.get("pairs", []):
        item["q"] = q(item["id"])
    for L in out.get("leaders", {}).values():
        L["pairs_q"] = [x for x in (q(t) for t in L.get("pairs", [])) if x]
        for pr in L.get("promises", []):
            if pr.get("note"):
                n = pr["note"]
                pr["note_q"] = refs.note(n["seat"], n["file"], n["text"], n.get("turn"))
            if pr.get("msg"):
                pr["msg_q"] = q(pr["msg"])
    for b in out.get("bargains", []):
        b["q"] = [x for x in (q(t) for t in b.get("msgs", [])) if x]
    for sc in out.get("scenes", []):
        sc["q"] = [x for x in (q(t) for t in sc.get("quotes", [])) if x]
        t = sc.get("turn")
        sc["year"] = g.year(t)
        when = None
        anchor = sc.get("anchor") or {}
        if anchor.get("msg"):
            qq = q(anchor["msg"])
            when = pdt(qq["wall"]) if qq else None
        elif anchor.get("event"):
            ev = anchor["event"]
            for p, evs in g.events.items():
                for e in evs:
                    if e.get("turn") == t and e.get("kind") == ev.get("kind") and all(
                            str(e.get(k)) == str(v) for k, v in ev.items() if k != "kind"):
                        when = e["_dt"] - BRIDGE_CLOCK_AHEAD if e.get("_dt") else None
                        break
                if when:
                    break
        if when is None and t in g.turn_start:
            when = g.turn_start[t]
        sc["wall_mac"] = fmt(when)
        sc["recording"] = find_recording(recs, when) if when else None
        sc["save"] = save_of.get(t)
        sc["replay"] = "python3 ~/civai/replay.py %s plan %s" % (g.gid, t)
    for n in out.get("notes_quoted", []):
        n["q"] = refs.note(n["seat"], n["file"], n["text"], n.get("turn"))
    return out


# ================================================================ HTML
def esc(s):
    return html.escape("" if s is None else str(s))


LOCK = ('<svg class="lock" viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 7V5a3.5 3.5 0 0 1 7 0v2h.5a1 1 0 0 1 '
        '1 1v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1zm1.5 0h4V5a2 2 0 0 0-4 0z" fill="currentColor"/></svg>')


def render(data):
    P = {p["id"]: p for p in data["players"]}
    ed = data.get("editorial") or {}
    hl = data["headline"]

    def who(pid, civ=False):
        p = P.get(pid)
        if not p:
            return "все" if pid == "all" else esc(pid)
        return '<span class="who c%d">%s%s</span>' % (pid, esc(p["ru"]), (" (%s)" % esc(p["ru_civ"])) if civ else "")

    def tlabel(t):
        y = None
        for r in data["turns"]:
            if r["turn"] == t:
                y = r["year"]
        return "T%s, %s" % (t, year_ru(y)) if y is not None else "T%s" % t

    def quote(q, show_thought=True, compact=False):
        if not q:
            return ""
        if q["to"] == "all":
            aud = "публично, всем"
        else:
            aud = "лично → %s" % who(q["to"])
        readers = ", ".join(P[r]["ru"] for r in q["readers"] if r in P)
        meta = '%s · %s · %s · <span class="muted">читали: %s</span>' % (tlabel(q["turn"]), who(q["from"]), aud,
                                                                         esc(readers or "—"))
        s = '<figure class="pair"><figcaption>%s%s</figcaption><blockquote class="said">%s</blockquote>' % (
            meta, ' <span class="tag">отменённая ветка</span>' if q.get("abandoned") else "", esc(q["text"]))
        if show_thought and q.get("thought"):
            s += ('<blockquote class="thought">%s<span class="tlab">мысль, написанная вместе с сообщением '
                  '(видна только автору)</span>%s</blockquote>') % (LOCK, esc(q["thought"]))
        return s + "</figure>"

    def note(n, label="личная запись"):
        if not n:
            return ""
        src = "%s/%s" % (n["seat"], n["file"])
        return ('<blockquote class="thought note">%s<span class="tlab">%s · %s%s</span>%s</blockquote>' % (
            LOCK, label, esc(src), (" · " + esc(n["from_history"])) if n.get("from_history") else "",
            esc(n["text"])))

    css = CSS
    toc = [("s1", "Игра на одном экране"), ("s2", "Хроника по ходам"), ("s3", "Лидеры"),
           ("s4", "Сказал и подумал"), ("s5", "Дипломатия"), ("s6", "Сцены для видео"), ("s7", "Для статьи"),
           ("s8", "Журнал инженерии"), ("s9", "Приложение")]
    h = []
    h.append('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>CIVAI · %s</title><style>%s</style></head><body>' % (esc(data["game"]), css))
    h.append('<header class="top"><div class="wrap"><div class="kicker">CIVAI · разбор игры · %s</div>'
             '<h1>%s</h1><p class="sub">%s</p></div></header>' % (
                 esc(data["game"]), esc(ed.get("title", "Разбор игры")),
                 "Состояние на %s · игра идёт (до T%s) · страница собрана %s из логов скриптом "
                 "<code>recap/build_recap.py</code>" % (tlabel(data["turn"]), data.get("max_turns") or "?",
                                                        esc(data["built"][:16]))))
    h.append('<nav class="toc" aria-label="Оглавление"><div class="wrap">%s</div></nav>' % "".join(
        '<a href="#%s">%s</a>' % (i, t) for i, t in toc))
    h.append('<main class="wrap">')

    # ---------------- 1
    h.append('<section id="s1"><h2>1. Игра на одном экране</h2>')
    if ed.get("summary"):
        h.append('<div class="lead">%s</div>' % "".join("<p>%s</p>" % esc(x) for x in ed["summary"]))
    tiles = [("сообщений между лидерами", hl["messages"], "said.jsonl, без отменённых откатом ходов"),
             ("сделок между агентами", hl["deals_agents"], "deal_done из events.jsonl, обе стороны склеены"),
             ("объявлений войны", hl["wars"], "war_declared"),
             ("городов сменили хозяина", hl["cities_changed"], "city_changed_hands между агентами (%d захватом)"
              % hl["cities_conquered"]),
             ("отказов фильтра", hl["refusals"], "wake_stats.jsonl: ошибка «safeguards flagged»")]
    h.append('<div class="tiles">%s</div>' % "".join(
        '<div class="tile" title="%s"><div class="num">%s</div><div class="lbl">%s</div></div>' % (esc(src), v, esc(l))
        for l, v, src in tiles))
    st = data.get("settings") or {}
    h.append('<p class="muted">Настройки: карта %s (%s×%s), сложность %s, скорость %s, %s ходов максимум; '
             'встроенный ИИ ни за кого не играет, все пять цивилизаций ведут агенты; ходы одновременные.</p>' % (
                 esc(st.get("map_size")), esc(st.get("map_w")), esc(st.get("map_h")), esc(st.get("difficulty")),
                 esc(st.get("speed")), esc(data.get("max_turns"))))
    h.append('<div class="tbl"><table><thead><tr><th>Лидер</th><th>Модель</th><th>Очки</th><th>Города</th>'
             '<th>Население</th><th>Техн.</th><th>Армия</th><th>Золото</th><th>Воюет с</th></tr></thead><tbody>')
    for p in sorted(data["players"], key=lambda x: -(x["now"].get("score") or 0)):
        n = p["now"]
        h.append('<tr><td>%s</td><td>%s</td><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                 '<td>%s</td><td>%s</td></tr>' % (
                     who(p["id"], True), esc("Claude %s, усилие %s" % (p["model"].capitalize(), p["effort"])),
                     n.get("score"), n.get("cities"), n.get("pop"), n.get("techs"), n.get("military"), n.get("gold"),
                     ("<b>выбыл на T%s</b>" % data["eliminated"][str(p["id"])]) if str(p["id"]) in data["eliminated"]
                     else (", ".join(who(w) for w in n.get("war") or []) or "—")))
    h.append('</tbody></table></div>')
    h.append('<p class="muted">Политика усилия (одна для всех мест): обычный ход — <code>high</code>; основание, '
             'совет и аудиенция — <code>xhigh</code>; повтор после отказа фильтра — <code>high</code>, затем '
             '<code>medium</code>. Харнесс: <code>claude -p</code> (Claude Code), наш текст как весь системный '
             'промпт.</p>')
    h.append('</section>')

    # ---------------- 2 timeline
    h.append('<section id="s2"><h2>2. Хроника по ходам</h2>')
    h.append('<p>Каждая клетка — один ход. Буква — главное событие хода, полоска снизу — сколько сообщений было '
             'написано. Нажмите на клетку: появятся события, сделки и все сообщения этого хода вместе с '
             'мыслями.</p>')
    h.append('<div class="legend">%s</div>' % "".join(
        '<span><b class="ev ev-%s">%s</b> %s</span>' % (k, l, t) for k, l, t in LEG))
    h.append('<div id="tl" class="tl"></div><div id="tld" class="tld" aria-live="polite">'
             '<p class="muted">Выберите ход.</p></div>')
    h.append('<h3>Очки по ходам</h3><div class="chart" id="score"></div>')
    h.append('<p class="muted">Очки — из <code>truth.jsonl</code> (запись режиссёра в начале каждого хода). '
             'Вертикальные пунктиры — откаты (загрузка сохранения).</p>')
    h.append('</section>')

    # ---------------- 3 leaders
    h.append('<section id="s3"><h2>3. Лидеры</h2>')
    hist = data["history"]
    M = {m["player"]: m for m in data["measures"]}
    for p in data["players"]:
        pid = p["id"]
        L = (ed.get("leaders") or {}).get(p["seat"], {})
        hs = hist.get(p["seat"], {})
        m = M[pid]
        h.append('<article class="card lead-card c%d"><h3>%s <span class="muted">· %s · Claude %s</span></h3>' % (
            pid, esc(p["ru"]), esc(p["ru_civ"]), esc(p["model"].capitalize())))
        h.append('<p class="stats">%s очков · %s городов · %s сообщений (%s на 10 ходов) · %s сделок · '
                 'отвечает на %s%% личных писем · %s пробуждений, в среднем %s с · $%s</p>' % (
                     p["now"].get("score"), p["now"].get("cities"), m["messages"], m["messages_per_10_turns"],
                     m["deals"], (m.get("reply") or {}).get("rate"), m["wakes"], m["mean_seconds"], m["cost_usd"]))
        if hs.get("persona_founding"):
            h.append('<details open><summary>Характер — своими словами, при основании (T0)</summary>'
                     '<blockquote class="persona">%s</blockquote></details>' % esc(hs["persona_founding"]))
        if L.get("arc"):
            h.append('<h4>Путь</h4><ol class="arc">%s</ol>' % "".join(
                '<li><b>T%s</b> %s</li>' % (esc(b[0]), esc(b[1])) for b in L["arc"]))
        amb = hs.get("ambitions") or []
        if amb:
            h.append('<h4>Цели (ambitions.md) — как менялись</h4>')
            h.append('<div class="two"><div><div class="muted">первые, T%s</div><pre class="file">%s</pre></div>'
                     '<div><div class="muted">сейчас, T%s</div><pre class="file">%s</pre></div></div>' % (
                         amb[0]["turn"], esc(amb[0]["text"]), amb[-1]["turn"], esc(amb[-1]["text"])))
            if L.get("ambitions_comment"):
                h.append('<p>%s</p>' % esc(L["ambitions_comment"]))
            h.append('<details><summary>Все %d версий целей</summary>%s</details>' % (len(amb), "".join(
                '<div class="ver"><div class="muted">T%s · %s</div><pre class="file">%s</pre></div>' % (
                    a["turn"], esc(a["wall"][11:16]), esc(a["text"])) for a in amb)))
        if L.get("pairs_q"):
            h.append('<h4>Сказал и подумал</h4>' + "".join(quote(q) for q in sorted(L["pairs_q"], key=lambda q: q["turn"] or 0)))
        if L.get("promises"):
            h.append('<h4>Обещания: сдержанные и нарушенные</h4><ul class="prom">')
            for pr in L["promises"]:
                h.append('<li><span class="pill %s">%s</span> %s%s%s</li>' % (
                    esc(pr.get("status")), esc({"kept": "сдержал", "broken": "нарушил", "bent": "обошёл"}.get(
                        pr.get("status"), pr.get("status"))), esc(pr.get("text")),
                    note(pr.get("note_q"), "его личная запись") if pr.get("note_q") else "",
                    quote(pr.get("msg_q")) if pr.get("msg_q") else ""))
            h.append('</ul>')
        st = [s for s in hs.get("stances", [])]
        if st:
            byf = collections.OrderedDict()
            for s in st:
                byf.setdefault(s["file"], [])
                if not byf[s["file"]] or byf[s["file"]][-1]["stance"] != s["stance"]:
                    byf[s["file"]].append(s)
            if L.get("trust"):
                h.append('<h4>Доверие и предательства</h4><p>%s</p>' % esc(L["trust"]))
            h.append('<details><summary>Строка Stance в досье на каждого соседа — все изменения (%d)</summary>' %
                     sum(len(v) for v in byf.values()))
            for f, lst in byf.items():
                h.append('<h5>%s</h5><ul class="stance">%s</ul>' % (esc(f.replace(".md", "")), "".join(
                    '<li><b>T%s</b> %s</li>' % (s["turn"], esc(s["stance"])) for s in lst)))
            h.append('</details>')
        reps = [r for r in data["director_reports"] if r["player"] == pid]
        if reps:
            h.append('<details><summary>Жалобы режиссёру (civ director): %d</summary><ul class="reports">%s</ul>'
                     '</details>' % (len(reps), "".join('<li><b>T%s</b> <span class="muted">%s</span> %s</li>' % (
                         r["turn"], esc((r["wall"] or "")[11:16]), esc(r["text"])) for r in reps)))
        h.append('</article>')
    h.append('</section>')

    # ---------------- 4 pairs
    h.append('<section id="s4"><h2>4. Сказал и подумал</h2>')
    if ed.get("pairs_intro"):
        h.append('<p>%s</p>' % esc(ed["pairs_intro"]))
    for i, it in enumerate(ed.get("pairs", []), 1):
        if not it.get("q"):
            continue
        h.append('<div class="pairbox"><div class="pairhead"><span class="n">%d</span> <span class="pill k">%s</span> '
                 '<b>%s</b></div>%s<p class="why">%s</p></div>' % (
                     i, esc(it.get("label")), esc(it.get("title")), quote(it["q"]), esc(it.get("comment"))))
    h.append('</section>')

    # ---------------- 5 diplomacy
    h.append('<section id="s5"><h2>5. Дипломатия</h2>')
    if ed.get("diplomacy_intro"):
        h.append('<p>%s</p>' % esc(ed["diplomacy_intro"]))
    h.append('<div class="chart" id="net"></div>')
    h.append('<p class="muted">Толщина линии — число двусторонних сделок между парой; цвет — самый частый вид '
             'сделок пары (почти везде — технологии). Наведите или нажмите на линию: разбивка по видам. Односторонние '
             'передачи (подарки и платежи через civ give) — в таблице ниже отдельной колонкой.</p>')
    deals = data["record"]["deals"]
    pids = [p["id"] for p in data["players"]]
    h.append('<h3>Сделки по парам и видам</h3><div class="tbl"><table><thead><tr><th>Пара</th>%s<th>Всего</th>'
             '<th>Передачи A→B / B→A (civ give)</th><th>Сообщений A→B / B→A</th></tr></thead><tbody>' % "".join(
                 '<th>%s</th>' % KIND_RU[k] for k in ("tech", "gold", "treaty", "city", "war")))
    pm = {(x["from"], x["to"]): x["n"] for x in data["pair_messages"]}
    for i, a in enumerate(pids):
        for b in pids[i + 1:]:
            ds = [d for d in deals if {d["a"], d["b"]} == {a, b}]
            c = collections.Counter(d["kind"] for d in ds)
            tr = data["record"]["transfers"]
            tab = sum(1 for x in tr if x["giver"] == a and x["receiver"] == b)
            tba = sum(1 for x in tr if x["giver"] == b and x["receiver"] == a)
            h.append('<tr><td>%s — %s</td>%s<td><b>%d</b></td><td>%s / %s</td><td>%s / %s</td></tr>' % (
                who(a), who(b), "".join('<td>%s</td>' % (c.get(k) or "") for k in ("tech", "gold", "treaty", "city",
                                                                                   "war")),
                len(ds), tab, tba, pm.get((a, b), 0), pm.get((b, a), 0)))
    h.append('</tbody></table></div>')
    h.append('<p class="muted">Публичных сообщений «всем»: %s.</p>' % ", ".join(
        "%s — %d" % (P[a]["ru"], n) for (a, b), n in pm.items() if b == "all"))
    h.append('<h3>Война и мир по ходам</h3><div class="chart" id="warmap"></div>')
    h.append('<p class="muted">Каждая строка — пара лидеров; закрашено, когда в начале хода между ними шла война '
             '(<code>truth.jsonl</code>, поле war).</p>')
    votes = [v for v in data["record"]["votes"]]
    if votes:
        h.append('<h3>Апостольский дворец: все голосования</h3><div class="tbl"><table><thead><tr><th>Ход</th>'
                 '<th>Вопрос</th>%s<th>Итог</th></tr></thead><tbody>' % "".join(
                     '<th>%s</th>' % who(p) for p in pids))
        for v in votes:
            txt = re.sub(r"^The Apostolic Palace vote: ", "", v["text"])
            if v["resident_choice"]:
                txt = "Выбор Резидента: " + re.sub(r"^As Resident of The Apostolic Palace you choose the resolution "
                                                   r"put to the vote: ", "", txt)
            cells = []
            for p in pids:
                a = v["answers"].get(str(p))
                if not a:
                    cells.append('<td class="muted">—</td>')
                else:
                    val = a["answer"]
                    if a.get("result") and v["resident_choice"]:
                        val = "%s: %s" % (val, "; ".join(a["result"]))
                    cells.append('<td>%s%s</td>' % (esc(val), (' <span class="muted">(%s)</span>' % esc(a["why"]))
                                                    if a.get("why") else ""))
            oc = v.get("outcome") or {}
            okey = (ed.get("vote_outcomes") or {}).get(str(v["turn"]))
            h.append('<tr><td>T%s</td><td class="q">%s</td>%s<td>%s</td></tr>' % (
                v["turn"], esc(txt[:260]), "".join(cells),
                esc({"passed": "принято", "failed": "не принято", "passed or peace by deal":
                     "войны нет (принято или мир по сделке)"}.get(oc.get("result"), okey or ("—" if v[
                         "resident_choice"] else "нет в логах"))) +
                (' <span class="muted">(%s)</span>' % esc(oc["evidence"]) if oc.get("evidence") else "")))
        h.append('</tbody></table></div><p class="muted">Ответы — из событий <code>proposal_answered</code> каждого '
                 'места; прочерк — ответа в логе нет (не ответил или голосовать не мог). Итог «принято/не принято» '
                 'выведен скриптом из смены владельца города или из продолжения войны.</p>')
    if ed.get("bargains"):
        h.append('<h3>Заметные торги</h3>')
        for b in ed["bargains"]:
            h.append('<div class="bargain"><h4>%s</h4><p>%s</p>%s</div>' % (esc(b.get("title")), esc(b.get("text")),
                                                                        "".join(quote(q) for q in b["q"])))
    h.append('</section>')

    # ---------------- 6 scenes
    h.append('<section id="s6"><h2>6. Сцены для видео</h2>')
    if ed.get("scenes_intro"):
        h.append('<p>%s</p>' % esc(ed["scenes_intro"]))
    for i, sc in enumerate(ed.get("scenes", []), 1):
        rc = sc.get("recording")
        where = ('<code>%s</code> с <b>%s</b>%s' % (esc(rc["file"]), esc(rc["offset"]),
                                                     " (файл с вырезанными паузами: смещение неточно)" if rc["cut"]
                                                     else "")) if rc else \
            '<span class="pill broken">в записи нет этого момента</span>'
        h.append('<article class="scene"><div class="rank">%d</div><div class="body"><h3>%s</h3>'
                 '<p class="muted">T%s, %s · время на Mac %s</p><p><b>Что происходит:</b> %s</p>'
                 '<p><b>Почему работает:</b> %s</p>%s<ul class="meta"><li>Запись: %s</li><li>Сохранение: '
                 '<code>saves/%s</code></li><li>Переснять: <code>%s</code></li></ul></div></article>' % (
                     i, esc(sc.get("title")), sc.get("turn"), esc(year_ru(sc.get("year"))),
                     esc((sc.get("wall_mac") or "")[11:19]), esc(sc.get("what")), esc(sc.get("why")),
                     "".join(quote(q, show_thought=True) for q in sc.get("q", [])), where, esc(sc.get("save")),
                     esc(sc.get("replay"))))
    if ed.get("cold_open"):
        h.append('<h3>Холодное открытие (60–90 с)</h3><ol>%s</ol>' % "".join("<li>%s</li>" % esc(x)
                                                                             for x in ed["cold_open"]))
    if ed.get("acts"):
        h.append('<h3>Три акта</h3>%s' % "".join('<div class="act"><h4>%s</h4><p>%s</p></div>' % (
            esc(a[0]), esc(a[1])) for a in ed["acts"]))
    h.append('</section>')

    # ---------------- 7 paper
    h.append('<section id="s7"><h2>7. Для статьи</h2>')
    for para in ed.get("method", []):
        h.append('<p>%s</p>' % esc(para))
    h.append('<h3>Показатели по местам</h3><div class="tbl"><table><thead><tr><th>Показатель</th>%s</tr></thead>'
             '<tbody>' % "".join('<th>%s</th>' % who(m["player"]) for m in data["measures"]))
    rowsdef = [("модель", lambda m: "Claude " + m["model"].capitalize()),
               ("пробуждений", "wakes"),
               ("  из них ход / совет / аудиенция / основание", lambda m: " / ".join(
                   str(m["wakes_by_kind"].get(k, 0)) for k in ("turn", "council", "audience", "founding"))),
               ("отказов фильтра (из них пропущенных аудиенций)", lambda m: "%d (%d)" % (
                   m["refusals"], m["skipped_audiences"])),
               ("готовность сказана за агента (forced ready)", "forced_ready"),
               ("секунд на пробуждение, среднее / медиана", lambda m: "%s / %s" % (m["mean_seconds"],
                                                                                   m["median_seconds"])),
               ("всего часов работы модели", lambda m: round(m["seconds_total"] / 3600.0, 1)),
               ("выходных токенов (из них на размышление)", lambda m: "%s (%s)" % (
                   fmtk(m["output_tokens"]), fmtk(m["thinking_tokens"]))),
               ("токенов прочитано из кэша", lambda m: fmtk(m["cache_read_tokens"])),
               ("стоимость, $", "cost_usd"),
               ("вызовов civ", "tool_calls"), ("из них с ошибкой, %", "tool_error_rate"),
               ("сообщений (лично / всем)", lambda m: "%d (%d / %d)" % (m["messages"], m["messages_private"],
                                                                       m["messages_public"])),
               ("сообщений на 10 ходов", "messages_per_10_turns"),
               ("ответил на личных писем, %", lambda m: "%s (%s из %s)" % ((m.get("reply") or {}).get("rate"),
                                                                           (m.get("reply") or {}).get("answered"),
                                                                           (m.get("reply") or {}).get("received"))),
               ("мыслей (civ think)", "thoughts"),
               ("сделок (тех / золото / договор / город / война)", lambda m: "%d (%s)" % (m["deals"], " / ".join(
                   str(m["deals_by_kind"].get(k, 0)) for k in ("tech", "gold", "treaty", "city", "war")))),
               ("подарков отдал", "gifts_given"), ("войн объявил", "wars_declared"),
               ("городов взял у агентов / потерял", lambda m: "%d / %d" % (m["cities_taken"], m["cities_lost"])),
               ("самопроверок (команд-исправлений)", lambda m: "%d (%d)" % (m["self_checks"],
                                                                           m["self_check_fix_commands"])),
               ("жалоб режиссёру", "director_reports")]
    for label, f in rowsdef:
        h.append('<tr><td>%s</td>%s</tr>' % (esc(label), "".join(
            '<td>%s</td>' % esc(f(m) if callable(f) else m.get(f)) for m in data["measures"])))
    h.append('</tbody></table></div>')
    pr = ed.get("promise_ledger_note")
    if pr:
        h.append('<p class="muted">%s</p>' % esc(pr))
    # comparison
    cmp_ = data["compare"]
    order = [k for k in ("2026-10-17-test-b", "2026-10-17-test-c", data["game"]) if cmp_.get(k) and
             not cmp_[k].get("error")]
    h.append('<h3>Тест C → Тест D: главный результат</h3>')
    for para in ed.get("compare_text", []):
        h.append('<p>%s</p>' % esc(para))
    h.append('<div class="tbl"><table><thead><tr><th></th>%s</tr></thead><tbody>' % "".join(
        '<th>%s</th>' % esc({"2026-10-17-test-b": "Тест B", "2026-10-17-test-c": "Тест C"}.get(k, "Тест D (сейчас)"))
        for k in order))
    crow = [("модели мест", lambda c: ", ".join(c["models"])),
            ("мест-агентов", lambda c: len(c["seats"])),
            ("встроенный ИИ (контроль)", lambda c: ", ".join("%s (%s очков)" % (x["leader"], x["score"])
                                                             for x in c.get("controls") or []) or "нет"),
            ("ходов с агентами в игре", "turns_with_agents"),
            ("часов стены (первое — последнее пробуждение)", "hours"),
            ("пробуждений", "wakes"), ("среднее секунд на пробуждение", "mean_wake_seconds"),
            ("вызовов civ на пробуждение", "calls_per_wake"),
            ("ошибок civ, %", lambda c: round(100.0 * c["tool_errors"] / max(1, c["tool_calls"]), 1)),
            ("сообщений между лидерами", "messages"),
            ("сообщений на 10 ходов на место", lambda c: round(10.0 * c["messages"] / max(1, c[
                "turns_with_agents"]) / max(1, len(c["seats"])), 2)),
            ("сделок агент–агент", "deals_between_agents"),
            ("объявлений войны", "wars"),
            ("стоимость, $", "cost_usd"), ("отказов фильтра", "refusals"),
            ("агенты выбыли (ход)", lambda c: ", ".join("%s T%s" % (k.split(" (")[0], v) for k, v in
                                                        (c.get("eliminated") or {}).items()) or "никто"),
            ("очки агентов в конце/сейчас", lambda c: ", ".join("%s %s" % (k.split(" (")[0], v) for k, v in
                                                                 c["final_scores"].items()))]
    for label, f in crow:
        h.append('<tr><td>%s</td>%s</tr>' % (esc(label), "".join('<td>%s</td>' % esc(
            f(cmp_[k]) if callable(f) else cmp_[k].get(f)) for k in order)))
    h.append('</tbody></table></div>')
    for para in ed.get("compare_caveats", []):
        h.append('<p class="muted">%s</p>' % esc(para))
    h.append('<h3>Opus и Sonnet: наблюдения, не выводы</h3>')
    for para in ed.get("opus_vs_sonnet", []):
        h.append('<p>%s</p>' % esc(para))
    h.append('<h3>Фильтр содержимого</h3>')
    for para in ed.get("filter_text", []):
        h.append('<p>%s</p>' % esc(para))
    rk = data["refusals_by_kind"]
    h.append('<div class="tbl"><table><thead><tr><th>Место</th><th>Вид пробуждения</th><th>пробуждений</th>'
             '<th>отказов</th></tr></thead><tbody>')
    for seat, c in rk.items():
        ks = sorted(set(k.split(":", 1)[1] for k in c))
        for k in ks:
            if c.get("refused:" + k) or seat == "opus3":
                h.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                    esc(seat), esc(k), c.get("wakes:" + k, 0), c.get("refused:" + k, 0)))
    h.append('</tbody></table></div>')
    ph = [x for x in data["refusals_by_phase"] if x["seat"] == "opus3" or x["refusals"]]
    h.append('<div class="tbl"><table><thead><tr><th>Место</th><th>Отрезок игры</th><th>пробуждений</th><th>отказов'
             '</th><th>доля</th></tr></thead><tbody>%s</tbody></table></div>' % "".join(
                 '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s%%</td></tr>' % (
                     esc(x["seat"]), esc(x["phase"]), x["wakes"], x["refusals"],
                     round(100.0 * x["refusals"] / max(1, x["wakes"]), 1)) for x in ph))
    sonnet_ref = sum(m["refusals"] for m in data["measures"] if m["model"] != "opus")
    h.append('<p class="muted">У четырёх мест на Sonnet отказов: %d.</p>' % sonnet_ref)
    h.append('<h3>Угрозы достоверности</h3><ul>')
    for para in ed.get("validity", []):
        h.append('<li>%s</li>' % esc(para))
    h.append('<li>Откаты (загрузка сохранения): %s.</li>' % "; ".join(
        "к началу T%s в %s" % (r["to_turn"], (r["wall_mac"] or "")[11:16]) for r in data["rewinds"]))
    if data["stalls"]:
        h.append('<li>Долгие ходы (≥ 10 мин и ≥ 4× медианы %.1f мин): %s.</li>' % (
            data["median_turn_minutes"], ", ".join("T%s — %.0f мин" % (s["turn"], s["minutes"])
                                                   for s in data["stalls"])))
    h.append('</ul>')
    dn = []
    for p in data["players"]:
        for n in data["history"].get(p["seat"], {}).get("director_notes", []):
            if n["text"].startswith("## "):
                continue
            dn.append((n["turn"], n["text"]))
    uniq = collections.OrderedDict()
    for t, txt in dn:
        if txt not in uniq:
            uniq[txt] = t
    h.append('<details><summary>Вмешательства режиссёра: все записки игрокам (%d, только об инструментах)</summary>'
             '<ul class="reports">%s</ul></details>' % (len(uniq), "".join(
                 '<li><b>T%s</b> %s</li>' % (t, esc(txt)) for txt, t in sorted(uniq.items(), key=lambda x: x[1] or 0))))
    h.append('</section>')

    # ---------------- 8 engineering
    h.append('<section id="s8"><h2>8. Журнал инженерии</h2>')
    for para in ed.get("engineering_intro", []):
        h.append('<p>%s</p>' % esc(para))
    attr = ed.get("attribution") or {}
    h.append('<div class="tbl"><table><thead><tr><th>Коммит</th><th>Что</th><th>Кто нашёл</th><th>Сделан</th>'
             '<th>Вступил в силу</th></tr></thead><tbody>')
    for c in data["engineering"]:
        a = attr.get(c["hash"][:7]) or {}
        by = a.get("by")
        byh = "режиссёр" if by == "director" else (who(next((p["id"] for p in data["players"] if p["seat"] == by),
                                                           None)) if by else '<span class="muted">—</span>')
        h.append('<tr><td><code>%s</code><br><span class="muted">%s</span></td><td>%s%s</td><td>%s</td>'
                 '<td>T%s · %s</td><td>%s</td></tr>' % (
                     esc(c["hash"]), esc(c["repo"]), esc(c["subject"]),
                     ('<br><span class="muted">%s</span>' % esc(a["note"])) if a.get("note") else "", byh,
                     c["turn_at_commit"], esc(c["wall"][11:16]),
                     ("T%s (%s)" % (c["landed_turn"], esc(c["how"]))) if c.get("landed") else "—"))
    h.append('</tbody></table></div>')
    if ed.get("open_issues"):
        h.append('<h3>Что ещё открыто</h3><ul>%s</ul>' % "".join('<li>%s</li>' % esc(x) for x in ed["open_issues"]))
    h.append('</section>')

    # ---------------- 9 appendix
    h.append('<section id="s9"><h2>9. Приложение</h2>')
    for para in ed.get("appendix", []):
        h.append('<p>%s</p>' % esc(para))
    h.append('<h3>Определения</h3><dl class="defs">%s</dl>' % "".join(
        '<dt>%s</dt><dd>%s</dd>' % (esc(k), esc(v)) for k, v in DEFS))
    if data.get("warnings"):
        h.append('<p class="muted">Предупреждения сборки: %s</p>' % esc("; ".join(data["warnings"])))
    h.append('<p class="muted">Хэши файлов на каждом запуске игры (manifest.json): %s</p>' % esc("; ".join(
        "%s (ход %s): bridge %s, engine %s" % (m["written"][11:16], m["turn_at_start"], (m["hashes"] or {}).get(
            "bridge"), (m["hashes"] or {}).get("engine_dll")) for m in data["manifest_hashes"])))
    h.append('</section></main>')

    # data for the scripts
    js_data = {
        "players": [{"id": p["id"], "ru": p["ru"]} for p in data["players"]],
        "turns": data["turns"], "series": data["series"], "wars": data["wars_by_turn"],
        "rewinds": data["rewinds"], "events": timeline_events(data), "mpt": data["messages_per_turn"],
        "msgs": [m for m in data["messages"] if not m["abandoned"]],
        "deals": [{k: d[k] for k in ("turn", "a", "b", "a_gives", "b_gives", "kind")} for d in deals],
    }
    h.append('<script>const D=%s;</script><script>%s</script></body></html>' % (
        json.dumps(js_data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"), JS))
    return "".join(h)


def fmtk(n):
    return "%.1f млн" % (n / 1e6) if n >= 1e6 else ("%d тыс." % round(n / 1e3) if n >= 1e3 else str(n))


def timeline_events(data):
    P = {p["id"]: p["ru"] for p in data["players"]}
    rec = data["record"]
    ev = collections.defaultdict(list)

    def n(pid):
        return P.get(pid, str(pid))
    for c in rec["contacts"]:
        ev[c["turn"]].append(["k", "Первый контакт: %s и %s" % (n(c["a"]), n(c["b"]))])
    for w in rec["wars"]:
        ev[w["turn"]].append(["w", "%s объявляет войну: %s" % (n(w["by"]), n(w["against"]))])
    for p in rec["peaces"]:
        ev[p["turn"]].append(["p", "Мир: %s и %s" % (n(p["a"]), n(p["b"]))])
    for c in rec["cities"]:
        ev[c["turn"]].append(["c", "Город %s: %s → %s (%s)" % (c["name"], n(c["from"]) if c["from"] is not None
                                                                 else c["from_name"], n(c["to"]),
                                                                 "захват" if c["conquest"] else "без боя")])
    for wd in rec["wonders"]:
        ev[wd["turn"]].append(["u", "Чудо света: %s — %s (%s)" % (wd["building"], n(wd["owner"]), wd["city"])])
    for r in rec["religions"]:
        ev[r["turn"]].append(["r", "Основана религия: %s (%s)" % (r["religion"], n(r["by"]) if r["by"] is not None
                                                                  else "неизвестная цивилизация")])
    for v in rec["votes"]:
        t = re.sub(r"\(Requires.*?\)", "", v["text"]).replace("The Apostolic Palace vote: ", "")
        if v["resident_choice"]:
            t = "Резидент выбирает вопрос: " + t.split("vote:", 1)[-1][:200]
        oc = (v.get("outcome") or {}).get("result")
        ev[v["turn"]].append(["v", "Апостольский дворец: %s%s" % (t.strip()[:220], (" — " + {
            "passed": "принято", "failed": "не принято"}.get(oc, oc)) if oc else "")])
    for r in data["rewinds"]:
        ev[r["to_turn"]].append(["o", "Откат: загружено сохранение начала T%s (%s)" % (r["to_turn"],
                                                                                     (r["wall_mac"] or "")[11:16])])
    for s in data["stalls"]:
        ev[s["turn"]].append(["s", "Ход длился %.0f мин (медиана %.1f)" % (s["minutes"], data["median_turn_minutes"])])
    for x in data["refusals"]:
        if x["turn"] is not None:
            ev[x["turn"]].append(["f", "Фильтр содержимого отклонил пробуждение %s (%s)" % (x["seat"], x["kind"])])
    for u in rec["unexplained"]:
        ev[u["turn"]].append(["x", "Необъяснённое изменение у %s: %s (окно %s)" % (
            n(u["who"]), ", ".join(u.get("permanent") or []), u.get("window"))])
    for p, t in (data.get("eliminated") or {}).items():
        ev[t].append(["e", "Цивилизация пала: %s потерял последний город" % n(int(p))])
    for gd in rec["golden_ages"]:
        ev[gd["turn"]].append(["g", "Золотой век: %s" % n(gd["who"])])
    return {str(k): v for k, v in ev.items()}


LEG = [("e", "✕", "цивилизация пала"), ("c", "Г", "город сменил хозяина"), ("w", "В", "объявлена война"), ("p", "М", "мир"),
       ("v", "П", "Апостольский дворец"), ("u", "Ч", "чудо света"), ("k", "К", "первый контакт"),
       ("r", "Р", "религия"), ("o", "О", "откат"), ("s", "С", "долгий ход"), ("f", "Ф", "отказ фильтра"),
       ("x", "?", "необъяснённое изменение"), ("g", "З", "золотой век")]

DEFS = [
    ("Ход (T)", "номер хода игры; год — из записи truth.jsonl того же хода."),
    ("Время на Mac", "часы компьютера; часы игры (bridge.log, events) идут на час вперёд, скрипт это вычитает."),
    ("Пробуждение", "один вызов модели (claude -p) по событию игры; виды: основание, совет (раз в 8 ходов или при "
                    "больших новостях), аудиенция (пришло письмо или предложение), ход."),
    ("Сообщение", "строка said.jsonl места (civ say); у каждой есть мысль с тем же id (civ say --think). Сообщения "
                  "ходов, отменённых откатом, не считаются."),
    ("Ответил на личных писем", "доля личных писем лидеру, после которых он сам написал отправителю (лично или "
                                "всем) не позже следующего хода."),
    ("Сделка", "событие deal_done; сделка видна в журналах обеих сторон, скрипт склеивает их (те же стороны, те же "
               "предметы, ±1 ход). Вид: город > война > мир/договор > технология > золото."),
    ("Ошибка civ", "вызов в calls.jsonl с ненулевым кодом выхода или текстом ошибки (в том числе отказ игры "
                   "выполнить приказ)."),
    ("Отказ фильтра", "пробуждение, завершившееся ошибкой API «safeguards flagged this message»; пропущенные "
                      "аудиенции записаны в wake_stats.jsonl отдельной строкой «skipped»."),
    ("Forced ready", "пробуждение на ход закончилось без civ ready, и цикл сказал его за агента."),
    ("Долгий ход", "ход, между началом которого и началом следующего прошло ≥ 10 минут и ≥ 4 медиан."),
    ("Stance", "первая строка досье лидера на соседа (dossiers/*.md); её история — из git-истории папки места.")]


CSS = r"""
:root{--bg:#fcfcfb;--fg:#0b0b0b;--fg2:#52514e;--muted:#6b6a66;--card:#ffffff;--line:#e4e2dc;--soft:#f3f2ee;
--acc:#2a78d6;--warbg:#fde3dc;--thought:#f4f1fb;--thoughtline:#6250d6;--said:#eef5fd;
--c1:#2a78d6;--c2:#eb6834;--c3:#1baf7a;--c4:#c98a00;--c5:#e87ba4;--good:#1b7f3a;--bad:#c23a2b;--mid:#a86b00}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#141413;--fg:#f0efec;--fg2:#c3c2b7;
--muted:#9a998f;--card:#1d1d1b;--line:#33322e;--soft:#25241f;--acc:#3987e5;--warbg:#4a2620;--thought:#24203a;
--thoughtline:#9085e9;--said:#16263a;--c1:#3987e5;--c2:#d95926;--c3:#199e70;--c4:#c98500;--c5:#d55181;
--good:#4cbf6b;--bad:#e66767;--mid:#e0a33a}}
:root[data-theme="dark"]{--bg:#141413;--fg:#f0efec;--fg2:#c3c2b7;--muted:#9a998f;--card:#1d1d1b;--line:#33322e;
--soft:#25241f;--acc:#3987e5;--warbg:#4a2620;--thought:#24203a;--thoughtline:#9085e9;--said:#16263a;--c1:#3987e5;
--c2:#d95926;--c3:#199e70;--c4:#c98500;--c5:#d55181;--good:#4cbf6b;--bad:#e66767;--mid:#e0a33a}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:56px}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",
Roboto,"Helvetica Neue",Arial,sans-serif;overflow-x:hidden}
.wrap{max-width:980px;margin:0 auto;padding:0 16px}
header.top{padding:28px 0 12px;border-bottom:1px solid var(--line)}
.kicker{font-size:13px;color:var(--muted);letter-spacing:.04em;text-transform:uppercase}
h1{font-size:28px;line-height:1.2;margin:6px 0 8px}h2{font-size:23px;margin:40px 0 12px;padding-top:8px;
border-top:2px solid var(--fg)}h3{font-size:18px;margin:26px 0 8px}h4{font-size:15px;margin:18px 0 6px}
h5{font-size:14px;margin:12px 0 4px;color:var(--fg2)}
.sub,.muted{color:var(--muted)}.muted{font-size:14px}
nav.toc{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line)}
nav.toc .wrap{display:flex;gap:6px;overflow-x:auto;padding-top:8px;padding-bottom:8px;scrollbar-width:none}
nav.toc a{flex:0 0 auto;font-size:13px;color:var(--fg2);text-decoration:none;padding:4px 10px;border-radius:999px;
background:var(--soft)}nav.toc a:hover{color:var(--fg)}
code{font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--soft);padding:1px 4px;border-radius:4px;
word-break:break-word}
.lead p{font-size:17px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.tile .num{font-size:30px;font-weight:700;line-height:1.1}.tile .lbl{font-size:13px;color:var(--fg2)}
.tbl{overflow-x:auto;margin:10px 0;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:6px 8px;border-bottom:1px solid var(--line);
text-align:left;vertical-align:top}th{background:var(--soft);font-weight:600}td.q{min-width:220px}
.who{font-weight:600;white-space:nowrap}.who.c1{color:var(--c1)}.who.c2{color:var(--c2)}.who.c3{color:var(--c3)}
.who.c4{color:var(--c4)}.who.c5{color:var(--c5)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:16px 0;
border-top:5px solid var(--acc)}.card.c1{border-top-color:var(--c1)}.card.c2{border-top-color:var(--c2)}
.card.c3{border-top-color:var(--c3)}.card.c4{border-top-color:var(--c4)}.card.c5{border-top-color:var(--c5)}
.card h3{margin-top:4px}.stats{font-size:14px;color:var(--fg2)}
blockquote{margin:6px 0;padding:8px 12px;border-radius:8px}
blockquote.said{background:var(--said);border-left:4px solid var(--acc)}
blockquote.thought{background:var(--thought);border-left:4px dashed var(--thoughtline);font-style:italic}
blockquote.persona{background:var(--soft);white-space:pre-wrap;font-size:14px;border-left:4px solid var(--line)}
.tlab{display:block;font-style:normal;font-size:12px;color:var(--muted);margin-bottom:2px}
.lock{width:12px;height:12px;vertical-align:-1px;margin-right:4px;color:var(--thoughtline);float:left;margin-top:4px}
figure.pair{margin:12px 0}figure.pair figcaption{font-size:13px;color:var(--fg2)}
.pairbox{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:14px 0;background:var(--card)}
.pairhead .n{display:inline-block;min-width:24px;font-weight:700}.why{margin:6px 0 0}
.pill{display:inline-block;font-size:12px;padding:1px 8px;border-radius:999px;background:var(--soft);
color:var(--fg2);font-weight:600;font-style:normal}.pill.kept{background:#d9f2e1;color:#1b5e30}
.pill.broken{background:#f8dcd7;color:#8a2417}.pill.bent{background:#f6ebcf;color:#6f4b00}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]) .pill.kept{background:#1d3b27;color:#9fe0b2}
:root:not([data-theme="light"]) .pill.broken{background:#45211c;color:#f2a99e}
:root:not([data-theme="light"]) .pill.bent{background:#3d3218;color:#ecd08a}}
.tag{font-size:11px;background:var(--warbg);padding:0 6px;border-radius:4px}
pre.file{white-space:pre-wrap;font:12.5px/1.45 ui-monospace,Menlo,monospace;background:var(--soft);padding:8px;
border-radius:6px;margin:4px 0;max-height:320px;overflow:auto}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media (max-width:700px){.two{grid-template-columns:1fr}}
details{margin:8px 0}summary{cursor:pointer;color:var(--fg2);font-size:14px}
ol.arc li,ul.prom li{margin:6px 0}ul.stance,ul.reports{font-size:14px}
.legend{display:flex;flex-wrap:wrap;gap:6px 12px;font-size:13px;color:var(--fg2);margin:8px 0}
.ev{display:inline-block;min-width:18px;text-align:center;border-radius:4px;font-size:11px;font-weight:700;
padding:0 3px;color:#fff;background:#8a8984;font-style:normal}
.ev-e{background:#000}.ev-c{background:#c23a2b}.ev-w{background:#7a1f15}.ev-p{background:#1b7f3a}.ev-v{background:#6250d6}
.ev-u{background:#a86b00}.ev-k{background:#2a78d6}.ev-r{background:#5a6b7c}.ev-o{background:#111;}
.ev-s{background:#6b6a66}.ev-f{background:#b0397a}.ev-x{background:#d4501c}.ev-g{background:#b8930c}
.tl{display:grid;grid-template-columns:repeat(20,1fr);gap:2px;margin:10px 0}
@media (max-width:520px){.tl{grid-template-columns:repeat(10,1fr)}.cell .t{font-size:9px}}
@media (min-width:700px){.tl{grid-template-columns:repeat(30,1fr)}}
.cell{position:relative;aspect-ratio:1/1.25;border:1px solid var(--line);border-radius:3px;background:var(--card);
cursor:pointer;font-size:10px;display:flex;align-items:flex-start;justify-content:center;padding-top:1px;
color:var(--muted);overflow:hidden}
.cell.war{background:var(--warbg)}.cell .ev{font-size:10px;min-width:0;padding:0 2px;margin-top:9px}
.cell .t{position:absolute;top:0;left:2px;font-size:8px}.cell .bar{position:absolute;left:0;bottom:0;
background:var(--acc);opacity:.55;width:100%}
.cell.sel{outline:2px solid var(--fg)}
.tld{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--card);min-height:60px}
.tld ul{padding-left:18px}.tld li{margin:3px 0}
.chart{width:100%;margin:8px 0}.chart svg{width:100%;height:auto;display:block}
.tip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:6px;
padding:6px 8px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.15);z-index:9;max-width:260px}
.scene{display:flex;gap:12px;border:1px solid var(--line);border-radius:10px;padding:12px;margin:14px 0;
background:var(--card)}.scene .rank{font-size:26px;font-weight:800;color:var(--muted);min-width:28px}
.scene .body{min-width:0;flex:1}.scene h3{margin:0 0 4px}ul.meta{font-size:13px;padding-left:18px;color:var(--fg2)}
.act{border-left:3px solid var(--line);padding-left:10px}.bargain{border-left:3px solid var(--acc);padding-left:10px;
margin:14px 0}dl.defs dt{font-weight:600;margin-top:8px}dl.defs dd{margin:0 0 0 0;color:var(--fg2)}
a{color:var(--acc)}
"""

JS = r"""
(function(){
const P={};D.players.forEach(p=>P[p.id]=p.ru);
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const col=id=>css('--c'+id);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const yr=y=>y==null?'':(y<0?(-y)+' г. до н. э.':y+' г.');
const tinfo={};D.turns.forEach(t=>tinfo[t.turn]=t);
const atwar={};D.wars.forEach(w=>atwar[w[0]]=w[1]);
const prio='ecwpvuoskfrxg';
const LET={e:'✕',c:'Г',w:'В',p:'М',v:'П',u:'Ч',k:'К',r:'Р',o:'О',s:'С',f:'Ф',x:'?',g:'З'};
const byT={};D.msgs.forEach(m=>{(byT[m.turn]=byT[m.turn]||[]).push(m)});
const dealsT={};D.deals.forEach(d=>{(dealsT[d.turn]=dealsT[d.turn]||[]).push(d)});
const maxm=Math.max(1,...Object.values(D.mpt));
const tl=document.getElementById('tl'),det=document.getElementById('tld');
let sel=null;
D.turns.forEach(t=>{
  const ev=(D.events[t.turn]||[]);let best=null;
  ev.forEach(e=>{if(best==null||prio.indexOf(e[0])<prio.indexOf(best))best=e[0]});
  const c=document.createElement('button');c.className='cell'+((atwar[t.turn]||[]).length?' war':'');
  c.setAttribute('aria-label','Ход '+t.turn);c.title='T'+t.turn+', '+yr(t.year)+(ev.length?' · '+ev.length+' событий':'');
  c.innerHTML='<span class="t">'+t.turn+'</span>'+(best?'<b class="ev ev-'+best+'">'+LET[best]+'</b>':'')+
   '<span class="bar" style="height:'+Math.round(28*(D.mpt[t.turn]||0)/maxm)+'%"></span>';
  c.onclick=()=>{if(sel)sel.classList.remove('sel');sel=c;c.classList.add('sel');show(t.turn)};
  tl.appendChild(c);
});
function who(id){return id==='all'?'всем':'<span class="who c'+id+'">'+esc(P[id]||id)+'</span>'}
function show(n){
  const t=tinfo[n];let h='<h4>T'+n+', '+yr(t.year)+' <span class="muted">· начало хода на Mac '+esc((t.start_mac||'').slice(11,16))+'</span></h4>';
  const ev=D.events[n]||[];
  if(ev.length)h+='<ul>'+ev.map(e=>'<li><b class="ev ev-'+e[0]+'">'+LET[e[0]]+'</b> '+esc(e[1])+'</li>').join('')+'</ul>';
  const w=atwar[n]||[];if(w.length)h+='<p class="muted">Войны в начале хода: '+w.map(p=>esc(P[p[0]])+' — '+esc(P[p[1]])).join('; ')+'</p>';
  const ds=dealsT[n]||[];
  if(ds.length)h+='<details open><summary>Сделки: '+ds.length+'</summary><ul>'+ds.map(d=>'<li>'+who(d.a)+' даёт: '+esc(d.a_gives.join(', ')||'—')+'; '+who(d.b)+' даёт: '+esc(d.b_gives.join(', ')||'—')+'</li>').join('')+'</ul></details>';
  const ms=byT[n]||[];
  if(ms.length)h+='<details><summary>Сообщения: '+ms.length+' (с мыслями)</summary>'+ms.map(m=>'<figure class="pair"><figcaption>'+who(m.from)+' → '+who(m.to)+' <span class="muted">'+esc((m.wall||'').slice(11,16))+'</span></figcaption><blockquote class="said">'+esc(m.text)+'</blockquote>'+(m.thought?'<blockquote class="thought"><span class="tlab">мысль (видна только автору)</span>'+esc(m.thought)+'</blockquote>':'')+'</figure>').join('')+'</details>';
  if(!ev.length&&!ds.length&&!ms.length)h+='<p class="muted">Ничего заметного в логах.</p>';
  det.innerHTML=h;
}
// tooltip
const tip=document.createElement('div');tip.className='tip';tip.style.display='none';document.body.appendChild(tip);
function tipAt(e,html){tip.innerHTML=html;tip.style.display='block';const x=Math.min(e.pageX+12,window.scrollX+document.documentElement.clientWidth-270);tip.style.left=x+'px';tip.style.top=(e.pageY+12)+'px'}
function tipOff(){tip.style.display='none'}
const NS='http://www.w3.org/2000/svg';
function el(n,a,p){const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);if(p)p.appendChild(e);return e}
// score chart
(function(){
  const box=document.getElementById('score');const W=900,H=340,L=46,R=170,T=12,B=28;
  const ids=Object.keys(D.series);let maxT=0,maxS=0;
  ids.forEach(i=>D.series[i].forEach(r=>{maxT=Math.max(maxT,r[0]);maxS=Math.max(maxS,r[1]||0)}));
  maxS=Math.ceil(maxS/1000)*1000||100;
  const x=t=>L+(W-L-R)*(t-1)/Math.max(1,maxT-1),y=s=>T+(H-T-B)*(1-s/maxS);
  const s=el('svg',{viewBox:'0 0 '+W+' '+H,role:'img','aria-label':'Очки по ходам'},box);
  for(let v=0;v<=maxS;v+=maxS/5){el('line',{x1:L,x2:W-R,y1:y(v),y2:y(v),stroke:css('--line'),'stroke-width':1},s);
    const tx=el('text',{x:L-6,y:y(v)+4,'text-anchor':'end','font-size':11,fill:css('--muted')},s);tx.textContent=Math.round(v)}
  for(let t=0;t<=maxT;t+=25){if(t<1)continue;const tx=el('text',{x:x(t),y:H-8,'text-anchor':'middle','font-size':11,fill:css('--muted')},s);tx.textContent='T'+t}
  D.rewinds.forEach(r=>{el('line',{x1:x(r.to_turn),x2:x(r.to_turn),y1:T,y2:H-B,stroke:css('--muted'),'stroke-dasharray':'3 3'},s)});
  const ends=[];
  ids.forEach(i=>{const pts=D.series[i].filter(r=>r[1]!=null).map(r=>x(r[0]).toFixed(1)+','+y(r[1]).toFixed(1)).join(' ');
    el('polyline',{points:pts,fill:'none',stroke:col(i),'stroke-width':2,'stroke-linejoin':'round'},s);
    const last=D.series[i][D.series[i].length-1];ends.push([y(last[1]),i,last[1]])});
  ends.sort((a,b)=>a[0]-b[0]);let prev=-99;
  ends.forEach(e=>{let yy=Math.max(e[0],prev+14);prev=yy;const tx=el('text',{x:W-R+6,y:yy+4,'font-size':12,fill:css('--fg')},s);tx.textContent=P[e[1]]+' '+e[2];
    el('rect',{x:W-R-2,y:e[0]-1,width:4,height:2,fill:col(e[1])},s)});
  const cross=el('line',{x1:0,x2:0,y1:T,y2:H-B,stroke:css('--fg2'),'stroke-width':1,visibility:'hidden'},s);
  const hit=el('rect',{x:L,y:T,width:W-L-R,height:H-T-B,fill:'transparent'},s);
  hit.addEventListener('mousemove',ev=>{const r=s.getBoundingClientRect();const px=(ev.clientX-r.left)*W/r.width;
    const t=Math.max(1,Math.min(maxT,Math.round(1+(px-L)/(W-L-R)*(maxT-1))));cross.setAttribute('x1',x(t));cross.setAttribute('x2',x(t));cross.setAttribute('visibility','visible');
    const rowsH=ids.map(i=>{const r=D.series[i].find(q=>q[0]===t);return [r?r[1]:null,i,r]}).sort((a,b)=>(b[0]||0)-(a[0]||0))
      .map(a=>'<div><span class="who c'+a[1]+'">'+esc(P[a[1]])+'</span>: '+a[0]+(a[2]?' <span class="muted">· '+a[2][2]+' гор., '+a[2][4]+' техн.</span>':'')+'</div>').join('');
    tipAt(ev,'<b>T'+t+', '+yr((tinfo[t]||{}).year)+'</b>'+rowsH)});
  hit.addEventListener('mouseleave',()=>{tipOff();cross.setAttribute('visibility','hidden')});
})();
// war map
(function(){
  const box=document.getElementById('warmap');if(!box)return;const ids=D.players.map(p=>p.id);const pairs=[];
  for(let i=0;i<ids.length;i++)for(let j=i+1;j<ids.length;j++)pairs.push([ids[i],ids[j]]);
  const maxT=D.turns.length?D.turns[D.turns.length-1].turn:1;const W=900,L=270,rh=18,H=pairs.length*rh+24;
  const s=el('svg',{viewBox:'0 0 '+W+' '+H,role:'img','aria-label':'Войны по ходам'},box);
  const x=t=>L+(W-L-8)*(t-1)/maxT;
  pairs.forEach((p,k)=>{const yy=k*rh;const tx=el('text',{x:L-6,y:yy+13,'text-anchor':'end','font-size':11.5,fill:css('--fg2')},s);tx.textContent=P[p[0]]+' — '+P[p[1]];
    el('rect',{x:L,y:yy+3,width:W-L-8,height:rh-6,fill:css('--soft')},s);
    D.wars.forEach(w=>{if(w[1].some(q=>q[0]===p[0]&&q[1]===p[1])){const r=el('rect',{x:x(w[0]),y:yy+3,width:Math.max(1.2,(W-L-8)/maxT+0.3),height:rh-6,fill:css('--bad')},s);
      r.addEventListener('mousemove',e=>tipAt(e,'T'+w[0]+': война '+esc(P[p[0]])+' — '+esc(P[p[1]])));r.addEventListener('mouseleave',tipOff)}})});
  for(let t=25;t<=maxT;t+=25){const tx=el('text',{x:x(t),y:H-6,'text-anchor':'middle','font-size':11,fill:css('--muted')},s);tx.textContent='T'+t}
})();
// network
(function(){
  const box=document.getElementById('net');if(!box)return;const ids=D.players.map(p=>p.id);const W=900,H=460,cx=450,cy=230,R=170;
  const s=el('svg',{viewBox:'0 0 '+W+' '+H,role:'img','aria-label':'Сеть сделок'},box);
  const pos={};ids.forEach((id,k)=>{const a=-Math.PI/2+2*Math.PI*k/ids.length;pos[id]=[cx+R*1.6*Math.cos(a),cy+R*Math.sin(a)]});
  const KC={tech:'--muted',gold:'--mid',treaty:'--good',city:'--bad',war:'--fg'};const KR={tech:'технологии',gold:'золото',treaty:'договоры',city:'города',war:'войны'};
  let max=1;const agg={};
  D.deals.forEach(d=>{const k=Math.min(d.a,d.b)+'-'+Math.max(d.a,d.b);(agg[k]=agg[k]||{n:0,c:{}});agg[k].n++;agg[k].c[d.kind]=(agg[k].c[d.kind]||0)+1;max=Math.max(max,agg[k].n)});
  Object.entries(agg).forEach(([k,v])=>{const [a,b]=k.split('-').map(Number);const dom=Object.entries(v.c).sort((p,q)=>q[1]-p[1])[0][0];
    const ln=el('line',{x1:pos[a][0],y1:pos[a][1],x2:pos[b][0],y2:pos[b][1],stroke:css(KC[dom]),'stroke-width':(2+14*v.n/max).toFixed(1),'stroke-linecap':'round',opacity:.75},s);
    const mx=(pos[a][0]+pos[b][0])/2,my=(pos[a][1]+pos[b][1])/2;const t=el('text',{x:mx,y:my-6,'text-anchor':'middle','font-size':13,'font-weight':700,fill:css('--fg'),'paint-order':'stroke',stroke:css('--bg'),'stroke-width':4},s);t.textContent=v.n;
    const html='<b>'+esc(P[a])+' — '+esc(P[b])+'</b>: '+v.n+' сделок<br>'+Object.entries(v.c).map(([kk,n])=>esc(KR[kk])+': '+n).join(', ');
    [ln,t].forEach(o=>{o.addEventListener('mousemove',e=>tipAt(e,html));o.addEventListener('mouseleave',tipOff);o.addEventListener('click',e=>tipAt(e,html))})});
  ids.forEach(id=>{el('circle',{cx:pos[id][0],cy:pos[id][1],r:26,fill:col(id),stroke:css('--bg'),'stroke-width':3},s);
    const t=el('text',{x:pos[id][0],y:pos[id][1]+(pos[id][1]>cy?44:-34),'text-anchor':'middle','font-size':14,'font-weight':600,fill:css('--fg')},s);t.textContent=P[id]});
  let lx=10;Object.entries(KR).forEach(([k,l])=>{el('rect',{x:lx,y:H-18,width:14,height:6,fill:css(KC[k])},s);const t=el('text',{x:lx+18,y:H-11,'font-size':12,fill:css('--fg2')},s);t.textContent=l;lx+=110});
})();
})();
"""


def main():
    args = sys.argv[1:]
    bridge = BRIDGE_LIVE
    probe = True
    if "--bridge" in args:
        i = args.index("--bridge")
        bridge = os.path.expanduser(args[i + 1])
        del args[i:i + 2]
    if "--no-probe" in args:
        args.remove("--no-probe")
        probe = False
    gid = args[0] if args else open(os.path.join(GAMES, "CURRENT")).read().strip()
    data = build(gid, bridge, probe)
    hl = data["headline"]
    print("recap %s at T%s: %s messages, %s agent deals, %s wars, %s cities changed hands, %s refusals" % (
        gid, data["turn"], hl["messages"], hl["deals_agents"], hl["wars"], hl["cities_changed"], hl["refusals"]))
    for w in data["warnings"]:
        print("warning:", w)
    print(os.path.join(HERE, gid, "recap.html"))


if __name__ == "__main__":
    main()
