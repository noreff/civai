#!/usr/bin/env python3
"""Offline checks for replay.py (no game needed): python3 tests/test_replay.py

A small made-up game: two seats, turns 10-12, a save reloaded in the middle of turn 11. The game's clock
runs an hour ahead of the Mac's, as it does under Wine."""
import io
import json
import os
import shutil
import sys
import tempfile
import time
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import replay  # noqa: E402

DAY = "2026-10-17"
WINE = 3600   # the game's clock minus the Mac's


def mac(hms):
    return time.mktime(time.strptime(DAY + " " + hms, "%Y-%m-%d %H:%M:%S"))


def wine(hms, date=True):
    t = time.localtime(mac(hms) + WINE)
    return time.strftime("%Y-%m-%d %H:%M:%S" if date else "%H:%M:%S", t)


def write_rows(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def cmd(hms, text, by="agent"):
    return {"cmd": text, "wall": DAY + " " + hms, "by": by}


def civ_row(i, score):
    return {"id": i, "name": "Leader%d" % i, "alive": True, "score": score, "cities": 1, "pop": 2, "units": 3,
            "military": 1, "gold": 10, "techs": 4, "era": "ERA_ANCIENT", "religion": -1, "war": [], "met": []}


def make_game():
    root = tempfile.mkdtemp(prefix="replay-test-")
    games, bridge = os.path.join(root, "games"), os.path.join(root, "bridge")
    g = os.path.join(games, "g1")
    os.makedirs(os.path.join(g, "saves"))
    json.dump({"seats": [{"key": "a", "player": 1}, {"key": "b", "player": 2}]}, open(os.path.join(g, "seats.json"), "w"))
    write_rows(os.path.join(g, "a", "commands.jsonl"), [
        cmd("10:00:10", "move 1 5 6"),
        cmd("10:00:12", "status"),                       # a lookup
        cmd("10:00:15", "ready"),
        cmd("10:00:30", "do 1 FORTIFY"),                 # turn 11, in a wake-up still named T010
        cmd("10:00:50", "say --to Joao II Hello there friend"),
        cmd("10:00:55", "move 2 18,21"),                 # failed in the game
        cmd("10:00:58", "answer 3 yes"),                 # a proposal made in turn 10
        cmd("10:01:00", "ready"),
        cmd("10:01:30", "move 3 1 1"),                   # turn 12, still going on
    ])
    write_rows(os.path.join(g, "b", "commands.jsonl"), [
        cmd("10:00:10", "research Bronze Working"),
        cmd("10:00:20", "ready"),                        # the same second turn 11 began: still turn 10
        cmd("10:00:35", "offer Joao II --give tech:Code of Laws --get gold:10"),   # thrown away by the reload
        cmd("10:00:50", "raw units"),                    # not a bridge order
        cmd("10:00:51", "gate auto on"),
        cmd("10:01:05", "ready"),
    ])
    write_rows(os.path.join(g, "a", "said.jsonl"), [
        {"text": "Hello there friend", "to": "Joao II (Portugal)", "wall": DAY + " 10:00:51", "by": "agent"}])
    write_rows(os.path.join(g, "a", "wake_stats.jsonl"), [
        {"turn": 10, "file": "T010-100040.md", "wall": DAY + " 10:00:40", "seconds": 32.0}])
    write_rows(os.path.join(g, "calls.jsonl"), [
        {"wall": DAY + " 10:00:55", "seat": "a", "argv": "move 2 18,21", "code": 1, "error": "ERROR: traceback",
         "seconds": 0.1},
        {"wall": DAY + " 10:00:58", "seat": "a", "argv": "answer 3 yes", "code": 0, "error": None, "seconds": 0.1}])
    saves = [("AutoSave_BC-0400.CivBeyondSwordSave", "10:00:00"), ("AutoSave_BC-0360.CivBeyondSwordSave", "10:00:20"),
             ("T012_AutoSave_BC-0320.CivBeyondSwordSave", "10:01:05"),
             ("AutoSave_BC-0280.CivBeyondSwordSave", "10:00:39")]   # turn 13 of the timeline the reload threw away
    for name, hms in saves:
        path = os.path.join(g, "saves", name)
        open(path, "w").write("save")
        os.utime(path, (mac(hms), mac(hms)))

    write_rows(os.path.join(bridge, "truth.jsonl"), [
        {"turn": 10, "time": wine("10:00:00"), "civs": [civ_row(1, 50), civ_row(2, 40)]},
        {"turn": 11, "time": wine("10:00:20"), "civs": [civ_row(1, 51), civ_row(2, 41)]},
        {"turn": 12, "time": wine("10:01:05"), "civs": [civ_row(1, 55), civ_row(2, 41)]}])
    events = [
        {"kind": "claude_wake", "reasons": ["turn"], "turn": 10, "year": -400, "time": wine("10:00:00", False)},
        {"kind": "proposal", "id": 3, "text": "Leader4 offers a deal", "turn": 10, "year": -400,
         "time": wine("10:00:19", False)},
        {"kind": "claude_wake", "reasons": ["turn"], "turn": 11, "year": -360, "time": wine("10:00:20", False)},
        {"kind": "unit_built", "turn": 13, "year": -280, "time": wine("10:00:38", False)},
        {"kind": "claude_wake", "reasons": ["turn"], "turn": 11, "year": -360, "time": wine("10:00:40", False)},
        {"kind": "claude_wake", "reasons": ["turn"], "turn": 12, "year": -320, "time": wine("10:01:05", False)}]
    write_rows(os.path.join(bridge, "p1", "events.jsonl"), events)
    log = os.path.join(bridge, "bridge.log")
    with open(log, "w") as f:
        f.write("%s dump ok: begin_turn turn=10 player=1\n" % wine("10:00:01"))
        f.write("%s dump ok: load_game turn=11 player=1 plots=1\n" % wine("10:00:40"))
        f.write("%s hot-reloaded bridge v80\n" % wine("10:00:45"))
        f.write("%s heartbeat: Update=1\n" % wine("10:02:00"))
    os.utime(log, (mac("10:02:00"), mac("10:02:00")))
    with open(os.path.join(bridge, "exec.log"), "w") as f:
        f.write("---- %s turn 11\ng = CyGame()\ng.toggleDebugMode()\nresult = 1\n" % wine("10:00:46"))
        f.write("---- %s turn 11\nresult = CyGame().getGameTurn()\n" % wine("10:00:47"))
    return root, replay.Game("g1", bridge, games)


def texts(orders):
    return [(o.seat, o.text) for o in orders]


def test_lookups_are_not_orders():
    for no in (["status"], ["research"], ["build", "Rome", "Archer", "--check"], ["say", "--help"], ["think", "x"],
               ["raw", "units"], ["raw", "gate"], ["raw", "notice", "{}"], ["war", "Rome", "--check"], ["hurry", "Rome"]):
        assert not replay.is_order(no), no
    for yes in (["move", "1", "2", "3"], ["ready"], ["research", "Bronze"], ["gate", "auto", "on"],
                ["raw", "gate", '{"on":', "true}"], ["raw", "ready"], ["hurry", "Rome", "whip"], ["say", "hi"]):
        assert replay.is_order(yes), yes


def test_argv_comes_back_from_the_joined_log_line():
    assert replay.split_argv("offer Joao II --give tech:Code of Laws,map --get gold:10") == [
        "offer", "Joao II", "--give", "tech:Code of Laws,map", "--get", "gold:10"]
    assert replay.split_argv("give Joao II tech:Bronze Working") == ["give", "Joao II", "tech:Bronze Working"]
    assert replay.split_argv("war Joao II --check") == ["war", "Joao II", "--check"]
    assert replay.split_argv("move 5 18,21") == ["move", "5", "18", "21"]
    said = {"text": "Hello there friend", "to": "Joao II (Portugal)"}
    assert replay.say_argv("say --to Joao II Hello there friend", said) == ["say", "--to", "Joao II", "Hello there friend"]


def test_clock_offset_from_bridge_log():
    root, g = make_game()
    try:
        assert g.offset == WINE, g.offset
    finally:
        shutil.rmtree(root)


def test_turns_come_from_the_game_clock():
    root, g = make_game()
    try:
        assert texts(g.by_turn[10]) == [("a", "move 1 5 6"), ("b", "research Bronze Working"), ("a", "ready"),
                                        ("b", "ready")], texts(g.by_turn[10])
        # the wake-up file says T010, the game was in turn 11 (and the order was thrown away by the reload)
        assert ("a", "do 1 FORTIFY") in texts(g.abandoned[11])
        assert ("b", "offer Joao II --give tech:Code of Laws --get gold:10") in texts(g.abandoned[11])
        assert texts(g.by_turn[11]) == [("a", "say --to Joao II Hello there friend"), ("b", "gate auto on"),
                                        ("a", "move 2 18,21"), ("a", "answer 3 yes"), ("a", "ready"),
                                        ("b", "ready")], texts(g.by_turn[11])
        assert texts(g.by_turn[12]) == [("a", "move 3 1 1")]
        w = g.window(11)
        assert w.how == "load" and w.start == mac("10:00:40") and w.end == mac("10:01:05")
        assert g.window(10).next_truth["turn"] == 11 and g.window(11).next_truth["turn"] == 12
    finally:
        shutil.rmtree(root)


def test_saves_by_year_and_timeline():
    root, g = make_game()
    try:
        assert os.path.basename(g.saves[10]["path"]) == "AutoSave_BC-0400.CivBeyondSwordSave"
        assert os.path.basename(g.saves[12]["path"]).startswith("T012_")
        assert not g.saves[11]["stale"]
        assert g.saves[13]["stale"]   # written before the reload went back to turn 11
    finally:
        shutil.rmtree(root)


def test_calls_said_and_wakes_are_attached():
    root, g = make_game()
    try:
        o = dict(((o.seat, o.text), o) for o in g.by_turn[11])
        assert o[("a", "move 2 18,21")].code == 1
        assert o[("a", "answer 3 yes")].code == 0
        assert o[("a", "say --to Joao II Hello there friend")].argv == ["say", "--to", "Joao II", "Hello there friend"]
        assert [x.wake for x in g.abandoned[11] if x.seat == "a"] == ["T010-100040.md"]
        steps = replay.replay_steps(g, 11)
        assert [why is not None for _, why in steps] == [False, False, True, False, False, False]
    finally:
        shutil.rmtree(root)


def test_turn_notes():
    root, g = make_game()
    try:
        notes = replay.turn_notes(g, 11)
        assert "save reloaded mid-turn" in notes
        assert "2 orders thrown away by a reload" in notes
        assert "director ran Python" in notes            # the toggle; the bare `result =` read doesn't count
        assert len(g.director) == 1
        assert "bridge v80 mid-turn" in notes
        assert "1 answers to proposals made before the save" in notes
        assert replay.replayable(notes)
        assert not replay.replayable(replay.turn_notes(g, 12))   # not over yet
        assert replay.turn_notes(g, 10) == ["1 same-second orders of different seats"], replay.turn_notes(g, 10)
    finally:
        shutil.rmtree(root)


def test_index_and_plan_print():
    root, g = make_game()
    try:
        out = io.StringIO()
        with redirect_stdout(out):
            replay.cmd_index(g)
            replay.cmd_plan(g, 11)
            replay.cmd_run(g, 11, True, 2.0, False)
        text = out.getvalue()
        assert "replayable (a save, the turn over, a record of the next turn to compare): 10-11" in text, text
        assert 'civ say --to "Joao II" "Hello there friend"' in text
        assert "thrown away by a reload, NOT replayed" in text
        assert "SKIPPED: failed then: ERROR: traceback" in text
        assert "DRY RUN" in text and "QuickSave.CivBeyondSwordSave" in text
    finally:
        shutil.rmtree(root)


def test_run_with_a_pretend_game():
    # the real run's steps against a pretend game: the "load" writes the bridge.log line, the last ready
    # writes the record of the next turn; nothing reaches the real game (QUICKSAVE, quick_load, send replaced)
    root, g = make_game()
    saved = (replay.QUICKSAVE, replay.quick_load, replay.send)
    sent = []

    def fake_load():
        with open(os.path.join(g.bridge, "bridge.log"), "a") as f:
            f.write("%s dump ok: load_game turn=11 player=1\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        write_rows(os.path.join(g.bridge, "p1", "events.jsonl"), [{"kind": "rewind", "to_turn": 11}])  # the load's marker

    def fake_send(game, order, log_dir, argv):
        sent.append((order.seat, argv))
        if argv == ["ready"] and order.seat == "b":
            with open(os.path.join(g.bridge, "truth.jsonl"), "a") as f:
                f.write(json.dumps({"turn": 12, "time": "x", "civs": [civ_row(1, 55), civ_row(2, 42)]}) + "\n")
        return 0, "ok"
    try:
        replay.QUICKSAVE = os.path.join(root, "quick", "QuickSave.CivBeyondSwordSave")
        replay.quick_load, replay.send = fake_load, fake_send
        events_before = open(os.path.join(g.bridge, "p1", "events.jsonl")).read()
        out = io.StringIO()
        with redirect_stdout(out):
            assert replay.cmd_run(g, 11, False, 0, False) == 0
        text = out.getvalue()
        assert open(replay.QUICKSAVE).read() == "save"
        assert sent == [("a", ["say", "--to", "Joao II", "Hello there friend"]), ("b", ["gate", "auto", "on"]),
                        ("a", ["answer", "3", "yes"]), ("a", ["ready"]), ("b", ["ready"])], sent
        assert "with 1 differences in the record of turn 12" in text and "Leader2: score 41 -> 42" in text, text
        # the game's own records are back as they were; the replay's are kept apart
        assert open(os.path.join(g.bridge, "p1", "events.jsonl")).read() == events_before
        assert "rewind" in open(os.path.join(g.dir, "replays", "T011", "bridge-after", "p1", "events.jsonl")).read()
    finally:
        replay.QUICKSAVE, replay.quick_load, replay.send = saved
        shutil.rmtree(root)


def test_compare_records():
    a = {"civs": [civ_row(1, 50), civ_row(2, 40)]}
    b = {"civs": [civ_row(1, 50), dict(civ_row(2, 40), gold=12)]}
    assert replay.compare(a, a) == []
    assert replay.compare(a, b) == ["Leader2: gold 10 -> 12"]


def test_compact_turns():
    assert replay.compact([54, 55, 56, 60, 62, 63]) == "54-56, 60, 62-63"


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except AssertionError as e:
                failed += 1
                print("FAIL", name, e)
    sys.exit(1 if failed else 0)
