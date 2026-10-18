#!/usr/bin/env python3
"""CIVAI loop: plays a civ with any model, one fresh call per wake-up.

Nothing piles up in a model's context: every wake-up gets the playbook, the game's
memory files and a fresh brief (state + what happened since the last wake-up), the
model acts through `civ` commands and updates its files, and the call ends.

  ./loop.py                 play with the model command from loop.json ("agent")
  ./loop.py --once          handle one wake-up now and exit (for testing)
  ./loop.py --dry-run       print the prompt of the next wake-up and exit

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


def civ(*args):
    r = subprocess.run([os.path.join(HERE, "civ")] + list(args), capture_output=True, text=True, timeout=180)
    return (r.stdout + r.stderr).strip()


def game_dir():
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
    if not _human:
        m = re.search(r"^  (.+?) of (.+?) \[HUMAN\]", civ("status"), re.M)
        if m:
            _human.append("%s (%s)" % (m.group(1), m.group(2)))
    return _human[0] if _human else "the human leader"


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
    recent, _ = read_from(CHAT, 0)
    now = game_turn()
    recent = [c for c in recent if not isinstance(c.get("turn"), int) or c["turn"] <= now]
    parts += ["%sT%s %s: %s" % ("NEW " if json.dumps(c, sort_keys=True) in new_ids and c.get("from") != "claude" else "    ", c.get("turn"),
              "you" if c.get("from") == "claude" else human_name(), c.get("text")) for c in recent[-CHAT_LINES:]] or ["(none)"]
    parts += ["", "## Your last wake-ups (what you did)", ""]
    parts += recent_wakes(3, now) or ["(none)"]
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


def recent_wakes(n, now=10 ** 6):
    # short-term memory: the final words of the last few wake-ups (none from turns after `now`)
    _, d = game_dir()
    names = sorted(os.listdir(os.path.join(d, "wakes")), key=lambda x: os.path.getmtime(os.path.join(d, "wakes", x)))
    names = [x for x in names if not re.match(r"T(\d+)-", x) or int(re.match(r"T(\d+)-", x).group(1)) <= now]
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


def run_agent(cfg, prompt):
    cmd = [a.replace("{prompt}", prompt) for a in cfg["agent"]]
    if cmd and os.path.basename(cmd[0]) == "claude":
        cmd += ["--append-system-prompt-file", SYSTEM_FILE]
    stdin = None if any("{prompt}" in a for a in cfg["agent"]) else prompt
    t0 = time.time()
    try:
        env = {k: v for k, v in os.environ.items() if not k.startswith("CIV_") or k in ("CIV_BOTTLE", "CIV_GAME")}
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, cwd=HERE, env=env,
                           timeout=cfg.get("timeout_minutes", 15) * 60)
        out = r.stdout.strip() or r.stderr.strip()
    except subprocess.TimeoutExpired:
        out = "(timed out)"
    return out, time.time() - t0


def lines_since(path, pos):
    rows, _ = read_from(path, pos)
    return rows


def handle(cfg, d, st, events, chat, reasons):
    gid = os.path.basename(d)
    turn = next((e.get("turn") for e in reversed(events) if e.get("turn") is not None), "?")
    cmds_path, thoughts_path = os.path.join(d, "commands.jsonl"), os.path.join(d, "thoughts.jsonl")
    prompt = prompt_for(d, events, chat, reasons)   # the loop's own lookups happen here, before the marks
    m = re.search(r"Turn (\d+),", prompt)
    if m:
        turn = m.group(1)
    cmds_pos = os.path.getsize(cmds_path) if os.path.exists(cmds_path) else 0
    th_pos = os.path.getsize(thoughts_path) if os.path.exists(thoughts_path) else 0
    out, secs = run_agent(cfg, prompt)
    agent_cmds = lines_since(cmds_path, cmds_pos)
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
    log += ["", "**Final words:**", "", out[-3000:], "",
            "_%.0f s, prompt ~%d tokens%s_" % (secs, len(prompt) // 4, ", ready said by the loop" if forced else "")]
    name = "T%s-%s.md" % (str(turn).zfill(3), time.strftime("%H%M%S"))
    open(os.path.join(d, "wakes", name), "w").write("\n".join(log))
    print(time.strftime("%H:%M:%S"), "wake-up done:", "; ".join(reasons), "(%.0f s)%s" % (secs, " +forced ready" if forced else ""),
          flush=True)


def reasons_of(events):
    out = []
    for e in events:
        k = e.get("kind")
        if k not in WAKE_KINDS:
            continue
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
    gid, d = game_dir()
    st = load_state(d)
    print("CIVAI loop on game %s (agent: %s)" % (gid, cfg["agent"][0]), flush=True)
    while True:
        events, epos = read_from(EVENTS, st["events_pos"])
        reasons = reasons_of(events)
        if not reasons and not (once or dry):
            time.sleep(1)
            continue
        if reasons:
            time.sleep(GATHER_SECONDS)              # let the burst finish
            events, epos = read_from(EVENTS, st["events_pos"])
            reasons = reasons_of(events)
        chat, cpos = read_from(CHAT, st["chat_pos"])
        if dry:
            print(prompt_for(d, events, chat, reasons or ["(dry run)"]))
            return
        handle(cfg, d, st, events, chat, reasons or ["manual run"])
        st["events_pos"], st["chat_pos"] = epos, cpos
        save_state(d, st)
        if once:
            return


if __name__ == "__main__":
    main()
