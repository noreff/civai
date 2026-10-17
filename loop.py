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
BRIDGE = os.path.expanduser("~/Library/Application Support/CrossOver/Bottles/civ4/drive_c/claude_bridge")
EVENTS = os.path.join(BRIDGE, "events.jsonl")
CHAT = os.path.join(BRIDGE, "chat.jsonl")
WAKE_KINDS = ("message_from_player", "claude_wake", "player_waiting", "deal_done", "deal_declined",
              "deal_failed", "native_deal")
NOISE = ("auto_ready", "claude_ready", "my_turn_begins", "player_turn_begins", "combat_animal")
MEMORY = ("persona.md", "ambitions.md", "plan.md", "secrets.md", "chronicle.md")
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


def fmt_event(e):
    skip = ("kind", "turn", "year", "time")
    rest = ", ".join("%s=%s" % (k, v) for k, v in e.items() if k not in skip)
    return "T%s %s %s" % (e.get("turn"), e.get("kind"), rest)


def brief(events, chat, reasons):
    parts = ["# Wake-up: " + "; ".join(reasons), "",
             "## Since your last wake-up", ""]
    shown = [fmt_event(e) for e in events if e.get("kind") not in NOISE]
    parts += shown[-40:] or ["(no game events)"]
    parts += ["", "## Chat since your last wake-up", ""]
    parts += ["T%s %s: %s" % (c.get("turn"), c.get("from"), c.get("text")) for c in chat[-20:]] or ["(none)"]
    parts += ["", "## State now", "", civ("status"), "", civ("research"), "", civ("offers"), "", civ("gate")]
    return "\n".join(parts)


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
    # fixed parts first (they stay cached between wake-ups), fresh parts last
    return "\n\n".join([
        "You are playing the current CIVAI game. This is ONE wake-up: act on it and finish. "
        "You remember nothing between wake-ups except the files in the game folder, so before you finish, "
        "write down in them whatever your future self must know. The playbook is your full instruction set; "
        "skip its 'Start of a session' and 'Turn loop' listening steps: the loop wakes you.",
        "# PLAYBOOK\n\n" + playbook,
        "# YOUR MEMORY FILES (game folder: %s)\n\n" % d + "\n\n".join(memory),
        "# BRIEF\n\n" + brief(events, chat, reasons),
    ])


def run_agent(cfg, prompt):
    cmd = [a.replace("{prompt}", prompt) for a in cfg["agent"]]
    stdin = None if any("{prompt}" in a for a in cfg["agent"]) else prompt
    t0 = time.time()
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, cwd=HERE,
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
            out.append('the human wrote: "%s"' % e.get("text"))
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
