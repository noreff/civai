#!/usr/bin/env python3
"""Offline checks for the CIVAI tools (no game needed): python3 tests/test_tools.py

They use a saved map dump from the game's bridge folder; anything that needs the live game is left out."""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import mapview  # noqa: E402

BRIDGE = os.path.expanduser("~/Library/Application Support/CrossOver/Bottles/civ4/drive_c/claude_bridge")


def latest_state():
    files = sorted(glob.glob(os.path.join(BRIDGE, "state_T*.json")), key=os.path.getmtime)
    return json.load(open(files[-1])) if files else None


def test_unit_and_civ_names():
    assert mapview.unit_name("UNIT_MONGOL_KESHIK") == "Keshik"
    assert mapview.unit_name("UNIT_NATIVE_AMERICAN_DOG_SOLDIER") == "Dog Soldier"
    assert mapview.unit_name("UNIT_WAR_ELEPHANT") == "War Elephant"


def test_offset_words():
    assert mapview.offset_words((10, 10), (11, 11)) == "1 tile north-east"
    assert mapview.offset_words((10, 10), (10, 7)) == "3 tiles south"
    assert mapview.offset_words((10, 10), (12, 11)) == "2 east and 1 north"


def test_map_text_from_a_saved_dump():
    st = latest_state()
    if st is None:
        print("  (skipped: no saved map dump)")
        return
    text = mapview.brief(st)
    assert "### Places" in text and "MY CITIES" in text
    for xy in list(mapview.CITIES)[:3]:
        assert mapview.where(xy).startswith("the city of")
        card = mapview.battle_card(xy)
        assert "rating" in card or "never seen" in card or "can't stand" in card


def test_offer_arguments():
    # the same parsing civ uses: every item after --give/--get counts, commas split, spaces inside names stay
    argv = ["offer", "4", "--give", "peace", "--get", "peace", "gold:600", "tech:Code of Laws,map"]
    give, get, side = [], [], None
    for a in argv[2:]:
        if a in ("--give", "--get"):
            side = give if a == "--give" else get
        else:
            side.extend(x.strip() for x in a.split(",") if x.strip())
    assert give == ["peace"] and get == ["peace", "gold:600", "tech:Code of Laws", "map"]


def test_timeline_drops_abandoned_turns():
    import timeline
    rows = [{"turn": 395, "text": "a"}, {"turn": 397, "text": "ghost"}, {"turn": 408, "text": "ghost"},
            {"rewind_to": 396, "turn": 396}, {"turn": 396, "text": "b"}, {"turn": 408, "text": "c"}]
    assert [r["text"] for r in timeline.current(rows, timeline.chat_rewind)] == ["a", "b", "c"]
    rows = [{"kind": "war_declared", "turn": 400}, {"kind": "rewind", "to_turn": 396, "turn": 396}, {"kind": "x", "turn": 397}]
    assert [r["kind"] for r in timeline.current(rows, timeline.event_rewind, keep_markers=True)] == ["rewind", "x"]


def test_brief_skips_abandoned_wakes():
    import importlib.util, re, time
    spec = importlib.util.spec_from_file_location("loop", os.path.join(HERE, "loop.py"))
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    for w, t in loop.timeline.rewinds(loop.EVENTS):
        for line in loop.recent_wakes(500):
            m = re.match(r"- Wake-up \d+, turn (\d+) \(([\d-]+ [\d:]+)\)", line)
            assert not (m and int(m.group(1)) >= t and m.group(2) < w), "a wake-up of an abandoned timeline reached the brief"


def test_record_is_built_from_commands():
    import importlib.util
    spec = importlib.util.spec_from_file_location("loop", os.path.join(HERE, "loop.py"))
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    r = loop.summarize_commands(["status", "move 1 5 6", "move 2 5 6", "do 3 BOMBARD", "do 4 BOMBARD", "think x", "ready"])
    assert r == "said nothing; moved #1 #2 to 5,6; BOMBARD: #3 #4; civ ready", r
    assert loop.summarize_commands(["say Brother, hello"]).startswith('said "Brother, hello"')


def test_read_only_mode_lets_only_lookups_through():
    import importlib.machinery, importlib.util
    loader = importlib.machinery.SourceFileLoader("civcli", os.path.join(HERE, "civ"))
    spec = importlib.util.spec_from_loader("civcli", loader)
    civ = importlib.util.module_from_spec(spec)
    loader.exec_module(civ)
    for ok in (["status"], ["odds", "1", "2"], ["research"], ["build", "X", "Y", "--check"], ["hurry", "Turfan"], ["think", "x"]):
        assert civ.read_only(ok), ok
    for no in (["say", "hi"], ["research", "Drama"], ["move", "1", "2", "3"], ["ready"], ["hurry", "Turfan", "whip"], ["raw", "say"]):
        assert not civ.read_only(no), no


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
