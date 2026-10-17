#!/usr/bin/env python3
"""Render a ClaudeBridge state dump into a PNG map + a short text summary.

Usage: render_map.py [state.json] [out_dir]
Defaults: the latest dump in the civ4 CrossOver bottle -> out/ next to this script
"""
import json
import re
import os
import sys
from collections import defaultdict

from PIL import Image, ImageDraw, ImageFont

BRIDGE = os.path.expanduser(
    "~/Library/Application Support/CrossOver/Bottles/civ4/drive_c/claude_bridge")
OUT = os.path.join(os.path.dirname(os.path.realpath(__file__)), "out")

TILE = 18
MARGIN = 28
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

PEAK, HILLS, LAND, OCEAN = 0, 1, 2, 3

TERRAIN = {
    "TERRAIN_GRASS": (92, 145, 60),
    "TERRAIN_PLAINS": (170, 155, 80),
    "TERRAIN_DESERT": (225, 205, 140),
    "TERRAIN_TUNDRA": (140, 150, 135),
    "TERRAIN_SNOW": (235, 238, 240),
    "TERRAIN_COAST": (70, 135, 200),
    "TERRAIN_OCEAN": (35, 80, 150),
    "TERRAIN_PEAK": (110, 110, 110),
    "TERRAIN_HILL": (150, 130, 90),
}
FEATURE_MARK = {
    "FEATURE_FOREST": (40, 85, 35),
    "FEATURE_JUNGLE": (20, 70, 30),
    "FEATURE_ICE": (220, 235, 245),
    "FEATURE_OASIS": (60, 170, 160),
    "FEATURE_FLOOD_PLAINS": (150, 175, 90),
    "FEATURE_FALLOUT": (120, 160, 40),
}
UNKNOWN = (18, 18, 22)


def fog(c, visible):
    if visible:
        return c
    g = 120
    return tuple(int(v * 0.55 + g * 0.45) for v in c)


def load(path):
    with open(path) as f:
        text = f.read()
    # v1 dumps wrote plot types as bare enum names; map them back to numbers
    for i, name in enumerate(("PLOT_PEAK", "PLOT_HILLS", "PLOT_LAND", "PLOT_OCEAN")):
        text = re.sub(r"(?<=[,\[])%s(?=[,\]])" % name, str(i), text)
    return json.loads(text)


def short(t):
    if not t:
        return "-"
    for p in ("UNIT_", "TECH_", "LEADER_", "ERA_", "RELIGION_", "ATTITUDE_", "BONUS_", "IMPROVEMENT_"):
        if t.startswith(p):
            return t[len(p):].replace("_", " ").title()
    return t


def render(state, out_png, region=None):
    """Full map to out_png, plus *_zoom.png: region (x0, y0, x1, y1) or else the explored area."""
    W, H = state["map"]["width"], state["map"]["height"]
    me = state["me"]
    players = {p["id"]: p for p in state["players"]}
    font = ImageFont.truetype(FONT, 10)
    font_city = ImageFont.truetype(FONT_BOLD, 11)
    font_axis = ImageFont.truetype(FONT, 9)

    legend_h = 22 * ((len(players) + 2) // 3) + 30
    img = Image.new("RGB", (W * TILE + 2 * MARGIN, H * TILE + 2 * MARGIN + legend_h), (10, 10, 14))
    d = ImageDraw.Draw(img)

    def px(x, y):  # civ y=0 is the south edge; draw north up
        return MARGIN + x * TILE, MARGIN + (H - 1 - y) * TILE

    d.rectangle([MARGIN, MARGIN, MARGIN + W * TILE - 1, MARGIN + H * TILE - 1], fill=UNKNOWN)

    owner_at = {}
    for x, y, ptype, terrain, feature, bonus, owner, impr, route, river, vis in state["plots"]:
        X, Y = px(x, y)
        if ptype == PEAK:
            base = TERRAIN["TERRAIN_PEAK"]
        else:
            base = TERRAIN.get(terrain, (200, 0, 200))
        d.rectangle([X, Y, X + TILE - 1, Y + TILE - 1], fill=fog(base, vis))
        if ptype == HILLS:
            d.polygon([(X + 3, Y + TILE - 4), (X + TILE // 2, Y + 5), (X + TILE - 3, Y + TILE - 4)],
                      outline=fog((90, 70, 40), vis))
        elif ptype == PEAK:
            d.polygon([(X + 2, Y + TILE - 3), (X + TILE // 2, Y + 2), (X + TILE - 2, Y + TILE - 3)],
                      fill=fog((60, 60, 60), vis), outline=fog((235, 235, 235), vis))
        if feature in FEATURE_MARK:
            c = fog(FEATURE_MARK[feature], vis)
            for dx, dy in ((4, 4), (11, 6), (6, 12), (13, 13)):
                d.ellipse([X + dx - 2, Y + dy - 2, X + dx + 1, Y + dy + 1], fill=c)
        if river:
            d.line([X + 1, Y + TILE - 2, X + TILE - 2, Y + TILE - 2], fill=fog((120, 190, 255), vis))
        if bonus:
            d.rectangle([X + TILE - 6, Y + 1, X + TILE - 2, Y + 5], fill=fog((255, 215, 0), vis))
        if route:
            d.line([X + 2, Y + TILE // 2, X + TILE - 3, Y + TILE // 2], fill=fog((130, 90, 50), vis), width=2)
        if owner >= 0:
            owner_at[(x, y)] = owner

    # borders: draw an edge wherever the neighbour has a different owner
    for (x, y), o in owner_at.items():
        col = tuple(players[o]["color"]) if o in players else (255, 255, 255)
        X, Y = px(x, y)
        if owner_at.get((x, y + 1)) != o:
            d.line([X, Y, X + TILE - 1, Y], fill=col, width=2)
        if owner_at.get((x, y - 1)) != o:
            d.line([X, Y + TILE - 2, X + TILE - 1, Y + TILE - 2], fill=col, width=2)
        if owner_at.get((x - 1, y)) != o:
            d.line([X, Y, X, Y + TILE - 1], fill=col, width=2)
        if owner_at.get((x + 1, y)) != o:
            d.line([X + TILE - 2, Y, X + TILE - 2, Y + TILE - 1], fill=col, width=2)

    for c in state["cities"]:
        X, Y = px(c["x"], c["y"])
        o = c["owner"]
        col = tuple(players[o]["color"]) if o in players else (255, 255, 255)
        d.rectangle([X + 2, Y + 2, X + TILE - 3, Y + TILE - 3], fill=col, outline=(255, 255, 255), width=2)
        name = c["name"] + (" %d" % c["pop"] if "pop" in c else "")
        d.text((X + TILE // 2, Y - 1), name, font=font_city, fill=(255, 255, 255), anchor="mb",
               stroke_width=2, stroke_fill=(0, 0, 0))

    # units: one badge per owner per tile, number = military units (civilians in brackets)
    stacks = defaultdict(lambda: [0, 0])
    for x, y, owner, utype, count, military in state["units"]:
        stacks[(x, y, owner)][0 if military else 1] += count
    for (x, y, owner), (mil, civ) in stacks.items():
        X, Y = px(x, y)
        col = tuple(players[owner]["color"]) if owner in players else (255, 255, 255)
        r = 6
        cx, cy = X + 6, Y + TILE - 6
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col, outline=(0, 0, 0))
        label = str(mil) if mil else "c"
        tc = (0, 0, 0) if sum(col) > 380 else (255, 255, 255)
        d.text((cx, cy), label, font=font, fill=tc, anchor="mm")

    # coordinate axis every 5 tiles
    for x in range(0, W, 5):
        X, _ = px(x, 0)
        d.text((X + TILE // 2, MARGIN - 4), str(x), font=font_axis, fill=(170, 170, 170), anchor="mb")
        d.text((X + TILE // 2, MARGIN + H * TILE + 4), str(x), font=font_axis, fill=(170, 170, 170), anchor="mt")
    for y in range(0, H, 5):
        _, Y = px(0, y)
        d.text((MARGIN - 4, Y + TILE // 2), str(y), font=font_axis, fill=(170, 170, 170), anchor="rm")
        d.text((MARGIN + W * TILE + 4, Y + TILE // 2), str(y), font=font_axis, fill=(170, 170, 170), anchor="lm")

    # legend
    ly = MARGIN + H * TILE + 22
    d.text((MARGIN, ly), "Turn %d (%s) - map as seen by player %d. Grey = fog, black = unexplored. Badge = military units, c = civilians only."
           % (state["turn"], fmt_year(state["year"]), me), font=font, fill=(200, 200, 200))
    ly += 18
    col_w = (W * TILE) // 3
    for i, p in enumerate(sorted(players.values(), key=lambda p: p["id"])):
        lx = MARGIN + (i % 3) * col_w
        yy = ly + (i // 3) * 20
        d.rectangle([lx, yy, lx + 12, yy + 12], fill=tuple(p["color"]))
        if p.get("barbarian"):
            text = "Barbarians"
        elif p.get("met"):
            text = "%s (%s)%s" % (p.get("name", "?"), p.get("civ", "?"), "  <- CLAUDE" if p["id"] == me else "")
        else:
            text = "not met"
        d.text((lx + 18, yy), text, font=font, fill=(230, 230, 230))

    img.save(out_png)

    # zoomed copy: the requested region, or the explored part (early turns are mostly black)
    xs = [pl[0] for pl in state["plots"]]
    ys = [pl[1] for pl in state["plots"]]
    if region or xs:
        if region:
            x0, y0, x1, y1 = region
            x0, x1 = max(0, min(x0, x1)), min(W - 1, max(x0, x1))
            y0, y1 = max(0, min(y0, y1)), min(H - 1, max(y0, y1))
        else:
            pad = 3
            x0, x1 = max(0, min(xs) - pad), min(W - 1, max(xs) + pad)
            y0, y1 = max(0, min(ys) - pad), min(H - 1, max(ys) + pad)
        L, T = px(x0, y1)
        R, B = px(x1, y0)
        crop = img.crop((L - MARGIN, T - MARGIN, R + TILE + MARGIN, B + TILE + MARGIN))
        scale = max(1, min(4, 1400 // max(crop.size)))
        crop = crop.resize((crop.size[0] * scale, crop.size[1] * scale), Image.NEAREST)
        crop.save(out_png.replace(".png", "_zoom.png"))


def fmt_year(y):
    return "%d BC" % -y if y < 0 else "%d AD" % y


def summary(state):
    me = state["me"]
    players = {p["id"]: p for p in state["players"]}
    emp = state["my_empire"]
    mep = players[me]
    lines = [
        "# Turn %d, %s - %s of %s" % (state["turn"], fmt_year(state["year"]), mep.get("name"), mep.get("civ")),
        "",
        "Gold %d (%+d/turn). Researching %s (%s turns). Era %s. Religion %s." % (
            emp["gold"], emp["gold_per_turn"], short(emp["research"]), emp.get("research_turns", "?"),
            short(mep.get("era")), short(mep.get("state_religion"))),
        "",
        "## My cities",
    ]
    for c in emp["cities"]:
        lines.append("- %s (%d,%d) pop %d%s: building %s (%d t), grows in %d t, happy %d/%d, health %d/%d" % (
            c["name"], c["x"], c["y"], c["pop"], " CAPITAL" if c["capital"] else "",
            c["building"] or "nothing", c["build_turns"], c["food_turns"],
            c["happy"], c["unhappy"], c["health"], c["unhealth"]))
    lines += ["", "## Others"]
    for p in sorted(players.values(), key=lambda p: p["id"]):
        if p["id"] == me or not p.get("met"):
            continue
        if p.get("barbarian"):
            continue
        lines.append("- %s (%s)%s: score %s, era %s, attitude to me %s%s" % (
            p["name"], p["civ"], " [HUMAN]" if p.get("human") else "", p.get("score"),
            short(p.get("era")), short(p.get("their_attitude_to_me")),
            ", AT WAR" if p.get("at_war_with_me") else ""))
    unmet = sum(1 for p in players.values() if not p.get("met") and not p.get("barbarian"))
    lines.append("- not met yet: %d civs" % unmet)

    # foreign units I can see
    foreign = defaultdict(list)
    for x, y, owner, utype, count, military in state["units"]:
        if owner != me:
            foreign[owner].append("%dx %s at (%d,%d)" % (count, short(utype), x, y))
    if foreign:
        lines += ["", "## Foreign units in sight"]
        for o, lst in foreign.items():
            who = players.get(o, {}).get("name") or ("Barbarians" if players.get(o, {}).get("barbarian") else "player %d" % o)
            lines.append("- %s: %s" % (who, "; ".join(lst)))
    revealed = len(state["plots"])
    total = state["map"]["width"] * state["map"]["height"]
    lines += ["", "Map explored: %d of %d tiles (%d%%)." % (revealed, total, 100 * revealed // total)]
    return "\n".join(lines) + "\n"


def summary_short(state):
    revealed = len(state["plots"])
    total = state["map"]["width"] * state["map"]["height"]
    return "turn %d: %d of %d tiles explored, %d cities and %d unit stacks in sight" % (
        state["turn"], revealed, total, len(state["cities"]), len(state["units"]))


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BRIDGE, "state_latest.json")
    out = sys.argv[2] if len(sys.argv) > 2 else OUT
    os.makedirs(out, exist_ok=True)
    state = load(src)
    tag = "T%03d" % state["turn"]
    png = os.path.join(out, "map_%s.png" % tag)
    render(state, png)
    md = os.path.join(out, "summary_%s.md" % tag)
    with open(md, "w") as f:
        f.write(summary(state))
    print(png)
    print(md)


if __name__ == "__main__":
    main()
