# ClaudeBridge: writes the world as the "Claude" player sees it to
# C:\claude_bridge\state_latest.json (plus one archived copy per turn).
#
# Only what Claude's team has revealed / currently sees is written, so the
# dump never leaks the human player's hidden information.
#
# Python 2.4: no json module, no "with", no conditional expressions,
# no "except X as e". Keep it that way.

from CvPythonExtensions import *
import os
import sys
import time
import traceback

gc = CyGlobalContext()

BRIDGE_VERSION = 18
OUT_DIR = "C:\\claude_bridge"
CONFIG_FILE = OUT_DIR + "\\config.txt"


# ---------------------------------------------------------------- utilities

def ensureDir():
	if not os.path.isdir(OUT_DIR):
		os.makedirs(OUT_DIR)

def log(msg):
	try:
		ensureDir()
		f = open(OUT_DIR + "\\bridge.log", "a")
		try:
			f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg + "\n")
		finally:
			f.close()
	except:
		pass

def jstr(s):
	if not isinstance(s, unicode):
		s = unicode(str(s), "latin-1")
	out = []
	for ch in s:
		o = ord(ch)
		if ch == '"':
			out.append('\\"')
		elif ch == '\\':
			out.append('\\\\')
		elif o < 32 or o > 126:
			out.append('\\u%04x' % o)
		else:
			out.append(str(ch))
	return '"' + "".join(out) + '"'

def toJson(v):
	if v is None:
		return "null"
	if v is True:
		return "true"
	if v is False:
		return "false"
	if isinstance(v, (int, long)):
		# game enums are int subclasses whose str() is their name
		return "%d" % int(v)
	if isinstance(v, float):
		return repr(v)
	if isinstance(v, (str, unicode)):
		return jstr(v)
	if isinstance(v, (list, tuple)):
		return "[" + ",".join([toJson(x) for x in v]) + "]"
	if isinstance(v, dict):
		parts = []
		for k in v.keys():
			parts.append(jstr(k) + ":" + toJson(v[k]))
		return "{" + ",".join(parts) + "}"
	return jstr(v)

def writeAtomic(path, text):
	tmp = path + ".tmp"
	f = open(tmp, "wb")
	try:
		f.write(text)
	finally:
		f.close()
	if os.path.exists(path):
		os.remove(path)
	os.rename(tmp, path)

def infoType(getter, i):
	if i < 0:
		return None
	return getter(i).getType()


# ------------------------------------------------------------ who is Claude

g_acting = [None]   # player a request acts for ("player" in the request), else the default

def getClaudePlayer():
	# the request's own player if it names one; else config.txt "player = N";
	# otherwise the first living AI civ
	if g_acting[0] is not None:
		return g_acting[0]
	try:
		if os.path.exists(CONFIG_FILE):
			f = open(CONFIG_FILE, "r")
			try:
				for line in f.readlines():
					line = line.strip()
					if line.startswith("player"):
						return int(line.split("=")[1].strip())
			finally:
				f.close()
	except:
		pass
	for i in range(gc.getMAX_CIV_PLAYERS()):
		p = gc.getPlayer(i)
		if p.isAlive() and not p.isHuman() and not p.isBarbarian() and not p.isMinorCiv():
			return i
	return -1


# ------------------------------------------------------------------- dumping

def playerColor(p):
	c = gc.getColorInfo(gc.getPlayerColorInfo(p.getPlayerColor()).getColorTypePrimary()).getColor()
	return [int(c.r * 255), int(c.g * 255), int(c.b * 255)]

def collectPlayers(iMe):
	me = gc.getPlayer(iMe)
	myTeam = gc.getTeam(me.getTeam())
	players = []
	for i in range(gc.getMAX_PLAYERS()):
		p = gc.getPlayer(i)
		if not p.isAlive():
			continue
		met = (i == iMe) or myTeam.isHasMet(p.getTeam())
		d = {
			"id": i,
			"met": met,
			"barbarian": p.isBarbarian(),
			"color": playerColor(p),
		}
		if met:
			d["name"] = p.getName()
			d["civ"] = p.getCivilizationShortDescription(0)
			d["leader"] = infoType(gc.getLeaderHeadInfo, p.getLeaderType())
			d["human"] = p.isHuman()
			d["team"] = p.getTeam()
			d["score"] = gc.getGame().getPlayerScore(i)
			d["era"] = infoType(gc.getEraInfo, p.getCurrentEra())
			d["state_religion"] = infoType(gc.getReligionInfo, p.getStateReligion())
			if i != iMe and not p.isBarbarian():
				d["at_war_with_me"] = myTeam.isAtWar(p.getTeam())
				if not p.isHuman():
					# the AI's mood, as the diplomacy screen shows it; meaningless for humans
					d["their_attitude_to_me"] = infoType(gc.getAttitudeInfo, p.AI_getAttitude(iMe))
		players.append(d)
	return players

def collectMyEmpire(iMe):
	p = gc.getPlayer(iMe)
	tech = p.getCurrentResearch()
	cities = []
	(city, it) = p.firstCity(False)
	while city and not city.isNone():
		cities.append({
			"name": city.getName(),
			"x": city.getX(), "y": city.getY(),
			"pop": city.getPopulation(),
			"capital": city.isCapital(),
			"building": city.getProductionName(),
			"build_turns": city.getProductionTurnsLeft(),
			"food_turns": city.getFoodTurnsLeft(),
			"happy": city.happyLevel(), "unhappy": city.unhappyLevel(0),
			"health": city.goodHealth(), "unhealth": city.badHealth(False),
		})
		(city, it) = p.nextCity(it, False)
	d = {
		"gold": p.getGold(),
		"gold_per_turn": p.calculateGoldRate(),
		"research": infoType(gc.getTechInfo, tech),
		"cities": cities,
	}
	if tech >= 0:
		d["research_turns"] = p.getResearchTurnsLeft(tech, True)
	return d

def collectPlots(iMe):
	iTeam = gc.getPlayer(iMe).getTeam()
	m = CyMap()
	w = m.getGridWidth()
	h = m.getGridHeight()
	plots = []
	cities = []
	units = []
	for y in range(h):
		for x in range(w):
			pl = m.plot(x, y)
			if not pl.isRevealed(iTeam, False):
				continue
			vis = pl.isVisible(iTeam, False)
			# [x, y, plotType, terrain, feature, bonus, owner, improvement, route, river, visible]
			plots.append([
				x, y,
				pl.getPlotType(),
				infoType(gc.getTerrainInfo, pl.getTerrainType()),
				infoType(gc.getFeatureInfo, pl.getFeatureType()),
				infoType(gc.getBonusInfo, pl.getBonusType(iTeam)),
				pl.getRevealedOwner(iTeam, False),
				infoType(gc.getImprovementInfo, pl.getRevealedImprovementType(iTeam, False)),
				infoType(gc.getRouteInfo, pl.getRevealedRouteType(iTeam, False)),
				pl.isRiver(),
				vis,
			])
			if pl.isCity():
				c = pl.getPlotCity()
				cd = {"x": x, "y": y, "owner": c.getOwner(), "name": c.getName()}
				if vis or c.getOwner() == iMe:
					cd["pop"] = c.getPopulation()
				cities.append(cd)
			if vis:
				counts = {}
				for i in range(pl.getNumUnits()):
					u = pl.getUnit(i)
					if u.isNone() or u.isInvisible(iTeam, False):
						continue
					key = (u.getOwner(), gc.getUnitInfo(u.getUnitType()).getType())
					counts[key] = counts.get(key, 0) + 1
				for key in counts.keys():
					info = gc.getUnitInfo(gc.getInfoTypeForString(key[1]))
					units.append([x, y, key[0], key[1], counts[key], info.getCombat() > 0])
	return w, h, plots, cities, units

def dump(reason):
	iMe = getClaudePlayer()
	if iMe < 0:
		log("no AI player to dump for")
		return
	t0 = time.time()
	game = gc.getGame()
	w, h, plots, cities, units = collectPlots(iMe)
	state = {
		"version": 1,
		"reason": reason,
		"turn": game.getGameTurn(),
		"year": game.getGameTurnYear(),
		"me": iMe,
		"map": {"width": w, "height": h,
			"wrap_x": CyMap().isWrapX(), "wrap_y": CyMap().isWrapY()},
		"players": collectPlayers(iMe),
		"my_empire": collectMyEmpire(iMe),
		"plot_fields": ["x", "y", "plotType", "terrain", "feature", "bonus", "owner",
			"improvement", "route", "river", "visible"],
		"plots": plots,
		"cities": cities,
		"unit_fields": ["x", "y", "owner", "type", "count", "military"],
		"units": units,
	}
	ensureDir()
	text = toJson(state)
	writeAtomic(OUT_DIR + "\\state_latest.json", text)
	writeAtomic(OUT_DIR + "\\state_T%03d.json" % game.getGameTurn(), text)
	log("dump ok: %s turn=%d player=%d plots=%d units=%d %.2fs" %
		(reason, game.getGameTurn(), iMe, len(plots), len(units), time.time() - t0))

def safeDump(reason):
	try:
		dump(reason)
	except:
		log("dump FAILED (%s):\n%s" % (reason, "".join(traceback.format_exception(*sys.exc_info()))))


# ------------------------------------------------------------------ mailbox
#
# The Mac-side `civ` tool drops requests into C:\claude_bridge\in\<id>.json
# ({"id": ..., "cmd": ..., "args": {...}}); we answer in out\<id>.json with
# {"id": ..., "ok": true, "result": ...} or {"id": ..., "ok": false, "error": ...}.
# Polled from the per-frame Update event, so it works at any moment of the game.

IN_DIR = OUT_DIR + "\\in"
REPLY_DIR = OUT_DIR + "\\out"
g_pollLogged = [False]

def _ws(s, i):
	while i < len(s) and s[i] in " \t\r\n":
		i += 1
	return i

def _jstring(s, i):
	i += 1
	out = []
	while s[i] != '"':
		c = s[i]
		if c == "\\":
			n = s[i + 1]
			if n == "u":
				out.append(unichr(int(s[i + 2:i + 6], 16)))
				i += 6
				continue
			out.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}.get(n, n))
			i += 2
			continue
		out.append(c)
		i += 1
	return u"".join(out), i + 1

def _jvalue(s, i):
	i = _ws(s, i)
	c = s[i]
	if c == "{":
		d = {}
		i = _ws(s, i + 1)
		if s[i] == "}":
			return d, i + 1
		while 1:
			k, i = _jstring(s, _ws(s, i))
			i = _ws(s, i) + 1  # ':'
			v, i = _jvalue(s, i)
			d[str(k)] = v
			i = _ws(s, i)
			if s[i] == "}":
				return d, i + 1
			i += 1  # ','
	if c == "[":
		a = []
		i = _ws(s, i + 1)
		if s[i] == "]":
			return a, i + 1
		while 1:
			v, i = _jvalue(s, i)
			a.append(v)
			i = _ws(s, i)
			if s[i] == "]":
				return a, i + 1
			i += 1
	if c == '"':
		return _jstring(s, i)
	if s.startswith("true", i):
		return True, i + 4
	if s.startswith("false", i):
		return False, i + 5
	if s.startswith("null", i):
		return None, i + 4
	j = i
	while j < len(s) and s[j] in "+-0123456789.eE":
		j += 1
	t = s[i:j]
	if "." in t or "e" in t or "E" in t:
		return float(t), j
	return int(t), j

def fromJson(s):
	return _jvalue(s, 0)[0]


def gameReady():
	return gc.getGame().isFinalInitialized()

def cmdPing(args):
	d = {"game_ready": gameReady(), "bridge_version": BRIDGE_VERSION}
	if d["game_ready"]:
		game = gc.getGame()
		d["turn"] = game.getGameTurn()
		d["year"] = game.getGameTurnYear()
		d["claude_player"] = getClaudePlayer()
		active = []
		for i in range(gc.getMAX_PLAYERS()):
			if gc.getPlayer(i).isAlive() and gc.getPlayer(i).isTurnActive():
				active.append(i)
		d["turn_active_players"] = active
	return d

def collectMyUnits(iMe):
	p = gc.getPlayer(iMe)
	claims = loadClaims()
	units = []
	(u, it) = p.firstUnit(False)
	while u and not u.isNone():
		g = u.getGroup()
		units.append({
			"id": u.getID(),
			"type": gc.getUnitInfo(u.getUnitType()).getType(),
			"x": u.getX(), "y": u.getY(),
			"moves": u.movesLeft(), "max_moves": u.maxMoves(),
			"damage": u.getDamage(),
			"level": u.getLevel(), "xp": u.getExperience(),
			"group": u.getGroupID(),
			"automated": u.isAutomated(),
			"fortified": u.getFortifyTurns() > 0,
			"waiting": u.isWaiting(),
			"missions_queued": g.getLengthMissionQueue(),
			"claimed": claims.has_key(u.getID()),
			"target": claims.get(u.getID(), {}).get("target"),
		})
		(u, it) = p.nextUnit(it, False)
	return units

def cmdStatus(args):
	if not gameReady():
		raise Exception("no game in progress")
	iMe = getClaudePlayer()
	game = gc.getGame()
	return {
		"turn": game.getGameTurn(),
		"year": game.getGameTurnYear(),
		"me": iMe,
		"players": collectPlayers(iMe),
		"my_empire": collectMyEmpire(iMe),
		"my_units": collectMyUnits(iMe),
	}

# ------------------------------------------------------------- queries
#
# Everything here answers only with what Claude's team knows: revealed plots,
# currently visible units, met players. Own cities and units in full detail.

YIELDS = ["food", "production", "commerce"]
COMMERCES = ["gold", "research", "culture", "espionage"]

def myIds():
	iMe = getClaudePlayer()
	return iMe, gc.getPlayer(iMe).getTeam()

def findCity(args):
	# by name (any revealed city) or by x, y
	iMe, iTeam = myIds()
	m = CyMap()
	if args.has_key("x"):
		pl = m.plot(int(args["x"]), int(args["y"]))
		if pl.isCity() and pl.isRevealed(iTeam, False):
			return pl.getPlotCity()
		raise Exception("no known city at %d,%d" % (args["x"], args["y"]))
	want = args.get("name", u"").lower()
	for y in range(m.getGridHeight()):
		for x in range(m.getGridWidth()):
			pl = m.plot(x, y)
			if pl.isCity() and pl.isRevealed(iTeam, False):
				c = pl.getPlotCity()
				if c.getName().lower() == want:
					return c
	raise Exception("no known city named %s" % want)

def unitBrief(u, iTeam):
	d = {
		"id": u.getID(), "owner": u.getOwner(),
		"type": gc.getUnitInfo(u.getUnitType()).getType(),
		"x": u.getX(), "y": u.getY(),
	}
	if u.getTeam() == iTeam:
		d["damage"] = u.getDamage()
		d["moves"] = u.movesLeft()
		d["max_moves"] = u.maxMoves()
	return d

def orderName(o):
	t = int(o.eOrderType)
	if t == 0:
		return gc.getUnitInfo(o.iData1).getType()
	if t == 1:
		return gc.getBuildingInfo(o.iData1).getType()
	if t == 2:
		return gc.getProjectInfo(o.iData1).getType()
	if t == 3:
		return gc.getProcessInfo(o.iData1).getType()
	return "?"

def cmdMap(args):
	iMe, iTeam = myIds()
	w, h, plots, cities, units = collectPlots(iMe)
	return {"turn": gc.getGame().getGameTurn(), "year": gc.getGame().getGameTurnYear(),
		"me": iMe, "map": {"width": w, "height": h},
		"players": collectPlayers(iMe), "plots": plots, "cities": cities, "units": units}

def cmdTile(args):
	iMe, iTeam = myIds()
	x = int(args["x"])
	y = int(args["y"])
	pl = CyMap().plot(x, y)
	if pl.isNone():
		raise Exception("no such tile %d,%d" % (x, y))
	if not pl.isRevealed(iTeam, False):
		return {"x": x, "y": y, "revealed": False}
	vis = pl.isVisible(iTeam, False)
	d = {
		"x": x, "y": y, "revealed": True, "visible": vis,
		"plot_type": ["peak", "hills", "flat", "water"][int(pl.getPlotType())],
		"terrain": infoType(gc.getTerrainInfo, pl.getTerrainType()),
		"feature": infoType(gc.getFeatureInfo, pl.getFeatureType()),
		"bonus": infoType(gc.getBonusInfo, pl.getBonusType(iTeam)),
		"owner": pl.getRevealedOwner(iTeam, False),
		"improvement": infoType(gc.getImprovementInfo, pl.getRevealedImprovementType(iTeam, False)),
		"route": infoType(gc.getRouteInfo, pl.getRevealedRouteType(iTeam, False)),
		"river": pl.isRiver(), "fresh_water": pl.isFreshWater(), "coastal_land": (not pl.isWater()) and pl.isCoastalLand(),
		"defense_bonus": pl.defenseModifier(iTeam, True, False),
		"yields": dict([(YIELDS[i], pl.calculateYield(YieldTypes(i), True)) for i in range(3)]),
	}
	if pl.isCity():
		c = pl.getPlotCity()
		d["city"] = {"name": c.getName(), "owner": c.getOwner()}
	wc = pl.getWorkingCity()
	if wc and not wc.isNone() and wc.getOwner() == iMe:
		d["in_radius_of"] = wc.getName()
		d["worked"] = pl.isBeingWorked()
	if vis:
		d["units"] = []
		for i in range(pl.getNumUnits()):
			u = pl.getUnit(i)
			if not u.isNone() and not u.isInvisible(iTeam, False):
				d["units"].append(unitBrief(u, iTeam))
	return d

def cmdCity(args):
	iMe, iTeam = myIds()
	c = findCity(args)
	d = {"name": c.getName(), "owner": c.getOwner(), "x": c.getX(), "y": c.getY()}
	pl = c.plot()
	if c.getOwner() != iMe:
		if pl.isVisible(iTeam, False):
			d["pop"] = c.getPopulation()
			d["defense_percent"] = c.getDefenseModifier(False)
			d["units"] = [unitBrief(pl.getUnit(i), iTeam) for i in range(pl.getNumUnits())
				if not pl.getUnit(i).isInvisible(iTeam, False)]
		d["religions"] = [gc.getReligionInfo(r).getType() for r in range(gc.getNumReligionInfos())
			if c.isHasReligion(r) and c.isRevealed(iTeam, False)]
		return d
	d.update({
		"pop": c.getPopulation(),
		"capital": c.isCapital(),
		"food": {"stored": c.getFood(), "needed": c.growthThreshold(), "surplus": c.foodDifference(True),
			"turns": c.getFoodTurnsLeft()},
		"yields": dict([(YIELDS[i], c.getYieldRate(i)) for i in range(3)]),
		"commerce": dict([(COMMERCES[i], c.getCommerceRate(i)) for i in range(4)]),
		"production": {"item": c.getProductionName(), "progress": c.getProduction(),
			"needed": c.getProductionNeeded(), "turns": c.getProductionTurnsLeft()},
		"queue": [orderName(c.getOrderFromQueue(i)) for i in range(c.getOrderQueueLength())],
		"happy": c.happyLevel(), "unhappy": c.unhappyLevel(0),
		"health": c.goodHealth(), "unhealth": c.badHealth(False),
		"culture": c.getCulture(iMe), "culture_level": infoType(gc.getCultureLevelInfo, c.getCultureLevel()),
		"defense_percent": c.getDefenseModifier(False),
		"maintenance": c.getMaintenance(),
		"great_people": {"progress": c.getGreatPeopleProgress(), "rate": c.getGreatPeopleRate()},
		"buildings": [gc.getBuildingInfo(b).getType() for b in range(gc.getNumBuildingInfos())
			if c.getNumRealBuilding(b) > 0],
		"religions": [gc.getReligionInfo(r).getType() for r in range(gc.getNumReligionInfos()) if c.isHasReligion(r)],
		"holy_city_of": [gc.getReligionInfo(r).getType() for r in range(gc.getNumReligionInfos()) if c.isHolyCityByType(r)],
		"specialists": dict([(gc.getSpecialistInfo(i).getType(), c.getSpecialistCount(i))
			for i in range(gc.getNumSpecialistInfos()) if c.getSpecialistCount(i) > 0]),
		"can_train": [gc.getUnitInfo(i).getType() for i in range(gc.getNumUnitInfos()) if c.canTrain(i, False, False)],
		"can_build": [gc.getBuildingInfo(i).getType() for i in range(gc.getNumBuildingInfos())
			if c.canConstruct(i, False, False, False)],
		"garrison": [unitBrief(pl.getUnit(i), iTeam) for i in range(pl.getNumUnits())],
	})
	tiles = []
	for i in range(21):
		tp = c.getCityIndexPlot(i)
		if tp and not tp.isNone():
			tiles.append([tp.getX(), tp.getY(), c.isWorkingPlot(tp),
				tp.getYield(YieldTypes(0)), tp.getYield(YieldTypes(1)), tp.getYield(YieldTypes(2))])
	d["tile_fields"] = ["x", "y", "worked", "food", "production", "commerce"]
	d["tiles"] = tiles
	return d

def cmdUnit(args):
	iMe, iTeam = myIds()
	u = gc.getPlayer(iMe).getUnit(int(args["id"]))
	if not u or u.isNone():
		raise Exception("I have no unit #%s" % args["id"])
	g = u.getGroup()
	info = gc.getUnitInfo(u.getUnitType())
	d = unitBrief(u, iTeam)
	d.update({
		"name": u.getName(),
		"strength": info.getCombat(), "moves_per_turn": info.getMoves(),
		"level": u.getLevel(), "xp": u.getExperience(),
		"promotions": [gc.getPromotionInfo(i).getType() for i in range(gc.getNumPromotionInfos()) if u.isHasPromotion(i)],
		"group": u.getGroupID(), "group_size": g.getNumUnits(),
		"automated": u.isAutomated(), "fortified": u.getFortifyTurns() > 0, "waiting": u.isWaiting(),
		"missions_queued": g.getLengthMissionQueue(),
		"cargo": u.getCargo(),
	})
	return d

def cmdPlayer(args):
	iMe, iTeam = myIds()
	want = args.get("name")
	target = -1
	for i in range(gc.getMAX_PLAYERS()):
		p = gc.getPlayer(i)
		if not p.isAlive():
			continue
		if want is not None and (str(i) == str(want) or p.getName().lower() == unicode(want).lower()
				or p.getCivilizationShortDescription(0).lower() == unicode(want).lower()):
			target = i
			break
	if target < 0:
		raise Exception("no living player called %s" % want)
	p = gc.getPlayer(target)
	team = gc.getTeam(iTeam)
	if target != iMe and not team.isHasMet(p.getTeam()):
		return {"id": target, "met": False}
	d = [x for x in collectPlayers(iMe) if x["id"] == target][0]
	other = gc.getTeam(p.getTeam())
	d["civics"] = [infoType(gc.getCivicInfo, p.getCivics(i)) for i in range(gc.getNumCivicOptionInfos())]
	if target != iMe:
		d["open_borders"] = team.isOpenBorders(p.getTeam())
		d["defensive_pact"] = team.isDefensivePact(p.getTeam())
		d["their_techs"] = [gc.getTechInfo(t).getType() for t in range(gc.getNumTechInfos()) if other.isHasTech(t)]
		d["techs_they_lack"] = [gc.getTechInfo(t).getType() for t in range(gc.getNumTechInfos())
			if team.isHasTech(t) and not other.isHasTech(t)]
		known = []
		m = CyMap()
		(c, it) = p.firstCity(False)
		while c and not c.isNone():
			if c.isRevealed(iTeam, False):
				known.append({"name": c.getName(), "x": c.getX(), "y": c.getY()})
			(c, it) = p.nextCity(it, False)
		d["known_cities"] = known
	else:
		d["techs"] = [gc.getTechInfo(t).getType() for t in range(gc.getNumTechInfos()) if team.isHasTech(t)]
	return d


# --------------------------------------------------------------- events log
#
# Appended to events.jsonl; the Mac side reads the file directly, so it works
# even while the game window is in the background.

EVENTS_FILE = OUT_DIR + "\\events.jsonl"

def pname(i):
	iMe, iTeam = myIds()
	if i < 0:
		return "nobody"
	p = gc.getPlayer(i)
	if i == iMe or gc.getTeam(iTeam).isHasMet(p.getTeam()):
		return p.getName() + " (" + p.getCivilizationShortDescription(0) + ")"
	return "an unknown civilization"

def writeEvent(kind, d):
	if not d.has_key("turn"):
		d["turn"] = gc.getGame().getGameTurn()
	d["year"] = gc.getGame().getTurnYear(d["turn"])
	d["kind"] = kind
	d["time"] = time.strftime("%H:%M:%S")
	ensureDir()
	if kind in ATTENTION_KINDS:
		noteAttention(kind)
	f = open(EVENTS_FILE, "ab")
	try:
		f.write(toJson(d) + "\n")
	finally:
		f.close()

def recordEvent(tag, a):
	if not gameReady():
		return
	iMe, iTeam = myIds()
	if iMe < 0:
		return
	if tag == "chat":
		# the game's own chat line (multiplayer-style); "%s" strips the wide-string wrapper
		text = u"%s" % (a[0],)
		# "<color=...>[V to all]:  hi</color>" -> "hi"; our own lines are not echoed back here
		if text.startswith(u"<color=") and text.endswith(u"</color>"):
			text = text[text.index(u">") + 1:-len(u"</color>")]
		if text.startswith(u"[") and u"]:" in text:
			text = text[text.index(u"]:") + 2:].strip()
		writeChat("player", text)
		if text.strip().lower() == u"!go":
			setReady("player")
			CyInterface().addImmediateMessage(u"Turn unlocked by you (!go).", "")
		else:
			writeEvent("message_from_player", {"text": text, "via": "chat"})
	elif tag == "BeginPlayerTurn" and a[1] == iMe:
		writeEvent("my_turn_begins", {})
	elif tag == "BeginPlayerTurn" and gc.getPlayer(a[1]).isHuman():
		# fired before the game turn counter moves on: the player is about to play turn a[0] + 1
		writeEvent("player_turn_begins", {"gate": readGate().get("on", False), "turn": a[0] + 1})
		autoReadyOrWake(a[0] + 1)
	elif tag == "firstContact" and iTeam in (a[0], a[1]):
		other = a[1]
		if other == iTeam:
			other = a[0]
		names = [pname(i) for i in range(gc.getMAX_CIV_PLAYERS())
			if gc.getPlayer(i).isAlive() and gc.getPlayer(i).getTeam() == other]
		writeEvent("first_contact", {"with": names})
	elif tag == "cityBuilt":
		c = a[0]
		if c.getOwner() == iMe or c.plot().isRevealed(iTeam, False):
			writeEvent("city_founded", {"name": c.getName(), "owner": pname(c.getOwner()), "x": c.getX(), "y": c.getY()})
	elif tag == "cityAcquired":
		prev, new, c, conquest = a[0], a[1], a[2], a[3]
		if iMe in (prev, new) or c.plot().isRevealed(iTeam, False):
			writeEvent("city_changed_hands", {"name": c.getName(), "from": pname(prev), "to": pname(new),
				"conquest": conquest, "x": c.getX(), "y": c.getY()})
	elif tag == "cityRazed":
		c, who = a[0], a[1]
		if iMe in (c.getOwner(), who):
			writeEvent("city_razed", {"name": c.getName(), "by": pname(who)})
	elif tag == "combatResult":
		win, lose = a[0], a[1]
		if iMe in (win.getOwner(), lose.getOwner()):
			# a scout beating a wild animal is not news: log it, but don't wake anyone for it
			kind = "combat"
			if win.getOwner() == iMe and lose.isAnimal():
				kind = "combat_animal"
			writeEvent(kind, {
				"winner": pname(win.getOwner()), "winner_unit": gc.getUnitInfo(win.getUnitType()).getType(),
				"loser": pname(lose.getOwner()), "loser_unit": gc.getUnitInfo(lose.getUnitType()).getType(),
				"x": lose.getX(), "y": lose.getY()})
	elif tag == "unitBuilt" and a[0].getOwner() == iMe:
		writeEvent("unit_built", {"city": a[0].getName(), "unit": gc.getUnitInfo(a[1].getUnitType()).getType(),
			"id": a[1].getID()})
	elif tag == "buildingBuilt":
		c, b = a[0], a[1]
		info = gc.getBuildingInfo(b)
		if c.getOwner() == iMe or isWorldWonderClass(info.getBuildingClassType()):
			writeEvent("building_built", {"city": c.getName(), "owner": pname(c.getOwner()), "building": info.getType()})
	elif tag == "projectBuilt":
		writeEvent("project_built", {"owner": pname(a[0].getOwner()), "project": gc.getProjectInfo(a[1]).getType()})
	elif tag == "techAcquired" and a[1] == iTeam:
		writeEvent("tech_learned", {"tech": gc.getTechInfo(a[0]).getType()})
	elif tag == "religionFounded":
		writeEvent("religion_founded", {"religion": gc.getReligionInfo(a[0]).getType(), "by": pname(a[1])})
	elif tag == "changeWar":
		war, t1, t2 = a[0], a[1], a[2]
		team = gc.getTeam(iTeam)
		if iTeam in (t1, t2) or (team.isHasMet(t1) and team.isHasMet(t2)):
			kind = "peace_made"
			if war:
				kind = "war_declared"
			writeEvent(kind, {"team": gc.getTeam(t1).getName(), "against": gc.getTeam(t2).getName()})
	elif tag == "greatPersonBorn" and a[1] == iMe:
		writeEvent("great_person", {"unit": gc.getUnitInfo(a[0].getUnitType()).getType(), "city": a[2].getName()})
	elif tag == "goldenAge" and a[0] == iMe:
		writeEvent("golden_age", {})
	elif tag == "goodyReceived" and a[0] == iMe:
		writeEvent("goody_hut", {"goody": gc.getGoodyInfo(a[3]).getType()})
	elif tag == "cultureExpansion" and a[0].getOwner() == iMe:
		writeEvent("borders_expanded", {"city": a[0].getName()})

def safeRecordEvent(tag, args):
	try:
		recordEvent(tag, args)
	except:
		log("event %s FAILED:\n%s" % (tag, "".join(traceback.format_exception(*sys.exc_info()))))


# ------------------------------------------------------------------- claims
#
# A claimed unit belongs to Claude: the built-in AI never moves it. Each time the
# AI would update it, we walk it toward its target (if any) or make it wait.
# Claims live in claims.json so they survive hot reloads and game restarts.

CLAIMS_FILE = OUT_DIR + "\\claims.json"

def loadClaims():
	if not os.path.exists(CLAIMS_FILE):
		return {}
	f = open(CLAIMS_FILE, "rb")
	try:
		d = fromJson(f.read())
	finally:
		f.close()
	out = {}
	for k in d.keys():
		out[int(k)] = d[k]
	return out

def saveClaims(c):
	d = {}
	for k in c.keys():
		d[str(k)] = c[k]
	ensureDir()
	writeAtomic(CLAIMS_FILE, toJson(d))

def setClaim(uid, target):
	c = loadClaims()
	c[int(uid)] = {"target": target}
	saveClaims(c)

def aiUnitUpdate(gu, argsList):
	u = argsList[0]
	if u.getOwner() != getClaudePlayer():
		return gu._claudeOrigUnitUpdate(argsList)
	claims = loadClaims()
	if not claims.has_key(u.getID()):
		return gu._claudeOrigUnitUpdate(argsList)
	g = u.getGroup()
	t = claims[u.getID()].get("target")
	if t and (u.getX(), u.getY()) != (t[0], t[1]):
		# the pathfinder only knows revealed tiles: aim at the target itself, or else at the
		# revealed tiles closest to it (exploring towards it), nearest first
		for (x, y) in waypoints(u, t[0], t[1]):
			g.pushMission(MissionTypes.MISSION_MOVE_TO, x, y, 0, False, True, MissionAITypes.NO_MISSIONAI, CyMap().plot(x, y), u)
			if g.getLengthMissionQueue() > 0 or u.movesLeft() == 0:
				return 1
		g.pushMission(MissionTypes.MISSION_SKIP, -1, -1, 0, False, False, MissionAITypes.NO_MISSIONAI, u.plot(), u)
		return 1
	if t:
		claims[u.getID()]["target"] = None
		saveClaims(claims)
		writeEvent("unit_arrived", {"id": u.getID(), "unit": gc.getUnitInfo(u.getUnitType()).getType(),
			"x": u.getX(), "y": u.getY()})
	g.pushMission(MissionTypes.MISSION_SKIP, -1, -1, 0, False, False, MissionAITypes.NO_MISSIONAI, u.plot(), u)
	return 1

def waypoints(u, tx, ty, limit=6):
	iTeam = u.getTeam()
	m = CyMap()
	tp = m.plot(tx, ty)
	if tp.isRevealed(iTeam, False):
		return [(tx, ty)]
	here = plotDistance(u.getX(), u.getY(), tx, ty)
	best = []
	for y in range(m.getGridHeight()):
		for x in range(m.getGridWidth()):
			pl = m.plot(x, y)
			if not pl.isRevealed(iTeam, False) or (x, y) == (u.getX(), u.getY()):
				continue
			if pl.isWater() != (u.getDomainType() == DomainTypes.DOMAIN_SEA):
				continue
			d = plotDistance(x, y, tx, ty)
			if d < here:
				best.append((d, plotDistance(u.getX(), u.getY(), x, y), x, y))
	best.sort()
	return [(b[2], b[3]) for b in best[:limit]]

def unitUpdateTrampoline(argsList):
	import CvGameInterfaceFile
	return sys.modules["ClaudeBridge"].aiUnitUpdate(CvGameInterfaceFile.GameUtils, argsList)

def cmdClaim(args):
	u = myUnit(args["id"])
	c = loadClaims()
	if not c.has_key(u.getID()):
		c[u.getID()] = {"target": None}
		saveClaims(c)
	return {"id": u.getID(), "claimed": True}

def cmdRelease(args):
	c = loadClaims()
	if args.get("id") == "all":
		saveClaims({})
		return {"released": "all"}
	uid = int(args["id"])
	if c.has_key(uid):
		del c[uid]
		saveClaims(c)
	return {"id": uid, "claimed": False}

# ------------------------------------------------------------------ actions

def myUnit(uid):
	iMe, iTeam = myIds()
	u = gc.getPlayer(iMe).getUnit(int(uid))
	if not u or u.isNone():
		raise Exception("I have no unit #%s" % uid)
	return u

def cmdMove(args):
	# order a unit (with its whole group) to walk to x, y; multi-turn paths are fine
	u = myUnit(args["id"])
	x = int(args["x"])
	y = int(args["y"])
	pl = CyMap().plot(x, y)
	if pl.isNone():
		raise Exception("no such tile %d,%d" % (x, y))
	g = u.getGroup()
	before = (u.getX(), u.getY())
	setClaim(u.getID(), [x, y])
	g.pushMission(MissionTypes.MISSION_MOVE_TO, x, y, 0, False, True, MissionAITypes.NO_MISSIONAI, pl, u)
	if (u.getX(), u.getY()) == before and g.getLengthMissionQueue() == 0 and before != (x, y):
		raise Exception("unit #%d did not accept the move to %d,%d (unreachable or no moves?)" % (u.getID(), x, y))
	return {"id": u.getID(), "from": before, "now_at": (u.getX(), u.getY()), "target": (x, y),
		"moves_left": u.movesLeft(), "missions_queued": g.getLengthMissionQueue()}

# --------------------------------------------------------------------- chat
#
# Player -> Claude: Ctrl+Shift+C in the game opens a text box; the text goes to
# chat.jsonl (and events.jsonl as message_from_player).
# Claude -> player: `civ say` shows a popup from the Claude leader + a log line.
#
# Hooks are attached to the live event manager at runtime (installPatches), so
# chat works without changing ClaudeEventManager.py and survives hot reloads.

CHAT_FILE = OUT_DIR + "\\chat.jsonl"
CHAT_EVENT_ID = 5917
g_patched = [False]

def leaderTitle():
	p = gc.getPlayer(getClaudePlayer())
	return u"%s of %s" % (p.getName(), p.getCivilizationShortDescription(0))

def writeChat(who, text):
	ensureDir()
	f = open(CHAT_FILE, "ab")
	try:
		f.write(toJson({"from": who, "text": text, "turn": gc.getGame().getGameTurn(),
			"time": time.strftime("%H:%M:%S")}) + "\n")
	finally:
		f.close()

def chatBegin(argsList=-1):
	import Popup as PyPopup
	popup = PyPopup.PyPopup(CHAT_EVENT_ID, EventContextTypes.EVENTCONTEXT_ALL)
	popup.setHeaderString(u"Message to " + leaderTitle())
	popup.setBodyString(u"Write in English or translit. Claude answers in a few seconds.")
	popup.createEditBox(u"")
	popup.setEditBoxMaxCharCount(400, 60)
	popup.launch()

def chatApply(playerID, userData, popupReturn):
	text = popupReturn.getEditBoxString(0)
	if text:
		writeChat("player", text)
		writeEvent("message_from_player", {"text": text})
		CyInterface().addImmediateMessage(u"You to %s: %s" % (gc.getPlayer(getClaudePlayer()).getName(), text), "")
	return 0

def onKey(em, argsList):
	eventType, key = argsList[0], argsList[1]
	if eventType == em.EventKeyDown and int(key) == int(InputTypes.KB_C) and em.bCtrl and em.bShift:
		chatBegin()
		return 1
	return em._claudeOrigKbd(argsList)

def kbdTrampoline(argsList):
	# always dispatch to the newest loaded bridge module
	import CvEventInterface
	return sys.modules["ClaudeBridge"].onKey(CvEventInterface.getEventManager(), argsList)

def installPatches():
	import CvEventInterface
	import CvUtil
	em = CvEventInterface.getEventManager()
	em.Events[CHAT_EVENT_ID] = ("ClaudeChat", chatApply, chatBegin)
	if CHAT_EVENT_ID not in CvUtil.SilentEvents:
		CvUtil.SilentEvents.append(CHAT_EVENT_ID)
	if not hasattr(em, "_claudeOrigKbd"):
		em._claudeOrigKbd = em.EventHandlerMap["kbdEvent"]
	em.EventHandlerMap["kbdEvent"] = kbdTrampoline
	import CvGameInterfaceFile
	gu = CvGameInterfaceFile.GameUtils
	if not hasattr(gu, "_claudeOrigUnitUpdate"):
		gu._claudeOrigUnitUpdate = gu.AI_unitUpdate
	gu.AI_unitUpdate = unitUpdateTrampoline
	if not hasattr(gu, "_claudeOrigCannotDoControl"):
		gu._claudeOrigCannotDoControl = gu.cannotDoControl
	gu.cannotDoControl = cannotDoControlTrampoline
	if not hasattr(gu, "_claudeOrigChooseProduction"):
		gu._claudeOrigChooseProduction = gu.AI_chooseProduction
	gu.AI_chooseProduction = chooseProductionTrampoline
	g_patched[0] = True
	log("hooks installed: chat, unit claims, city claims, turn gate")

def cmdSay(args):
	# a chat line in the game's chat log (like a human opponent), or a popup with popup=true
	text = args["text"]
	me = gc.getPlayer(getClaudePlayer())
	if args.get("popup"):
		import Popup as PyPopup
		popup = PyPopup.PyPopup()
		popup.setHeaderString(args.get("title") or leaderTitle())
		popup.setBodyString(text)
		popup.launch()
	else:
		# bright and a size bigger; a "major event" stays in the event log (Ctrl+Tab) for good,
		# a chat-type line would drop out after 20 turns
		line = u"<font=4><color=255,200,60,255>[%s to you]:  %s</color></font>" % (me.getName(), text)
		for i in range(gc.getMAX_CIV_PLAYERS()):
			if gc.getPlayer(i).isAlive() and gc.getPlayer(i).isHuman():
				CyInterface().addMessage(i, True, gc.getEVENT_MESSAGE_TIME() * 3, line, "",
					InterfaceMessageTypes.MESSAGE_TYPE_MAJOR_EVENT, "", -1, -1, -1, False, False)
	writeChat("claude", text)
	return {"shown": True}


# ------------------------------------------------------- orders: research, builds
#
# The player's own decisions, checked by the game's rules (canResearch, canTrain...)
# so an impossible order fails with a reason instead of silently doing nothing.
# Cities given an order are "claimed": the built-in AI won't change what they build
# while their queue has something in it (the AI_chooseProduction hook).

CITY_CLAIMS_FILE = OUT_DIR + "\\city_claims.json"

def findInfo(want, count, getter, prefix):
	# by type ("TECH_ARCHERY") or description ("Archery"), case-insensitive
	w = want.strip().lower().replace(" ", "_")
	for i in range(count):
		info = getter(i)
		t = info.getType().lower()
		if t == w or t == prefix + w or info.getDescription().lower().replace(" ", "_") == w:
			return i
	return -1

def techName(i):
	if i < 0:
		return None
	return gc.getTechInfo(i).getDescription()

def researchState(p):
	t = gc.getTeam(p.getTeam())
	cur = p.getCurrentResearch()
	queue = [techName(i) for i in range(gc.getNumTechInfos()) if p.isResearchingTech(i)]
	queue.sort(lambda a, b: cmp(p.getQueuePosition(findInfo(a, gc.getNumTechInfos(), gc.getTechInfo, "tech_")),
		p.getQueuePosition(findInfo(b, gc.getNumTechInfos(), gc.getTechInfo, "tech_"))))
	d = {"researching": techName(cur), "queue": queue, "beakers_per_turn": p.calculateResearchRate(-1)}
	if cur >= 0:
		d["progress"] = "%d/%d" % (t.getResearchProgress(cur), t.getResearchCost(cur))
		d["turns"] = p.getResearchTurnsLeft(cur, True)
	d["can_research"] = ["%s (%dt)" % (techName(i), p.getResearchTurnsLeft(i, True))
		for i in range(gc.getNumTechInfos()) if p.canResearch(i, False)]
	return d

def cmdResearch(args):
	# no tech: show research; tech: research it now (the game queues missing prerequisites);
	# queue=true: add it after what is already queued
	p = gc.getPlayer(getClaudePlayer())
	if args.get("tech"):
		i = findInfo(args["tech"], gc.getNumTechInfos(), gc.getTechInfo, "tech_")
		if i < 0:
			raise Exception("no tech called %s" % args["tech"])
		if gc.getTeam(p.getTeam()).isHasTech(i):
			raise Exception("we already know %s" % techName(i))
		p.pushResearch(i, not args.get("queue"))
		if not p.isResearchingTech(i):
			raise Exception("can't research %s (missing prerequisites we can't research yet?)" % techName(i))
	return researchState(p)

def loadCityClaims():
	if not os.path.exists(CITY_CLAIMS_FILE):
		return []
	f = open(CITY_CLAIMS_FILE, "rb")
	try:
		return fromJson(f.read()) or []
	finally:
		f.close()

def claimCity(c):
	ids = loadCityClaims()
	key = "%d:%d" % (c.getOwner(), c.getID())
	if key not in ids:
		ids.append(key)
		writeAtomic(CITY_CLAIMS_FILE, toJson(ids))

def findItem(want):
	# a unit, building, project or process for a city's queue
	for (order, count, getter, prefix) in (
			(OrderTypes.ORDER_TRAIN, gc.getNumUnitInfos(), gc.getUnitInfo, "unit_"),
			(OrderTypes.ORDER_CONSTRUCT, gc.getNumBuildingInfos(), gc.getBuildingInfo, "building_"),
			(OrderTypes.ORDER_CREATE, gc.getNumProjectInfos(), gc.getProjectInfo, "project_"),
			(OrderTypes.ORDER_MAINTAIN, gc.getNumProcessInfos(), gc.getProcessInfo, "process_")):
		i = findInfo(want, count, getter, prefix)
		if i >= 0:
			return order, i, getter(i).getDescription()
	raise Exception("nothing called %s to build" % want)

def cmdBuild(args):
	# what a city of ours builds: replace the current item (default), queue=true to add at the end,
	# first=true to put it in front; check=true only tells whether it is possible
	iMe, iTeam = myIds()
	c = findCity(args)
	if c.getOwner() != iMe:
		raise Exception("%s is not our city" % c.getName())
	order, i, name = findItem(args["item"])
	if order == OrderTypes.ORDER_TRAIN:
		possible = c.canTrain(i, False, False)
	elif order == OrderTypes.ORDER_CONSTRUCT:
		possible = c.canConstruct(i, False, False, False)
	elif order == OrderTypes.ORDER_CREATE:
		possible = c.canCreate(i, False, False)
	else:
		possible = c.canMaintain(i, False)
	if not possible:
		raise Exception("%s can't build %s now" % (c.getName(), name))
	if args.get("check"):
		return {"city": c.getName(), "item": name, "possible": True}
	if args.get("queue"):
		c.pushOrder(order, i, -1, False, False, True, False)
	elif args.get("first"):
		c.pushOrder(order, i, -1, False, False, False, True)
	else:
		c.clearOrderQueue()
		c.pushOrder(order, i, -1, False, True, False, True)
	claimCity(c)
	return {"city": c.getName(), "queue": [orderName(c.getOrderFromQueue(k)) for k in range(c.getOrderQueueLength())],
		"turns": c.getProductionTurnsLeft()}

def aiChooseProduction(gu, argsList):
	c = argsList[0]
	if c.getOrderQueueLength() > 0 and ("%d:%d" % (c.getOwner(), c.getID())) in loadCityClaims():
		return True   # keep our queue; the built-in AI chooses only when it runs empty
	return gu._claudeOrigChooseProduction(argsList)

def chooseProductionTrampoline(argsList):
	import CvGameInterfaceFile
	return sys.modules["ClaudeBridge"].aiChooseProduction(CvGameInterfaceFile.GameUtils, argsList)

# ---------------------------------------------------------------- turn gate
#
# Claude plays its turn while the human plays theirs. The human cannot end the
# turn (End Turn button, Enter) until Claude says `civ ready` for this turn.
# Auto end-turn would bypass that, so "wait at end of turn" is switched on.
# Escape hatch: the player types !go in chat. Gate is on/off via `civ gate`.

GATE_FILE = OUT_DIR + "\\gate.json"
g_gateNag = [0]

def readGate():
	if not os.path.exists(GATE_FILE):
		return {"on": False, "ready_turn": -1}
	f = open(GATE_FILE, "rb")
	try:
		return fromJson(f.read())
	finally:
		f.close()

def writeGate(d):
	ensureDir()
	writeAtomic(GATE_FILE, toJson(d))

def claudeReady():
	g = readGate()
	return (not g.get("on")) or g.get("ready_turn") == gc.getGame().getGameTurn()

def humanTurn():
	# the turn the human is playing, or is about to play while the AIs are still moving
	t = gc.getGame().getGameTurn()
	for i in humanPlayers():
		if gc.getPlayer(i).isTurnActive():
			return t
	return t + 1

def setReady(byWhom):
	g = readGate()
	g["ready_turn"] = humanTurn()
	g["attention"] = []
	writeGate(g)
	writeEvent("claude_ready", {"by": byWhom})

# Auto-ready: on quiet turns the bridge says "ready" by itself, so Claude is only
# woken (event "claude_wake", with reasons) when something needs attention:
# events below since the last ready, an enemy inside or next to our borders,
# or a regular review every few turns. Switched with `civ gate auto on|off [N]`.

ATTENTION_KINDS = ("first_contact", "war_declared", "peace_made", "city_founded", "city_changed_hands",
	"city_razed", "combat", "tech_learned", "building_built", "project_built", "religion_founded",
	"great_person", "golden_age", "unit_arrived")

def noteAttention(kind):
	g = readGate()
	if not g.get("auto"):
		return
	reasons = g.get("attention") or []
	if kind not in reasons:
		reasons.append(kind)
		g["attention"] = reasons
		writeGate(g)

def enemiesNear():
	# enemy or barbarian units we can see on our land or right next to it
	iMe, iTeam = myIds()
	team = gc.getTeam(iTeam)
	found = []
	m = CyMap()
	for i in range(m.numPlots()):
		pl = m.plotByIndex(i)
		if not pl.isVisible(iTeam, False):
			continue
		near = pl.getOwner() == iMe
		if not near:
			for dx in (-1, 0, 1):
				for dy in (-1, 0, 1):
					q = m.plot(pl.getX() + dx, pl.getY() + dy)
					if q and not q.isNone() and q.getOwner() == iMe:
						near = True
		if not near:
			continue
		for k in range(pl.getNumUnits()):
			u = pl.getUnit(k)
			if u.isInvisible(iTeam, False) or u.getOwner() == iMe:
				continue
			if u.isBarbarian() or team.isAtWar(u.getTeam()):
				found.append("%s at %d,%d" % (gc.getUnitInfo(u.getUnitType()).getDescription(), pl.getX(), pl.getY()))
				break
	return found

def autoReadyOrWake(turn):
	g = readGate()
	if not (g.get("on") and g.get("auto")):
		return
	reasons = list(g.get("attention") or [])
	enemies = enemiesNear()
	if enemies:
		reasons.append("enemy_near: " + "; ".join(enemies[:5]))
	me = gc.getPlayer(myIds()[0])
	if me.getCurrentResearch() < 0 and me.getNumCities() > 0:
		reasons.append("research_idle")
	every = int(g.get("review_every") or 5)
	if every > 0 and turn % every == 0:
		reasons.append("review")
	if reasons:
		writeEvent("claude_wake", {"turn": turn, "reasons": reasons})
	else:
		g["ready_turn"] = turn
		writeGate(g)
		writeEvent("auto_ready", {"turn": turn})

def humanPlayers():
	return [i for i in range(gc.getMAX_CIV_PLAYERS()) if gc.getPlayer(i).isAlive() and gc.getPlayer(i).isHuman()]

def cannotDoControl(gu, argsList):
	eControl = argsList[0]
	if eControl in (ControlTypes.CONTROL_ENDTURN, ControlTypes.CONTROL_ENDTURN_ALT, ControlTypes.CONTROL_FORCEENDTURN):
		if not claudeReady():
			# canDoControl is also polled to draw the button; only nag once in a while
			g_gateNag[0] = g_gateNag[0] + 1
			if g_gateNag[0] % 200 == 1:
				CyInterface().addImmediateMessage(u"%s is still thinking about this turn... (type !go in chat to skip)" %
					gc.getPlayer(getClaudePlayer()).getName(), "")
				writeEvent("player_waiting", {})
			return 1
	return gu._claudeOrigCannotDoControl(argsList)

def cannotDoControlTrampoline(argsList):
	import CvGameInterfaceFile
	return sys.modules["ClaudeBridge"].cannotDoControl(CvGameInterfaceFile.GameUtils, argsList)

def cmdReady(args):
	setReady("claude")
	CyInterface().addImmediateMessage(u"%s has finished thinking. You may end the turn." %
		gc.getPlayer(getClaudePlayer()).getName(), "")
	return {"ready_turn": readGate()["ready_turn"]}

def cmdHold(args):
	# take "ready" back: the player cannot end the turn until the next `civ ready`
	g = readGate()
	g["ready_turn"] = -1
	writeGate(g)
	writeEvent("claude_hold", {})
	CyInterface().addImmediateMessage(u"%s wants a moment to think before you end the turn." %
		gc.getPlayer(getClaudePlayer()).getName(), "")
	return {"ready": claudeReady()}

def cmdGate(args):
	g = readGate()
	if args.has_key("auto"):
		g["auto"] = bool(args["auto"])
		if args.has_key("every"):
			g["review_every"] = int(args["every"])
		writeGate(g)
	if args.has_key("on"):
		g["on"] = bool(args["on"])
		writeGate(g)
		if g["on"]:
			for i in humanPlayers():
				gc.getPlayer(i).setOption(PlayerOptionTypes.PLAYEROPTION_WAIT_END_TURN, True)
	g["turn"] = gc.getGame().getGameTurn()
	g["ready"] = claudeReady()
	return g

# ------------------------------------------------------- dev: run any code
#
# Runs a Python snippet inside the game with the full game API in scope.
# Sees EVERYTHING (no fog of war), so it is for building and debugging only:
# every snippet is logged to exec.log, and it can be switched off with
# "exec = off" in config.txt for a fair game.

def execAllowed():
	try:
		if os.path.exists(CONFIG_FILE):
			f = open(CONFIG_FILE, "r")
			try:
				for line in f.readlines():
					line = line.strip().replace(" ", "")
					if line == "exec=off":
						return False
			finally:
				f.close()
	except:
		pass
	return True

def cmdExec(args):
	if not execAllowed():
		raise Exception("exec is switched off in config.txt (fair play mode)")
	code = args["code"]
	f = open(OUT_DIR + "\\exec.log", "a")
	try:
		f.write("---- %s turn %d\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), gc.getGame().getGameTurn(),
			code.encode("utf-8")))
	finally:
		f.close()
	ns = {"gc": gc, "CyMap": CyMap, "game": gc.getGame(), "me": getClaudePlayer()}
	ns.update(globals())
	try:
		return {"value": repr(eval(compile(code, "<claude>", "eval"), ns))}
	except SyntaxError:
		pass
	ns["result"] = None
	eval(compile(code, "<claude>", "exec"), ns)
	return {"value": repr(ns["result"])}

COMMANDS = {
	"ready": cmdReady,
	"hold": cmdHold,
	"gate": cmdGate,
	"claim": cmdClaim,
	"release": cmdRelease,
	"say": cmdSay,
	"exec": cmdExec,
	"move": cmdMove,
	"research": cmdResearch,
	"build": cmdBuild,
	"ping": cmdPing,
	"status": cmdStatus,
	"map": cmdMap,
	"tile": cmdTile,
	"city": cmdCity,
	"unit": cmdUnit,
	"player": cmdPlayer,
}

def handleRequest(name):
	path = IN_DIR + "\\" + name
	f = open(path, "rb")
	try:
		text = f.read()
	finally:
		f.close()
	os.remove(path)
	rid = name[:-5]
	log("request " + name)
	try:
		req = fromJson(text)
		rid = req.get("id", rid)
		cmd = req.get("cmd")
		if not COMMANDS.has_key(cmd):
			raise Exception("unknown command: %s" % cmd)
		if req.get("player") is not None:
			if gc.getPlayer(int(req["player"])).isHuman():
				raise Exception("player %s is a human: agents can only act for AI-controlled civs" % req["player"])
			g_acting[0] = int(req["player"])
		try:
			reply = {"id": rid, "ok": True, "result": COMMANDS[cmd](req.get("args") or {})}
		finally:
			g_acting[0] = None
	except:
		reply = {"id": rid, "ok": False,
			"error": "".join(traceback.format_exception(*sys.exc_info()))}
	writeAtomic(REPLY_DIR + "\\" + str(rid) + ".json", toJson(reply))
	log("reply %s ok=%s" % (rid, reply["ok"]))

def poll():
	# throttled by the caller (frame counter); time.time() moves in 128 s steps in-game
	if not g_patched[0] and gameReady():
		try:
			installPatches()
		except:
			g_patched[0] = True  # don't retry every frame
			log("installPatches FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
	if not g_pollLogged[0]:
		g_pollLogged[0] = True
		log("mailbox polling started")
	try:
		if not os.path.isdir(IN_DIR):
			os.makedirs(IN_DIR)
		if not os.path.isdir(REPLY_DIR):
			os.makedirs(REPLY_DIR)
		names = [n for n in os.listdir(IN_DIR) if n.endswith(".json")]
		names.sort()
		for n in names:
			handleRequest(n)
	except:
		log("poll FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
