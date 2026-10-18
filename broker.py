#!/usr/bin/env python3
"""The seats' doorway to the game: runs `civ` for a sandboxed agent as its own seat, and only as that.

Each agent runs in a macOS sandbox that hides the bridge folder and every other seat's files. Its
`civ` is a thin client (CIV_BROKER set) that sends the command line and the seat's token here; the
broker runs the real `civ` with that seat's player number and folder. The token lives in the seat's
own folder, which no other seat can read, so a model can neither read another player's messages nor
act for another civilization, whatever it types.

  broker.py <game-id>       serve the seats listed in games/<game-id>/seats.json
seats.json: {"seats": [{"key": "claude", "player": 1, "readonly": false}, ...]}
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(HERE, "run")
SOCKET = os.path.join(RUN, "broker.sock")
TOKEN_NAME = ".seat_token"


def seats(game):
    return json.load(open(os.path.join(HERE, "games", game, "seats.json")))["seats"]


def issue_tokens(game):
    # a fresh token per seat per broker start, written into that seat's own folder
    table = {}
    for s in seats(game):
        d = os.path.join(HERE, "games", game, s["key"])
        os.makedirs(d, exist_ok=True)
        tok = secrets.token_hex(16)
        path = os.path.join(d, TOKEN_NAME)
        with open(path, "w") as f:
            f.write(tok)
        os.chmod(path, 0o600)
        table[tok] = dict(s, game=game)
    return table


def run_civ(seat, argv):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CIV_") or k == "CIV_BOTTLE"}
    env.update({"CIV_PLAYER": str(seat["player"]), "CIV_GAME": "%s/%s" % (seat["game"], seat["key"]),
                "CIV_ACTOR": "agent"})
    if seat.get("readonly"):
        env["CIV_READONLY"] = "1"
    t0 = time.time()
    r = subprocess.run([os.path.join(HERE, "civ")] + argv, capture_output=True, text=True, env=env, timeout=300)
    # every call and how it ended, for the record (outside the seats' folders: no seat reads it)
    err = (r.stderr.strip() or (r.stdout.strip() if r.stdout.lstrip().startswith("ERROR") else "")).splitlines()
    row = {"wall": time.strftime("%Y-%m-%d %H:%M:%S"), "seat": seat["key"], "argv": " ".join(argv)[:300],
           "code": r.returncode, "error": err[0][:300] if err else None, "seconds": round(time.time() - t0, 2)}
    with open(os.path.join(HERE, "games", seat["game"], "calls.jsonl"), "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"out": neutral(r.stdout), "err": neutral(r.stderr), "code": r.returncode}


# the bridge's internal names (it began as Claude's): a seat reads neutral ones, whichever model it is
NEUTRAL = (("claude_wake", "turn_wake"), ("claude_ready", "turn_ready"), ("claude_bridge", "bridge"),
           ("ClaudeBridge", "Bridge"))


def neutral(text):
    for a, b in NEUTRAL:
        text = text.replace(a, b)
    return text


def serve(game):
    table = issue_tokens(game)
    os.makedirs(RUN, exist_ok=True)
    if os.path.exists(SOCKET):
        os.remove(SOCKET)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET)
    srv.listen(16)
    print("broker for %s: %d seats on %s" % (game, len(table), SOCKET), flush=True)

    def handle(conn):
        with conn:
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            try:
                req = json.loads(data)
                seat = table.get(req.get("token"))
                if seat is None:
                    reply = {"out": "", "err": "ERROR: this seat is not known to the game\n", "code": 1}
                else:
                    reply = run_civ(seat, [str(a) for a in req.get("argv", [])])
            except Exception as e:   # one bad request must not stop the game
                reply = {"out": "", "err": "ERROR: %s\n" % e, "code": 1}
            conn.sendall(json.dumps(reply).encode() + b"\n")

    threading.Thread(target=keep_saves, args=(game,), daemon=True).start()
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


AUTOSAVES = os.path.expanduser("~/Library/Application Support/CrossOver/Bottles/%s/drive_c/users/crossover/Documents/"
                               "My Games/Beyond the Sword/Saves/single/auto" % os.environ.get("CIV_BOTTLE", "civ4"))


def keep_saves(game):
    # the game keeps only its last few autosaves: copy each one into the game's folder as it appears,
    # so every turn can be loaded again later (replays, re-recording the map for the video)
    import shutil
    import time
    dest = os.path.join(HERE, "games", game, "saves")
    os.makedirs(dest, exist_ok=True)
    while True:
        try:
            for name in os.listdir(AUTOSAVES):
                src, dst = os.path.join(AUTOSAVES, name), os.path.join(dest, name)
                if name.endswith(".CivBeyondSwordSave") and time.time() - os.path.getmtime(src) > 5 and (
                        not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst)):
                    shutil.copy2(src, dst)
        except OSError:
            pass
        time.sleep(10)


def client(argv):
    """`civ` inside a sandbox: forward to the broker (called from civ when CIV_BROKER is set)."""
    tok = open(os.environ.get("CIV_TOKEN_FILE", TOKEN_NAME)).read().strip()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(os.environ["CIV_BROKER"])
    s.sendall(json.dumps({"token": tok, "argv": argv}).encode() + b"\n")
    data = b""
    while not data.endswith(b"\n"):
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    r = json.loads(data)
    sys.stdout.write(r["out"])
    sys.stderr.write(r["err"])
    return r["code"]


if __name__ == "__main__":
    serve(sys.argv[1])
