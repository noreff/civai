#!/usr/bin/env python3
"""How the playing agent sees the map: words with coordinates, and pictures.

Everything comes from the agent's own fog-of-war view (`civ raw map`). Designed and tested
against other formats (see the map-concepts page): place descriptions never need column
counting, and every fact carries its own coordinates.

  mapview.py brief            the "Map" section of a wake-up brief (also saves the pictures)
  mapview.py around X Y       one place and its 8 neighbours (`civ around`)
  mapview.py where X Y [X Y..]   a place in words for someone without coordinates (`civ where`)
  mapview.py card <city>      battle card for attacking a city (`civ card`)
  mapview.py pictures [DIR]   overview + close-ups of the hot spots as PNG
Add --state FILE to read a saved map dump instead of the live game.
"""
import json
import math
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

TERRAIN = {"TERRAIN_GRASS": "grass", "TERRAIN_PLAINS": "plains", "TERRAIN_DESERT": "desert",
           "TERRAIN_TUNDRA": "tundra", "TERRAIN_SNOW": "snow", "TERRAIN_COAST": "coast",
           "TERRAIN_OCEAN": "ocean", "TERRAIN_PEAK": "peak"}
FEAT = {"FEATURE_FOREST": "forest", "FEATURE_JUNGLE": "jungle", "FEATURE_FLOOD_PLAINS": "flood plains",
        "FEATURE_OASIS": "oasis", "FEATURE_ICE": "ice"}
DIRS = [("N", 0, 1), ("NE", 1, 1), ("E", 1, 0), ("SE", 1, -1), ("S", 0, -1), ("SW", -1, -1), ("W", -1, 0), ("NW", -1, 1)]
CIVILIAN = ("WORKER", "BOAT", "EXPLORER", "SETTLER", "PROPHET", "MISSIONARY", "SCOUT", "GREAT", "ARTIST",
            "ENGINEER", "MERCHANT", "SCIENTIST", "SPY", "EXECUTIVE")

ME, PLAYERS, PLOTS, CITIES, UNITS, D = None, {}, {}, {}, {}, {}


def load(d):
    global ME, PLAYERS, PLOTS, CITIES, UNITS, D
    D = d
    ME = d["me"]
    PLAYERS = {p["id"]: p for p in d["players"]}
    PLOTS = {(p[0], p[1]): p for p in d["plots"]}
    CITIES = {(c["x"], c["y"]): c for c in d["cities"]}
    UNITS = {}
    for u in d["units"]:
        UNITS.setdefault((u[0], u[1]), []).append(u)


def live_state():
    out = subprocess.run([os.path.join(HERE, "civ"), "raw", "map"], capture_output=True, text=True, timeout=180).stdout
    return json.loads(out)


# ---------------------------------------------------------------- words
def nice(s, prefix):
    return s.replace(prefix, "").replace("_", " ").lower() if s else None


def unit_name(t):
    return nice(t, "UNIT_").replace("mongol ", "").replace("indian ", "").title()


def at_war(o):
    return PLAYERS.get(o, {}).get("at_war_with_me")


def owner_name(o, short=False):
    if o is None or o < 0:
        return "no one"
    if o == ME:
        return "us" if short else "ours (Mongol)"
    p = PLAYERS.get(o)
    if not p:
        return "?"
    civ = {"Vikings": "Viking", "Zululand": "Zulu", "Ottomans": "Ottoman", "Barbarians": "Barbarian"}.get(p["civ"], p["civ"])
    if short:
        return civ
    return civ + (", AT WAR" if at_war(o) else "")


def ground(p):
    """'HILL grass, river, mine' / 'flat plains, road' / 'coast'."""
    pt, ter, feat, imp, route, river = p[2], p[3], p[4], p[7], p[8], p[9]
    t = TERRAIN.get(ter, nice(ter, "TERRAIN_"))
    if pt == 3:
        return t
    if pt == 0:
        return "PEAK (impassable)"
    parts = [("HILL " if pt == 1 else "flat ") + t]
    if feat:
        parts.append(FEAT.get(feat, nice(feat, "FEATURE_")))
    if river:
        parts.append("river")
    if imp:
        parts.append(nice(imp, "IMPROVEMENT_"))
    if route:
        parts.append("road")
    return ", ".join(parts)


def land(p):
    if p[6] == ME:
        return "our land"
    return owner_name(p[6], short=True) + " land" if p[6] >= 0 else "unowned"


def units_at(xy):
    us = UNITS.get(xy, [])
    by = {}
    for u in us:
        by.setdefault(u[2], []).append("%s%s" % (unit_name(u[3]), " x%d" % u[4] if u[4] > 1 else ""))
    return "; ".join("%s: %s" % (owner_name(o, short=True), ", ".join(v)) for o, v in by.items())


def contents(xy):
    p = PLOTS[xy]
    out = []
    if xy in CITIES:
        c = CITIES[xy]
        out.append("CITY %s (%s%s)" % (c["name"], owner_name(c["owner"], short=True), " pop %d" % c["pop"] if c.get("pop") else ""))
    if p[5]:
        out.append(nice(p[5], "BONUS_").capitalize())
    u = units_at(xy)
    if u:
        out.append("units " + u)
    if not p[10]:
        out.append("fog, last seen")
    return out


def dist(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def dirword(dx, dy):
    ang = math.degrees(math.atan2(dy, dx))
    names = ["E", "ENE", "NE", "NNE", "N", "NNW", "NW", "WNW", "W", "WSW", "SW", "SSW", "S", "SSE", "SE", "ESE"]
    return names[int(((ang + 360) % 360 + 11.25) // 22.5) % 16]


def straight_path(a, b):
    x, y = a
    out = []
    while (x, y) != b:
        x += (b[0] > x) - (b[0] < x)
        y += (b[1] > y) - (b[1] < y)
        out.append((x, y))
    return out


WIND = {(0, 1): "north", (1, 1): "north-east", (1, 0): "east", (1, -1): "south-east",
        (0, -1): "south", (-1, -1): "south-west", (-1, 0): "west", (-1, 1): "north-west"}


def offset_words(src, xy):
    """How a person counts from src to xy on screen: '2 tiles south-west' / '3 east and 1 north'."""
    dx, dy = xy[0] - src[0], xy[1] - src[1]
    if dx == 0 or dy == 0 or abs(dx) == abs(dy):
        n = max(abs(dx), abs(dy))
        return "%d tile%s %s" % (n, "" if n == 1 else "s", WIND[((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))])
    return "%d %s and %d %s" % (abs(dx), "east" if dx > 0 else "west", abs(dy), "north" if dy > 0 else "south")


def where(xy):
    """A place in the words of someone who sees the map but no coordinates: counted from the nearest cities."""
    if xy in CITIES:
        c = CITIES[xy]
        return "the city of %s (%s)" % (c["name"], owner_name(c["owner"], short=True))
    refs = sorted(CITIES, key=lambda c: (dist(c, xy), c))[:2]
    if not refs:
        return None
    rel = ["%s of %s" % (offset_words(c, xy), CITIES[c]["name"]) for c in refs if dist(c, xy) <= 10]
    p = PLOTS.get(xy)
    what = ground(p).replace("HILL ", "hill, ").replace("flat ", "") if p else "a tile we never saw"
    if p and p[5]:
        what += ", " + nice(p[5], "BONUS_")
    u = units_at(xy)
    return "the %s tile %s%s" % (what, " = ".join(rel) or "far from any city we know", "; units there: " + u if u else "")


def around(xy, title=None):
    """One place and its 8 neighbours by compass direction."""
    x, y = xy
    p = PLOTS.get(xy)
    if not p:
        return "%d,%d: never seen" % xy
    if title is None:
        title = "Tile"
        if xy in CITIES:
            title = "%s (%s city)" % (CITIES[xy]["name"], owner_name(CITIES[xy]["owner"]))
    head = "%s at %d,%d: %s; %s" % (title, x, y, ground(p), land(p))
    extra = [c for c in contents(xy) if not c.startswith("CITY")]
    if extra:
        head += " [" + "; ".join(extra) + "]"
    L = [head]
    if xy not in CITIES:
        L.append("  (to other leaders: %s)" % where(xy))
    for name, dx, dy in DIRS:
        n = (x + dx, y + dy)
        q = PLOTS.get(n)
        if not q:
            L.append("  %-2s %d,%d: never seen" % (name, n[0], n[1]))
            continue
        c = contents(n)
        L.append("  %-2s %d,%d: %s; %s%s" % (name, n[0], n[1], ground(q), land(q), " [" + "; ".join(c) + "]" if c else ""))
    return "\n".join(L)


def my_cities():
    return [xy for xy, c in CITIES.items() if c["owner"] == ME]


def nearest_own_city(xy):
    mine = my_cities()
    return min(mine, key=lambda c: dist(c, xy)) if mine else None


def battle_card(target):
    p = PLOTS[target]
    c = CITIES[target]
    L = ["TARGET: %s %d,%d, %s city" % (c["name"], target[0], target[1], owner_name(c["owner"]))]
    L.append("  ground under the city: %s -> %s" % (ground(p), "defenders get the HILL bonus" if p[2] == 1 else "NO hill bonus for defenders"))
    L.append("  seen right now: %s" % ("yes" if p[10] else "no, fog (what follows may be stale)"))
    L.append("  defenders seen inside: %s" % (units_at(target) or "none seen"))
    L.append("THE 8 TILES AROUND IT, best to worst to attack from (HILL +25%, forest/jungle +50% for whoever stands there):")
    rows = []
    for name, dx, dy in DIRS:
        n = (target[0] + dx, target[1] + dy)
        q = PLOTS.get(n)
        if not q:
            rows.append((-50, name, n, None))
            continue
        score = -99 if q[2] in (0, 3) else (2 if q[2] == 1 else 0) + (1 if q[4] in ("FEATURE_FOREST", "FEATURE_JUNGLE") else 0)
        rows.append((score, name, n, q))
    rows.sort(key=lambda r: -r[0])
    for score, name, n, q in rows:
        if q is None:
            L.append("  %-2s %d,%d: never seen" % (name, n[0], n[1]))
        elif score == -99:
            L.append("  %-2s %d,%d: %s (can't stand here)" % (name, n[0], n[1], ground(q)))
        else:
            c2 = [z for z in contents(n) if not z.startswith("CITY")]
            L.append("  %-2s %d,%d: %s; %s%s" % (name, n[0], n[1], ground(q), land(q), "  [" + "; ".join(c2) + "]" if c2 else ""))
    src = nearest_own_city(target)
    if src:
        path = straight_path(src, target)
        dx, dy = target[0] - src[0], target[1] - src[1]
        L.append("APPROACH from %s %d,%d: %d tiles %s. Straight walk: %s" % (
            CITIES[src]["name"], src[0], src[1], dist(src, target), dirword(dx, dy),
            " -> ".join("%d,%d %s" % (t[0], t[1], ground(PLOTS[t]).split(",")[0]) if t in PLOTS else "%d,%d never seen" % t for t in path[:-1]) or "adjacent"))
    near = ["%d,%d %s" % (xy[0], xy[1], units_at(xy)) for xy, us in UNITS.items()
            if xy != target and dist(xy, target) <= 4 and any(u[2] != ME for u in us)]
    L.append("OTHER FOREIGN UNITS within 4 tiles: %s" % ("; ".join(near) if near else "none seen"))
    return "\n".join(L)


def military(us, owner):
    return [u for u in us if u[2] == owner and not any(w in u[3] for w in CIVILIAN)]


def hot_spots():
    """Places that matter this turn: enemy cities at war, foreign armies near our land, our armies in the field."""
    spots = []
    mine_land = {xy for xy, p in PLOTS.items() if p[6] == ME}
    cities = set(my_cities())
    field = [xy for xy, us in UNITS.items() if xy not in cities and military(us, ME)
             and (sum(u[4] for u in military(us, ME)) >= 2 or any(w in u[3] for u in military(us, ME) for w in ("CATAPULT", "KESHIK", "TREBUCHET")))]
    for xy, c in CITIES.items():
        if c["owner"] != ME and at_war(c["owner"]) and (not cities or min(dist(xy, m) for m in cities) <= 12):
            spots.append((xy, "enemy city"))
    for xy, us in UNITS.items():
        foreign = [u for o in {u[2] for u in us if u[2] != ME} for u in military(us, o)]
        if foreign and xy not in CITIES and any((xy[0] + dx, xy[1] + dy) in mine_land for dx in range(-2, 3) for dy in range(-2, 3)):
            spots.append((xy, ("ENEMY" if any(at_war(u[2]) for u in foreign) else "foreign") + " units near our land"))
    for xy in field:
        spots.append((xy, "our army in the field"))
    return spots


def crops_for(spots, limit=3):
    crops = []
    for xy, why in spots:
        for c in crops:
            pts = c["pts"] + [xy]
            if max(p[0] for p in pts) - min(p[0] for p in pts) <= 10 and max(p[1] for p in pts) - min(p[1] for p in pts) <= 10:
                c["pts"] = pts
                c["why"].append(why)
                break
        else:
            crops.append({"pts": [xy], "why": [why]})
    for c in crops:
        xs = [p[0] for p in c["pts"]]
        ys = [p[1] for p in c["pts"]]
        cx, cy = (min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2
        c["box"] = (cx - 5, cx + 5, cy - 5, cy + 5)
    return crops[:limit]


def places_and_routes():
    mine = my_cities()
    L = ["MY CITIES (ground under each)"]
    for xy in sorted(mine, key=lambda t: (-t[1], t[0])):
        L.append("  %s %d,%d on %s" % (CITIES[xy]["name"], xy[0], xy[1], ground(PLOTS[xy])))
    near = [xy for xy, c in CITIES.items() if c["owner"] != ME and mine and min(dist(xy, m) for m in mine) <= 8]
    if near:
        L.append("FOREIGN CITIES within 8 tiles of mine (distance and direction from my nearest city)")
        for xy in sorted(near, key=lambda t: (-t[1], t[0])):
            src = nearest_own_city(xy)
            dx, dy = xy[0] - src[0], xy[1] - src[1]
            path = straight_path(src, xy)[:-1]
            road = sum(1 for t in path if t in PLOTS and PLOTS[t][8])
            L.append("  %s %d,%d (%s) on %s: %d tiles %s of %s; road on %d of the %d tiles between%s" % (
                CITIES[xy]["name"], xy[0], xy[1], owner_name(CITIES[xy]["owner"]), ground(PLOTS[xy]), dist(src, xy),
                dirword(dx, dy), CITIES[src]["name"], road, len(path), "" if PLOTS[xy][10] else "; fog, last seen"))
    return "\n".join(L)


def brief(state, pic_dir=None):
    load(state)
    spots = hot_spots()
    L = ["Every fact has its coordinates. x grows EAST, y grows NORTH: south of x,y is x,y-1. "
         "Other leaders' screens show no coordinates: name places to them as `civ where X Y` words them. "
         "HILL = +25% defence for whoever stands there; forest/jungle +50%. Ask for more: `civ around X Y`, `civ card <city>`, `civ tile X Y`.",
         "", "### Places", "", places_and_routes()]
    if spots:
        L += ["", "### Around every place that matters this turn", ""]
        seen = set()
        for xy, why in spots:
            if xy in seen:
                continue
            seen.add(xy)
            L += [around(xy, None if xy in CITIES else why.capitalize()), ""]
        targets = sorted([xy for xy, why in spots if why == "enemy city"],
                         key=lambda t: min(dist(t, m) for m in my_cities()) if my_cities() else 0)
        targets = targets[:1] + [t for t in targets[1:2] if min(dist(t, m) for m in my_cities()) <= 6]
        for t in targets:
            L += ["### Battle card: %s" % CITIES[t]["name"], "", battle_card(t), ""]
    else:
        L += ["", "No hot spots this turn: no enemy city at war near us, no foreign army by our land, no army of ours in the field."]
    if pic_dir:
        files = pictures(state, pic_dir, spots)
        if files:
            L += ["", "### Pictures (open with your Read tool when you want the lay of the land)", ""]
            L += ["- %s: %s" % (f, why) for f, why in files]
            L += ["Legend: coloured outlines = borders (brown = us, purple = Viking, magenta = India, yellow = Zulu, green = Ottoman); "
                  "squares = cities; circles with a number = unit stacks (colour = owner); a dark triangle marked HILL = hill; "
                  "trees = forest, dark dots = jungle, blue wave = river, brown line = road; washed-out = fog. "
                  "In close-ups every tile shows its x,y in the top-left corner."]
    return "\n".join(L).rstrip()


# ---------------------------------------------------------------- pictures
COLORS = {"grass": "#8fc06c", "plains": "#d2bb74", "desert": "#eadbab", "tundra": "#b8b5a6", "snow": "#f1f1ee",
          "coast": "#a9d0e6", "ocean": "#6f9fd0", "peak": "#8a8a8a"}
OWNER_COL = {1: "#7a4a00", 4: "#6d4bd6", 0: "#b03fc9", 2: "#b8a400", 3: "#1f7a2a", 18: "#222"}


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;")


def owner_col(o):
    return OWNER_COL.get(o, "#000")


def svg_closeup(box, S=56):
    x0, x1, y0, y1 = box
    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    ML, MT = 30, 22
    W, H = ML + nx * S + 8, MT + ny * S + 8
    o = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" font-family="Menlo, monospace">' % (W, H, W, H),
         '<rect width="%d" height="%d" fill="#f6f4ee"/>' % (W, H)]
    for i in range(nx):
        o.append('<text x="%d" y="15" font-size="11" text-anchor="middle" fill="#333">%d</text>' % (ML + i * S + S / 2, x0 + i))
    for j in range(ny):
        o.append('<text x="%d" y="%d" font-size="11" text-anchor="end" fill="#333">%d</text>' % (ML - 6, MT + j * S + S / 2 + 4, y1 - j))
    labels = []
    for j in range(ny):
        y = y1 - j
        for i in range(nx):
            x = x0 + i
            px, py = ML + i * S, MT + j * S
            p = PLOTS.get((x, y))
            if not p:
                o.append('<rect x="%d" y="%d" width="%d" height="%d" fill="#ddd"/>' % (px, py, S, S))
                continue
            o.append('<rect x="%d" y="%d" width="%d" height="%d" fill="%s" stroke="#fff"/>' % (px, py, S, S, COLORS.get(TERRAIN.get(p[3]), "#ccc")))
            if p[2] == 1:
                o.append('<path d="M%d %d L%d %d L%d %d Z" fill="#000" fill-opacity="0.22"/>' % (px + 6, py + S - 8, px + S / 2, py + 14, px + S - 6, py + S - 8))
                o.append('<text x="%d" y="%d" font-size="10" font-weight="bold" text-anchor="middle" fill="#2b1d00">HILL</text>' % (px + S / 2, py + S - 12))
            if p[2] == 0:
                o.append('<path d="M%d %d L%d %d L%d %d Z" fill="#444"/>' % (px + 6, py + S - 8, px + S / 2, py + 8, px + S - 6, py + S - 8))
            if p[4] == "FEATURE_FOREST":
                for k in range(3):
                    cx = px + 12 + k * 16
                    o.append('<path d="M%d %d L%d %d L%d %d Z" fill="#2f6b2a" fill-opacity="0.8"/>' % (cx - 5, py + S - 16, cx, py + S - 28, cx + 5, py + S - 16))
            if p[4] == "FEATURE_JUNGLE":
                for k in range(3):
                    o.append('<circle cx="%d" cy="%d" r="5" fill="#1f5c3a" fill-opacity="0.8"/>' % (px + 12 + k * 16, py + S - 22))
            if p[4] == "FEATURE_FLOOD_PLAINS":
                o.append('<rect x="%d" y="%d" width="%d" height="%d" fill="#9fd08c" fill-opacity="0.6"/>' % (px + 2, py + 2, S - 4, S - 4))
            if p[9]:
                o.append('<path d="M%d %d q4 -4 8 0 t8 0 t8 0" stroke="#2a6fd6" stroke-width="2.5" fill="none"/>' % (px + 4, py + S - 5))
            if p[8]:
                o.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#8b5a2b" stroke-width="3"/>' % (px + 4, py + S / 2, px + S - 4, py + S / 2))
            if p[6] >= 0:
                o.append('<rect x="%.1f" y="%.1f" width="%d" height="%d" fill="none" stroke="%s" stroke-width="3"/>' % (px + 1.5, py + 1.5, S - 3, S - 3, owner_col(p[6])))
            if p[5]:
                o.append('<text x="%d" y="%d" font-size="9" font-weight="bold" fill="#5a3b00">%s</text>' % (px + 3, py + 22, esc(nice(p[5], "BONUS_").capitalize())))
            o.append('<text x="%d" y="%d" font-size="9" fill="#111" fill-opacity="0.85">%d,%d</text>' % (px + 3, py + 11, x, y))
            if not p[10]:
                o.append('<rect x="%d" y="%d" width="%d" height="%d" fill="#fff" fill-opacity="0.45"/>' % (px, py, S, S))
            if (x, y) in UNITS:
                us = UNITS[(x, y)]
                o.append('<circle cx="%d" cy="%d" r="9" fill="%s" stroke="#fff" stroke-width="1.5"/>' % (px + S - 12, py + 12, owner_col(us[0][2])))
                o.append('<text x="%d" y="%d" font-size="10" font-weight="bold" text-anchor="middle" fill="#fff">%d</text>' % (px + S - 12, py + 16, sum(u[4] for u in us)))
            if (x, y) in CITIES:
                c = CITIES[(x, y)]
                o.append('<rect x="%d" y="%d" width="18" height="18" fill="%s" stroke="#fff" stroke-width="2"/>' % (px + S / 2 - 9, py + S / 2 - 9, owner_col(c["owner"])))
                labels.append('<rect x="%d" y="%d" width="60" height="14" rx="2" fill="#fff" fill-opacity="0.9"/><text x="%d" y="%d" font-size="10" font-weight="bold" text-anchor="middle" fill="%s">%s</text>' %
                              (px + S / 2 - 30, py + S / 2 + 10, px + S / 2, py + S / 2 + 21, owner_col(c["owner"]), esc(c["name"])))
    o.extend(labels)
    o.append('</svg>')
    return "\n".join(o), W, H


def svg_overview(S=14):
    xs = [x for x, y in PLOTS]
    ys = [y for x, y in PLOTS]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    S = max(6, min(S, 1500 // max(nx, ny)))   # stays under the ~1568 px an image keeps
    ML, MT = 26, 18
    W, H = ML + nx * S + 6, MT + ny * S + 6
    o = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" font-family="Menlo, monospace">' % (W, H, W, H),
         '<rect width="%d" height="%d" fill="#2b2b2b"/>' % (W, H)]
    for x in range(x0, x1 + 1):
        if x % 5 == 0:
            o.append('<text x="%d" y="12" font-size="10" text-anchor="middle" fill="#eee">%d</text>' % (ML + (x - x0) * S + S / 2, x))
    for y in range(y0, y1 + 1):
        if y % 5 == 0:
            o.append('<text x="%d" y="%d" font-size="10" text-anchor="end" fill="#eee">%d</text>' % (ML - 4, MT + (y1 - y) * S + S / 2 + 4, y))
    labels = []
    for (x, y), p in PLOTS.items():
        px, py = ML + (x - x0) * S, MT + (y1 - y) * S
        o.append('<rect x="%d" y="%d" width="%d" height="%d" fill="%s"/>' % (px, py, S, S, COLORS.get(TERRAIN.get(p[3]), "#ccc")))
        if p[2] == 1:
            o.append('<path d="M%d %d L%d %d L%d %d Z" fill="#000" fill-opacity="0.35"/>' % (px + 2, py + S - 2, px + S / 2, py + 3, px + S - 2, py + S - 2))
        if p[2] == 0:
            o.append('<rect x="%d" y="%d" width="%d" height="%d" fill="#333"/>' % (px + 2, py + 2, S - 4, S - 4))
        if p[4] in ("FEATURE_FOREST", "FEATURE_JUNGLE"):
            o.append('<circle cx="%d" cy="%d" r="%d" fill="#1f5c2a" fill-opacity="0.6"/>' % (px + S / 2, py + S / 2, S / 4))
        if p[6] >= 0:
            o.append('<rect x="%d" y="%d" width="%d" height="%d" fill="none" stroke="%s" stroke-width="2"/>' % (px + 1, py + 1, S - 2, S - 2, owner_col(p[6])))
        if not p[10]:
            o.append('<rect x="%d" y="%d" width="%d" height="%d" fill="#fff" fill-opacity="0.35"/>' % (px, py, S, S))
        if (x, y) in UNITS:
            o.append('<circle cx="%d" cy="%d" r="%d" fill="%s" stroke="#fff" stroke-width="1"/>' % (px + S / 2, py + S / 2, max(3, S / 3), owner_col(UNITS[(x, y)][0][2])))
        if (x, y) in CITIES:
            c = CITIES[(x, y)]
            o.append('<rect x="%d" y="%d" width="%d" height="%d" fill="%s" stroke="#fff" stroke-width="1.5"/>' % (px + 2, py + 2, S - 4, S - 4, owner_col(c["owner"])))
            labels.append('<text x="%d" y="%d" font-size="9" font-weight="bold" fill="#fff" stroke="#000" stroke-width="2" paint-order="stroke">%s</text>' % (px + S + 2, py + S - 3, esc(c["name"])))
    o.extend(labels)
    o.append('</svg>')
    return "\n".join(o), W, H


def to_png(svg, w, h, png):
    tmp = png[:-4] + ".svg"
    open(tmp, "w").write(svg)
    prof = os.path.join(os.path.dirname(png), ".chrome")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--user-data-dir=" + prof,
                    "--window-size=%d,%d" % (w, h), "--screenshot=" + png, "file://" + tmp],
                   capture_output=True, timeout=120)
    os.remove(tmp)
    return os.path.exists(png)


def pictures(state, out_dir, spots=None):
    """Overview + up to 3 close-ups; the latest in out_dir, a copy per turn in out_dir/T<turn>/ for the video."""
    load(state)
    if not os.path.exists(CHROME):
        return []
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        if f.endswith(".png"):
            os.remove(os.path.join(out_dir, f))
    files = []
    svg, w, h = svg_overview()
    if to_png(svg, w, h, os.path.join(out_dir, "overview.png")):
        files.append((os.path.join(out_dir, "overview.png"), "the whole known world, low detail"))
    for k, c in enumerate(crops_for(spots if spots is not None else hot_spots())):
        svg, w, h = svg_closeup(c["box"])
        png = os.path.join(out_dir, "closeup%d.png" % (k + 1))
        if to_png(svg, w, h, png):
            files.append((png, "close-up x %d-%d, y %d-%d: %s" % (c["box"][0], c["box"][1], c["box"][2], c["box"][3], "; ".join(sorted(set(c["why"]))))))
    arch = os.path.join(out_dir, "T%03d" % state.get("turn", 0))
    os.makedirs(arch, exist_ok=True)
    for f, _ in files:
        shutil.copy(f, arch)
    return files


def find_city(name):
    for xy, c in CITIES.items():
        if c["name"].lower() == name.lower():
            return xy
    raise SystemExit("no known city named %s" % name)


def main(argv):
    state = None
    if "--state" in argv:
        i = argv.index("--state")
        state = json.load(open(argv[i + 1]))
        argv = argv[:i] + argv[i + 2:]
    if not argv:
        print(__doc__.strip())
        return
    state = state or live_state()
    load(state)
    cmd = argv[0]
    if cmd == "brief":
        print(brief(state, argv[1] if len(argv) > 1 else None))
    elif cmd == "around":
        xy = tuple(int(v) for v in " ".join(argv[1:3]).replace(",", " ").split()[:2])
        print(around(xy))
    elif cmd == "where":
        v = [int(t) for t in " ".join(argv[1:]).replace(",", " ").replace("/", " ").split()]
        for xy in zip(v[0::2], v[1::2]):
            print("%d,%d = %s" % (xy[0], xy[1], where(xy)))
    elif cmd == "card":
        print(battle_card(find_city(" ".join(argv[1:]))))
    elif cmd == "pictures":
        for f, why in pictures(state, argv[1] if len(argv) > 1 else os.path.join(HERE, "out", "map")):
            print(f, "-", why)
    else:
        print(__doc__.strip())


if __name__ == "__main__":
    main(sys.argv[1:])
