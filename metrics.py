#!/usr/bin/env python3
"""The numbers of one game of several AI leaders, per seat, from its logs (read-only).

  metrics.py <game-id>            print the table; also writes games/<id>/metrics.json

Reads games/<id>/{seats.json, calls.jsonl, <seat>/wake_stats.jsonl, <seat>/said.jsonl, <seat>/thoughts.jsonl}
and the bridge's chat_all.jsonl, truth.jsonl and p<N>/events.jsonl (current timeline only).
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timeline  # noqa: E402

BRIDGE = os.path.expanduser("~/Library/Application Support/CrossOver/Bottles/%s/drive_c/claude_bridge"
                            % os.environ.get("CIV_BOTTLE", "civ4"))


def rows(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def per_seat(game, s, names, truth_last):
    d = os.path.join(HERE, "games", game, s["key"])
    stats = rows(os.path.join(d, "wake_stats.jsonl"))
    # marker rows (a refused audience skipped, a refused turn passed) are not wake-ups of their own
    wakes = [w for w in stats if not (w.get("skipped") or w.get("passed"))]
    ok = [w for w in wakes if not w.get("error")]
    usage = [w.get("usage") or {} for w in wakes]
    calls = [c for c in rows(os.path.join(HERE, "games", game, "calls.jsonl")) if c["seat"] == s["key"]]
    said = [m for m in rows(os.path.join(d, "said.jsonl")) if m.get("by", "agent") == "agent"]
    thoughts = rows(os.path.join(d, "thoughts.jsonl"))
    events = timeline.read(os.path.join(BRIDGE, "p%d" % s["player"], "events.jsonl"), timeline.event_rewind)
    agents = set(names.values()) - {names[s["player"]]}
    deals = [e for e in events if e.get("kind") == "deal_done"]
    me = truth_last.get(s["player"], {})
    return {
        "seat": s["key"], "model": s.get("model"), "harness": s.get("harness"),
        "leader": names.get(s["player"]),
        "wakes": len(wakes), "failed_wakes": len(wakes) - len(ok),
        "forced_ready": sum(1 for w in wakes if w.get("forced_ready")),
        "mean_seconds": round(sum(w.get("seconds", 0) for w in ok) / max(1, len(ok)), 1),
        "input_tokens": sum(u.get("input_tokens", 0) for u in usage),
        "output_tokens": sum(u.get("output_tokens", 0) for u in usage),
        "reasoning_tokens": sum(u.get("reasoning_output_tokens", 0) for u in usage),
        # claude: the self-check resumes the wake-up's session, and its total includes the wake-up's own cost;
        # pi: the self-check reports only its own cost
        "cost_usd": round(sum((max if s.get("harness") == "claude" else (lambda a, b: a + b))(
                                  w.get("total_cost_usd") or 0, (w.get("check") or {}).get("total_cost_usd") or 0)
                              for w in wakes), 2),
        "skipped_audiences": sum(1 for w in stats if w.get("skipped")),
        "passed_turns": sum(1 for w in stats if w.get("passed")),
        "tool_calls": len(calls),
        "tool_errors": sum(1 for c in calls if c.get("code") or c.get("error")),
        "messages": len(said),
        "messages_private": sum(1 for m in said if m.get("to") and m["to"] != "all"),
        "messages_to_agents": sum(1 for m in said if any(a in (m.get("read_by") or []) for a in agents)),
        "thoughts": len(thoughts),
        "deals": len(deals),
        "deals_with_agents": sum(1 for e in deals if e.get("with") in agents),
        "wars_declared": sum(1 for e in events if e.get("kind") == "war_declared" and e.get("team")
                             and names.get(s["player"], "").split(" (")[0] == e["team"]),
        "score": me.get("score"), "cities": me.get("cities"), "pop": me.get("pop"), "techs": me.get("techs"),
        "military": me.get("military"), "alive": me.get("alive"),
    }


def main(game):
    seats = json.load(open(os.path.join(HERE, "games", game, "seats.json")))["seats"]
    truth = rows(os.path.join(BRIDGE, "truth.jsonl"))
    last = truth[-1] if truth else {"civs": [], "turn": None}
    by_id = {c["id"]: c for c in last["civs"]}
    names = {s["player"]: "%s (%s)" % (by_id[s["player"]]["name"], by_id[s["player"]]["civ"])
             for s in seats if s["player"] in by_id}
    table = [per_seat(game, s, names, by_id) for s in seats]
    controls = [{"leader": "%s (%s)" % (c["name"], c["civ"]), "score": c["score"], "cities": c["cities"], "pop": c["pop"],
                 "techs": c["techs"], "military": c["military"], "alive": c["alive"]}
                for c in last["civs"] if not c["agent"] and not c["human"]]
    out = {"game": game, "turn": last.get("turn"), "seats": table, "controls": controls}
    json.dump(out, open(os.path.join(HERE, "games", game, "metrics.json"), "w"), indent=1)

    print("game %s, turn %s\n" % (game, last.get("turn")))
    keys = ["leader", "wakes", "failed_wakes", "mean_seconds", "cost_usd", "tool_calls", "tool_errors", "messages",
            "messages_to_agents", "messages_private", "thoughts", "deals", "deals_with_agents", "score", "cities",
            "pop", "techs", "military"]
    print("%-20s" % "" + "".join("%-22s" % ("%s (%s)" % (r["seat"], r["harness"]))[:22] for r in table))
    for k in keys:
        print("%-20s" % k + "".join("%-22s" % str(r[k])[:21] for r in table))
    print("\nbuilt-in AI (controls):")
    for c in controls:
        print("  %-26s score %-5s cities %-3s pop %-3s techs %-3s military %s" % (
            c["leader"], c["score"], c["cities"], c["pop"], c["techs"], c["military"]))


if __name__ == "__main__":
    main(sys.argv[1])
