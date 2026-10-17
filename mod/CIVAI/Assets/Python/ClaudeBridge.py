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

BRIDGE_VERSION = 30
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
		w = unicode(want).lower()
		if want is not None and (str(i) == str(want) or p.getName().lower() == w
				or p.getCivilizationShortDescription(0).lower() == w
				or (len(w) >= 3 and (p.getName().lower().startswith(w)
					or p.getCivilizationShortDescription(0).lower().startswith(w)))):
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
		elif text.strip().lower().startswith(u"!accept") or text.strip().lower().startswith(u"!decline"):
			human = humanPlayers()
			answerOffer(text.strip(), human and human[0] or 0)
		else:
			writeEvent("message_from_player", {"text": text, "via": "chat"})
	elif tag == "BeginPlayerTurn" and a[1] == iMe:
		writeEvent("my_turn_begins", {})
		refreshSnapshot()
	elif tag == "BeginPlayerTurn" and gc.getPlayer(a[1]).isHuman():
		# fired before the game turn counter moves on: the player is about to play turn a[0] + 1
		writeEvent("player_turn_begins", {"gate": readGate().get("on", False), "turn": a[0] + 1})
		refreshSnapshot()
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
		cityItemDone(a[0], OrderTypes.ORDER_TRAIN, a[1].getUnitType())
		writeEvent("unit_built", {"city": a[0].getName(), "unit": gc.getUnitInfo(a[1].getUnitType()).getType(),
			"id": a[1].getID()})
	elif tag == "buildingBuilt":
		c, b = a[0], a[1]
		if c.getOwner() == iMe:
			cityItemDone(c, OrderTypes.ORDER_CONSTRUCT, b)
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
	cl = claims[u.getID()]
	if cl.get("mission") and not cl.get("started"):
		# an order given outside this civ's turn gets dropped when the turn starts: run it now
		m, d1, d2 = cl["mission"]
		cl["started"] = True
		saveClaims(claims)
		pl = u.plot()
		if d1 >= 0 and d2 >= 0 and cl.get("targeted"):
			pl = CyMap().plot(d1, d2)
		g.pushMission(MissionTypes(m), d1, d2, 0, False, True, MissionAITypes.NO_MISSIONAI, pl, u)
		return 1
	t = cl.get("target")
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
	elif cl.get("busy"):
		cl["busy"] = False
		cl["mission"] = None
		saveClaims(claims)
		writeEvent("unit_done", {"id": u.getID(), "unit": gc.getUnitInfo(u.getUnitType()).getType(),
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
	em.Events[DEAL_EVENT_ID] = ("ClaudeDeal", dealApplyTrampoline, dealBeginTrampoline)
	if DEAL_EVENT_ID not in CvUtil.SilentEvents:
		CvUtil.SilentEvents.append(DEAL_EVENT_ID)
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
	if not hasattr(gu, "_claudeOrigDoDiplo"):
		gu._claudeOrigDoDiplo = gu.AI_doDiplo
	gu.AI_doDiplo = doDiploTrampoline
	if not hasattr(gu, "_claudeOrigDoWar"):
		gu._claudeOrigDoWar = gu.AI_doWar
	gu.AI_doWar = doWarTrampoline
	g_patched[0] = True
	log("hooks installed: chat, unit claims, city claims, diplomacy, war, turn gate")

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



# ------------------------------------------------------------------ area map
#
# A compact text map of a region, limited to what our civ has seen, plus the best
# city sites there (the game's own site rating, only for sites we have mostly seen).

TERRAIN_CH = {"TERRAIN_GRASS": "g", "TERRAIN_PLAINS": "p", "TERRAIN_DESERT": "d", "TERRAIN_TUNDRA": "t",
	"TERRAIN_SNOW": "s", "TERRAIN_COAST": "~", "TERRAIN_OCEAN": "=", "TERRAIN_PEAK": "^", "TERRAIN_HILL": "h"}
FEATURE_CH = {"FEATURE_FOREST": "f", "FEATURE_JUNGLE": "j", "FEATURE_FLOOD_PLAINS": "l", "FEATURE_OASIS": "o",
	"FEATURE_ICE": "i", "FEATURE_FALLOUT": "x"}

def ownerCh(o):
	if o < 0:
		return "."
	return "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"[o % 36]

def areaCell(pl, iMe, iTeam):
	if not pl.isRevealed(iTeam, False):
		return "    "
	t = gc.getTerrainInfo(pl.getTerrainType()).getType()
	if pl.isPeak():
		c1 = "^"
	else:
		c1 = TERRAIN_CH.get(t, "?")
		if pl.isHills():
			c1 = c1.upper()
	f = pl.getFeatureType()
	c2 = "."
	if f >= 0:
		c2 = FEATURE_CH.get(gc.getFeatureInfo(f).getType(), "?")
	c3 = "."
	if pl.isCity():
		c3 = "#"
		if pl.getPlotCity().getOwner() == iMe:
			c3 = "@"
	else:
		units = []
		if pl.isVisible(iTeam, False):
			units = [pl.getUnit(k) for k in range(pl.getNumUnits())]
			units = [u for u in units if not u.isInvisible(iTeam, False)]
		if [u for u in units if u.getOwner() != iMe]:
			c3 = "x"
		elif units:
			c3 = "u"
		elif pl.getBonusType(iTeam) >= 0:
			c3 = "*"
		elif pl.isRiver():
			c3 = ":"
	return c1 + c2 + c3 + ownerCh(pl.getRevealedOwner(iTeam, False))

def cmdArea(args):
	iMe, iTeam = myIds()
	me = gc.getPlayer(iMe)
	m = CyMap()
	cx, cy, r = int(args["x"]), int(args["y"]), int(args.get("r", 6))
	rows = ["     " + "".join(["%-4d" % ((cx + dx) % m.getGridWidth()) for dx in range(-r, r + 1)])]
	cities, bonuses, foreign, owners = [], [], [], {}
	for dy in range(r, -r - 1, -1):          # north at the top
		line = []
		for dx in range(-r, r + 1):
			pl = m.plot(cx + dx, cy + dy)
			if pl is None or pl.isNone():
				line.append("    ")
				continue
			line.append(areaCell(pl, iMe, iTeam))
			if not pl.isRevealed(iTeam, False):
				continue
			o = pl.getRevealedOwner(iTeam, False)
			if o >= 0:
				owners[ownerCh(o)] = pname(o)
			if pl.isCity():
				c = pl.getPlotCity()
				cities.append("%s (%d,%d) %s" % (c.getName(), pl.getX(), pl.getY(), pname(c.getOwner())))
			b = pl.getBonusType(iTeam)
			if b >= 0:
				bonuses.append("%s (%d,%d)" % (gc.getBonusInfo(b).getDescription(), pl.getX(), pl.getY()))
			if pl.isVisible(iTeam, False):
				for k in range(pl.getNumUnits()):
					u = pl.getUnit(k)
					if u.getOwner() != iMe and not u.isInvisible(iTeam, False):
						foreign.append("%s of %s (%d,%d)" % (gc.getUnitInfo(u.getUnitType()).getDescription(),
							pname(u.getOwner()), pl.getX(), pl.getY()))
		rows.append("%4d " % (cy + dy) + "".join(line))
	d = {"map": rows, "cities": cities, "resources": bonuses, "foreign_units": foreign,
		"owners": ["%s = %s" % (k, v) for k, v in owners.items()],
		"legend": "each tile = 4 chars: terrain (g grass, p plains, d desert, t tundra, s snow, ~ coast, = ocean, ^ peak; "
			"CAPITAL = hills), feature (f forest, j jungle, l flood plains, o oasis, i ice, . none), "
			"what's on it (@ our city, # other city, u our unit, x foreign unit, * resource, : river, . nothing), "
			"owner (. nobody, else player id, see owners). Blank = never seen. North is up: y grows to the NORTH, x grows to the EAST (a smaller y is south of you)."}
	if args.get("sites", True):
		sites = []
		for dy in range(-r, r + 1):
			for dx in range(-r, r + 1):
				pl = m.plot(cx + dx, cy + dy)
				if pl is None or pl.isNone() or not pl.isRevealed(iTeam, False) or pl.isWater():
					continue
				if not me.canFound(pl.getX(), pl.getY()):
					continue
				seen = 0
				for i in range(21):
					q = plotCity(pl.getX(), pl.getY(), i)
					if q and not q.isNone() and q.isRevealed(iTeam, False):
						seen += 1
				if seen < 15:
					continue
				v = me.AI_foundValue(pl.getX(), pl.getY(), -1, False)
				if v > 0:
					sites.append((v, pl.getX(), pl.getY(), seen))
		sites.sort()
		sites.reverse()
		d["best_city_sites"] = ["(%d,%d) value %d, %d/21 tiles seen" % (x, y, v, n) for (v, x, y, n) in sites[:5]]
	return d


# ------------------------------------------------------------------ unit actions
#
# The same buttons a human sees for a unit, taken from the game's own action list
# and checked with the game's own rules (canStartMission / canDoCommand / canAutomate).
# Names: FORTIFY, SENTRY, FOUND, BUILD_FARM, PILLAGE, PROMOTE_COMBAT1, UPGRADE_KESHIK,
# AUTO_BUILD, AUTO_EXPLORE, ... Targeted actions (MOVE_TO, ROUTE_TO, ...) take x y.

TARGETED_MISSIONS = ("MISSION_MOVE_TO", "MISSION_ROUTE_TO", "MISSION_AIRLIFT", "MISSION_NUKE",
	"MISSION_RECON", "MISSION_PARADROP", "MISSION_AIRBOMB", "MISSION_RANGE_ATTACK", "MISSION_AIRPATROL",
	"MISSION_SEAPATROL", "MISSION_MOVE_TO_UNIT", "MISSION_ESPIONAGE")

def actionName(a):
	m, c, au = a.getMissionType(), a.getCommandType(), a.getAutomateType()
	if m >= 0:
		t = gc.getMissionInfo(m).getType()
		if t == "MISSION_BUILD":
			return gc.getBuildInfo(a.getMissionData()).getType()
		return t[len("MISSION_"):]
	if c >= 0:
		t = gc.getCommandInfo(c).getType()[len("COMMAND_"):]
		if t in ("HOTKEY", "AUTOMATE"):
			return None   # interface internals; automation is offered as AUTO_* actions
		if t == "PROMOTION":
			return "PROMOTE_" + gc.getPromotionInfo(a.getCommandData()).getType()[len("PROMOTION_"):]
		if t == "UPGRADE":
			return "UPGRADE_" + gc.getUnitInfo(a.getCommandData()).getType()[len("UNIT_"):]
		return t
	if au >= 0:
		return "AUTO_" + gc.getAutomateInfo(au).getType()[len("AUTOMATE_"):]
	return None

def unitActions(u):
	# [(name, action info, needs target)] for what this unit can do right now
	g = u.getGroup()
	out = []
	for i in range(gc.getNumActionInfos()):
		a = gc.getActionInfo(i)
		try:
			name = actionName(a)
		except:
			name = None   # actions without data the game can show (e.g. a generic promotion entry)
		if not name:
			continue
		m, c, au = a.getMissionType(), a.getCommandType(), a.getAutomateType()
		try:
			if m >= 0:
				if gc.getMissionInfo(m).getType() in TARGETED_MISSIONS:
					if gc.getMissionInfo(m).getType() in ("MISSION_MOVE_TO", "MISSION_ROUTE_TO") and u.canMove():
						out.append((name, a, True))
					continue
				if g.canStartMission(m, a.getMissionData(), -1, u.plot(), False):
					out.append((name, a, False))
			elif c >= 0:
				if u.canDoCommand(CommandTypes(c), a.getCommandData(), -1, False):
					out.append((name, a, False))
			elif au >= 0:
				if g.canAutomate(AutomateTypes(au)):
					out.append((name, a, False))
		except:
			pass
	return out

def cmdActions(args):
	u = myUnit(args["id"])
	acts = unitActions(u)
	return {"id": u.getID(), "unit": gc.getUnitInfo(u.getUnitType()).getDescription(), "at": (u.getX(), u.getY()),
		"moves_left": u.movesLeft() / gc.getMOVE_DENOMINATOR(),
		"actions": [n for (n, a, t) in acts if not t], "with_target_x_y": [n for (n, a, t) in acts if t]}

def cmdDo(args):
	# do one of the unit's available actions; queue=true adds it after its current orders
	u = myUnit(args["id"])
	want = args["action"].strip().upper().replace(" ", "_")
	acts = unitActions(u)
	match = [x for x in acts if x[0] == want]
	if not match:
		raise Exception("%s #%d can't %s here now. It can: %s" % (gc.getUnitInfo(u.getUnitType()).getDescription(),
			u.getID(), want, ", ".join([n for (n, a, t) in acts])))
	name, a, targeted = match[0]
	g = u.getGroup()
	m, c, au = a.getMissionType(), a.getCommandType(), a.getAutomateType()
	if targeted:
		if not args.has_key("x"):
			raise Exception("%s needs a target: civ do %d %s X Y" % (name, u.getID(), name))
		if name == "MOVE_TO":
			return cmdMove(args)
		x, y = int(args["x"]), int(args["y"])
		ours = gc.getPlayer(u.getOwner()).isTurnActive()
		c2 = loadClaims()
		c2[u.getID()] = {"target": None, "busy": True, "mission": [m, x, y], "targeted": True, "started": ours}
		saveClaims(c2)
		if ours:
			g.pushMission(MissionTypes(m), x, y, 0, bool(args.get("queue")), True, MissionAITypes.NO_MISSIONAI, CyMap().plot(x, y), u)
	elif m >= 0:
		# outside our own turn the game drops queued orders at turn start, so the claim keeps
		# the order and the unit hook issues it when our turn comes (started=False)
		ours = gc.getPlayer(u.getOwner()).isTurnActive()
		c2 = loadClaims()
		c2[u.getID()] = {"target": None, "busy": True, "mission": [m, a.getMissionData(), -1], "started": ours}
		saveClaims(c2)
		if ours:
			g.pushMission(MissionTypes(m), a.getMissionData(), -1, 0, bool(args.get("queue")), True, MissionAITypes.NO_MISSIONAI, u.plot(), u)
		else:
			g.clearMissionQueue()
			return {"id": u.getID(), "will_do": name, "when": "at the start of our next turn (orders given during another player's turn run then)"}
	elif c >= 0:
		u.doCommand(CommandTypes(c), a.getCommandData(), -1)
	else:
		# automation hands the unit back to the game's own automation
		c2 = loadClaims()
		if c2.has_key(u.getID()):
			del c2[u.getID()]
			saveClaims(c2)
		g.setAutomateType(AutomateTypes(au))
	if u.isNone():
		return {"id": args["id"], "done": name, "unit": "gone (used up, e.g. founded a city)"}
	return {"id": u.getID(), "done": name, "at": (u.getX(), u.getY()), "moves_left": u.movesLeft() / gc.getMOVE_DENOMINATOR(),
		"orders_queued": g.getLengthMissionQueue()}




# ------------------------------------------------- state religion and civics are Claude's
#
# The built-in AI adopts state religions and changes civics for its civ on its own, and
# the game offers no hook to stop it. So the bridge remembers what Claude chose and puts
# back any change Claude didn't order (cancelling the anarchy it caused). Claude changes
# them with `civ religion` / `civ civics`, paying the normal anarchy.

CHOICES_FILE = OUT_DIR + "\\choices.json"
g_guardTick = [0]

def currentChoices(p):
	return {"religion": p.getStateReligion(),
		"civics": [p.getCivics(o) for o in range(gc.getNumCivicOptionInfos())]}

def loadChoices():
	if not os.path.exists(CHOICES_FILE):
		return None
	f = open(CHOICES_FILE, "rb")
	try:
		return fromJson(f.read())
	finally:
		f.close()

def saveChoices(c):
	writeAtomic(CHOICES_FILE, toJson(c))

def guardChoices():
	g_guardTick[0] = g_guardTick[0] + 1
	if g_guardTick[0] % 25:
		return
	p = gc.getPlayer(getClaudePlayer())
	if not p.isAlive():
		return
	want = loadChoices()
	now = currentChoices(p)
	if want is None:
		saveChoices(now)   # start from whatever the civ has now
		return
	undone = []
	if now["religion"] != want["religion"]:
		p.setLastStateReligion(want["religion"])
		undone.append("state religion %s" % religionName(now["religion"]))
	for o in range(len(want["civics"])):
		if now["civics"][o] != want["civics"][o]:
			p.setCivics(o, want["civics"][o])
			undone.append("civic %s" % gc.getCivicInfo(now["civics"][o]).getDescription())
	if undone:
		extra = p.getAnarchyTurns() - int(want.get("own_anarchy", 0))
		if extra > 0:
			p.changeAnarchyTurns(-extra)
		writeEvent("ai_change_undone", {"undone": undone,
			"note": "the built-in AI changed this without your order; the bridge put it back"})

def religionName(r):
	if r < 0:
		return "none"
	return gc.getReligionInfo(r).getDescription()

def cmdReligion(args):
	# no name: show the options; a name (or "none"): convert, with the game's normal anarchy
	p = gc.getPlayer(getClaudePlayer())
	have = [r for r in range(gc.getNumReligionInfos()) if p.getHasReligionCount(r) > 0]
	if not args.get("name"):
		return {"state_religion": religionName(p.getStateReligion()),
			"in_our_cities": ["%s (%d cities)" % (religionName(r), p.getHasReligionCount(r)) for r in have],
			"anarchy_if_we_convert": p.getReligionAnarchyLength(),
			"can_convert_now": [religionName(r) for r in have + [-1] if p.canConvert(r)]}
	w = args["name"].strip().lower()
	r = -1
	if w != "none":
		r = findInfo(w, gc.getNumReligionInfos(), gc.getReligionInfo, "religion_")
		if r < 0:
			raise Exception("no religion called %s" % args["name"])
	if not p.canConvert(r):
		raise Exception("can't adopt %s now (not in our cities, already ours, anarchy, or too soon after the last change)" % religionName(r))
	anarchy = p.getReligionAnarchyLength()
	p.convert(r)
	c = currentChoices(p)
	c["own_anarchy"] = p.getAnarchyTurns()
	saveChoices(c)
	return {"state_religion": religionName(p.getStateReligion()), "anarchy_turns": anarchy}

def cmdCivics(args):
	# no names: show current civics and what we could adopt; names: switch to them
	p = gc.getPlayer(getClaudePlayer())
	cur = [p.getCivics(o) for o in range(gc.getNumCivicOptionInfos())]
	if not args.get("names"):
		return {"current": ["%s: %s" % (gc.getCivicOptionInfo(o).getDescription(), gc.getCivicInfo(cur[o]).getDescription())
				for o in range(len(cur))],
			"can_adopt": [gc.getCivicInfo(c).getDescription() for c in range(gc.getNumCivicInfos())
				if p.canDoCivics(c) and c not in cur],
			"turns_until_allowed": p.getRevolutionTimer()}
	new = list(cur)
	for n in args["names"]:
		c = findInfo(n, gc.getNumCivicInfos(), gc.getCivicInfo, "civic_")
		if c < 0:
			raise Exception("no civic called %s" % n)
		if not p.canDoCivics(c):
			raise Exception("we can't adopt %s (needs %s?)" % (gc.getCivicInfo(c).getDescription(),
				", ".join(techList([gc.getCivicInfo(c).getTechPrereq()])) or "something else"))
		new[gc.getCivicInfo(c).getCivicOptionType()] = c
	if new == cur:
		raise Exception("those are our civics already")
	if p.getRevolutionTimer() > 0 or p.isAnarchy():
		raise Exception("too soon to change civics again (%d turns), or in anarchy" % p.getRevolutionTimer())
	anarchy = p.getCivicAnarchyLength(new)
	for o in range(len(new)):
		if new[o] != cur[o]:
			p.setCivics(o, new[o])
	if anarchy > 0:
		p.changeAnarchyTurns(anarchy)
	c = currentChoices(p)
	c["own_anarchy"] = p.getAnarchyTurns()
	saveChoices(c)
	return {"civics": [gc.getCivicInfo(x).getDescription() for x in new], "anarchy_turns": anarchy}

# ------------------------------------------------- deals made in the game's own screen
#
# When the human trades with Claude's civ through the normal diplomacy screen, the
# built-in AI decides and no event tells us. So during the human's turn the bridge
# compares snapshots of what Claude's civ has (techs, gold, open borders, pacts, war,
# resource imports/exports) and reports an unexplained change as "native_deal":
# in the story, Claude's ministers traded on their own authority.

g_snap = [None]
g_snapTick = [0]

def takeSnapshot():
	iMe, iTeam = myIds()
	me, team = gc.getPlayer(iMe), gc.getTeam(iTeam)
	d = {"techs": [t for t in range(gc.getNumTechInfos()) if team.isHasTech(t)], "gold": me.getGold(), "rel": {}, "res": {}, "theirs": {},
		"researching": [t for t in range(gc.getNumTechInfos()) if me.isResearchingTech(t)]}
	for i in range(gc.getMAX_CIV_PLAYERS()):
		p = gc.getPlayer(i)
		if i == iMe or not p.isAlive() or not team.isHasMet(p.getTeam()):
			continue
		d["rel"][i] = [team.isOpenBorders(p.getTeam()), team.isDefensivePact(p.getTeam()), team.isAtWar(p.getTeam())]
		d["theirs"][i] = [t for t in range(gc.getNumTechInfos()) if gc.getTeam(p.getTeam()).isHasTech(t)]
	for b in range(gc.getNumBonusInfos()):
		if me.getBonusImport(b) or me.getBonusExport(b):
			d["res"][b] = [me.getBonusImport(b), me.getBonusExport(b)]
	return d

def refreshSnapshot():
	try:
		g_snap[0] = takeSnapshot()
	except:
		g_snap[0] = None

def checkNativeDeal():
	# called often during the human's turn; cheap enough every couple of seconds
	g_snapTick[0] = g_snapTick[0] + 1
	if g_snapTick[0] % 40:
		return
	if not humanPlayers() or not [i for i in humanPlayers() if gc.getPlayer(i).isTurnActive()]:
		return
	old = g_snap[0]
	new = takeSnapshot()
	g_snap[0] = new
	if old is None:
		return
	# a tech we were researching just finished: research, not a deal
	got = [gc.getTechInfo(t).getDescription() for t in new["techs"] if t not in old["techs"] and t not in old.get("researching", [])]
	lost = [gc.getTechInfo(t).getDescription() for t in old["techs"] if t not in new["techs"]]
	changes = []
	if got:
		changes.append("we got " + ", ".join(got))
	if lost:
		changes.append("we lost " + ", ".join(lost))
	for i, rel in new["rel"].items():
		was = old["rel"].get(i)
		if was is None:
			continue
		for k, name in ((0, "open borders"), (1, "defensive pact"), (2, "war")):
			if rel[k] != was[k]:
				state = "ended"
				if rel[k]:
					state = "started"
				changes.append("%s with %s %s" % (name, pname(i), state))
		gained = [gc.getTechInfo(t).getDescription() for t in new["theirs"].get(i, []) if t not in old["theirs"].get(i, [])]
		if gained:
			changes.append("%s gained %s at the same time" % (pname(i), ", ".join(gained)))
	for b in dict(new["res"].items() + old["res"].items()).keys():
		a, z = old["res"].get(b, [0, 0]), new["res"].get(b, [0, 0])
		if a != z:
			changes.append("%s: importing %d (was %d), exporting %d (was %d)" % (gc.getBonusInfo(b).getDescription(), z[0], a[0], z[1], a[1]))
	if not [c for c in changes if not c.endswith("at the same time")]:
		return   # only someone else's research moved: not a deal with us
	if new["gold"] != old["gold"]:
		changes.append("our gold %d -> %d" % (old["gold"], new["gold"]))
	writeEvent("native_deal", {"changes": changes,
		"note": "made in the game's own diplomacy screen; the built-in AI agreed on our behalf"})

# ------------------------------------------------------------------------ deals
#
# The game's own deal machinery isn't reachable from Python, but its results are
# (setHasTech, signOpenBorders, makePeace, declareWar...). So deals are done here,
# each item checked with the game's own rules (canTradeItem) first.
#   - with the human: the offer shows on screen; they answer "!accept N" / "!decline N" in chat
#   - with an AI: it decides at once, by the game's own refusal rules (getTradeDenial),
#     its attitude, and a simple value check
# The built-in AI's own diplomacy and war planning are switched off for Claude's civ
# (AI_doDiplo / AI_doWar hooks): every deal, demand and war of that civ is Claude's.
# Items: tech:<name>, gold:<n>, open_borders, defensive_pact, peace, war:<player>

OFFERS_FILE = OUT_DIR + "\\offers.json"

def loadOffers():
	if not os.path.exists(OFFERS_FILE):
		return {"next": 1, "open": {}}
	f = open(OFFERS_FILE, "rb")
	try:
		return fromJson(f.read())
	finally:
		f.close()

def saveOffers(o):
	writeAtomic(OFFERS_FILE, toJson(o))

def findPlayer(want):
	w = unicode(want).lower()
	for i in range(gc.getMAX_CIV_PLAYERS()):
		p = gc.getPlayer(i)
		if p.isAlive() and (str(i) == w or p.getName().lower().startswith(w)
				or p.getCivilizationShortDescription(0).lower().startswith(w)):
			return i
	raise Exception("no player called %s" % want)

def parseItem(text):
	k = text.strip().lower()
	if ":" in k:
		kind, arg = k.split(":", 1)
	else:
		kind, arg = k, ""
	kind = kind.strip().replace(" ", "_")
	if kind == "tech":
		i = findInfo(arg, gc.getNumTechInfos(), gc.getTechInfo, "tech_")
		if i < 0:
			raise Exception("no tech called %s" % arg)
		return ("tech", i)
	if kind == "gold":
		return ("gold", int(arg))
	if kind in ("open_borders", "defensive_pact", "peace"):
		return (kind, -1)
	if kind == "war":
		return ("war", findPlayer(arg))
	raise Exception("unknown deal item %s (tech:<name>, gold:<n>, open_borders, defensive_pact, peace, war:<player>)" % text)

def itemText(it):
	kind, d = it
	if kind == "tech":
		return gc.getTechInfo(d).getDescription()
	if kind == "gold":
		return "%d gold" % d
	if kind == "war":
		return "war on " + pname(d)
	return kind.replace("_", " ")

TRADE_TYPES = {"tech": "TRADE_TECHNOLOGIES", "gold": "TRADE_GOLD", "open_borders": "TRADE_OPEN_BORDERS",
	"defensive_pact": "TRADE_DEFENSIVE_PACT", "peace": "TRADE_PEACE_TREATY", "war": "TRADE_WAR"}

def tradeData(it):
	kind, d = it
	t = TradeData()
	t.ItemType = getattr(TradeableItems, TRADE_TYPES[kind])
	if kind == "war":
		t.iData = gc.getPlayer(d).getTeam()
	elif kind in ("tech", "gold"):
		t.iData = d
	else:
		t.iData = 0
	return t

def checkItem(giver, taker, it):
	# raise unless `giver` may give `it` to `taker` under the game's rules
	g, t = gc.getPlayer(giver), gc.getPlayer(taker)
	kind, d = it
	if kind == "peace":
		if not gc.getTeam(g.getTeam()).isAtWar(t.getTeam()):
			raise Exception("%s and %s are not at war" % (pname(giver), pname(taker)))
		return
	if kind == "gold" and g.getGold() < d:
		raise Exception("%s has only %d gold" % (pname(giver), g.getGold()))
	if not g.canTradeItem(taker, tradeData(it), False):
		raise Exception("%s can't give %s to %s under the game's rules (e.g. tech trading needs Alphabet; "
			"open borders need contact and no war...)" % (pname(giver), itemText(it), pname(taker)))

def doItem(giver, taker, it):
	g, t = gc.getPlayer(giver), gc.getPlayer(taker)
	kind, d = it
	if kind == "tech":
		gc.getTeam(t.getTeam()).setHasTech(d, True, taker, False, True)
	elif kind == "gold":
		g.changeGold(-d)
		t.changeGold(d)
	elif kind == "open_borders":
		gc.getTeam(g.getTeam()).signOpenBorders(t.getTeam())
	elif kind == "defensive_pact":
		gc.getTeam(g.getTeam()).signDefensivePact(t.getTeam())
	elif kind == "peace":
		gc.getTeam(g.getTeam()).makePeace(t.getTeam())
	elif kind == "war":
		gc.getTeam(g.getTeam()).declareWar(gc.getPlayer(d).getTeam(), True, WarPlanTypes.WARPLAN_DOGPILE)

def itemValue(owner, it):
	kind, d = it
	if kind == "tech":
		return gc.getTeam(gc.getPlayer(owner).getTeam()).getResearchCost(d)
	if kind == "gold":
		return d
	return 0

def aiAccepts(ai, me, give, get):
	# give = what Claude gives the AI, get = what the AI gives Claude
	p = gc.getPlayer(ai)
	for it in get:
		den = p.getTradeDenial(me, tradeData(it))
		if den != DenialTypes.NO_DENIAL and it[0] != "peace":
			return False, "%s refuses to give %s (%s)" % (pname(ai), itemText(it), gc.getDenialInfo(den).getDescription())
	att = p.AI_getAttitude(me)
	if get and att <= AttitudeTypes.ATTITUDE_ANNOYED:
		return False, "%s is %s toward us and won't deal" % (pname(ai), gc.getAttitudeInfo(att).getDescription())
	vin = sum([itemValue(ai, it) for it in give])
	vout = sum([itemValue(ai, it) for it in get])
	if vout > vin * 1.1 + 10:
		return False, "%s finds it unfair: gives about %d, gets about %d" % (pname(ai), vout, vin)
	return True, "accepted"

def executeDeal(a, b, giveA, giveB):
	for it in giveA:
		checkItem(a, b, it)
	for it in giveB:
		checkItem(b, a, it)
	for it in giveA:
		doItem(a, b, it)
	for it in giveB:
		doItem(b, a, it)
	refreshSnapshot()   # our own deal: not a "native" one

def cmdOffer(args):
	iMe, iTeam = myIds()
	other = findPlayer(args["player"])
	if other == iMe:
		raise Exception("that's us")
	if not gc.getTeam(iTeam).isHasMet(gc.getPlayer(other).getTeam()):
		raise Exception("we haven't met %s" % args["player"])
	give = [parseItem(x) for x in args.get("give") or []]
	get = [parseItem(x) for x in args.get("get") or []]
	if not give and not get:
		raise Exception("an offer needs something to give or to get")
	for it in give:
		checkItem(iMe, other, it)
	for it in get:
		checkItem(other, iMe, it)
	if not get:
		# a gift needs no answer
		executeDeal(iMe, other, give, [])
		writeEvent("deal_done", {"with": pname(other), "gave": [itemText(x) for x in give], "got": []})
		if gc.getPlayer(other).isHuman():
			CyInterface().addMessage(other, True, gc.getEVENT_MESSAGE_TIME() * 3,
				u"<font=4><color=255,200,60,255>%s gives you: %s</color></font>" % (gc.getPlayer(iMe).getName(),
				", ".join([itemText(x) for x in give])), "", InterfaceMessageTypes.MESSAGE_TYPE_MAJOR_EVENT, "", -1, -1, -1, False, False)
		return {"done": True, "gave": [itemText(x) for x in give]}
	if not gc.getPlayer(other).isHuman():
		ok, why = aiAccepts(other, iMe, give, get)
		if not ok:
			writeEvent("deal_refused", {"with": pname(other), "why": why})
			return {"done": False, "why": why}
		executeDeal(iMe, other, give, get)
		writeEvent("deal_done", {"with": pname(other), "gave": [itemText(x) for x in give], "got": [itemText(x) for x in get]})
		return {"done": True, "gave": [itemText(x) for x in give], "got": [itemText(x) for x in get]}
	o = loadOffers()
	n = o["next"]
	o["next"] = n + 1
	o["open"][str(n)] = {"from": iMe, "to": other, "give": [list(x) for x in give], "get": [list(x) for x in get],
		"turn": gc.getGame().getGameTurn()}
	saveOffers(o)
	line = u"<font=4><color=255,200,60,255>%s offers a deal #%d - you get: %s; he gets: %s. Answer in the window (or type !accept %d / !decline %d in chat).</color></font>" % (
		gc.getPlayer(iMe).getName(), n, ", ".join([itemText(x) for x in give]) or "nothing",
		", ".join([itemText(x) for x in get]), n, n)
	CyInterface().addMessage(other, True, gc.getEVENT_MESSAGE_TIME() * 4, line, "",
		InterfaceMessageTypes.MESSAGE_TYPE_MAJOR_EVENT, "", -1, -1, -1, False, False)
	dealPopup(n, iMe, give, get)
	writeEvent("deal_offered", {"id": n, "to": pname(other), "give": [itemText(x) for x in give], "get": [itemText(x) for x in get]})
	return {"offer": n, "waiting_for": pname(other)}

def answerOffer(text, human):
	# "!accept N" / "!decline N" typed by the human in chat
	parts = text.split()
	o = loadOffers()
	n = len(parts) > 1 and parts[1] or ""
	if not o["open"].has_key(n):
		CyInterface().addImmediateMessage(u"No open deal #%s." % n, "")
		return
	d = o["open"][n]
	del o["open"][n]
	saveOffers(o)
	give = [tuple(x) for x in d["give"]]
	get = [tuple(x) for x in d["get"]]
	if parts[0].lower() == "!decline":
		writeEvent("deal_declined", {"id": int(n), "by": pname(human)})
		return
	try:
		executeDeal(d["from"], d["to"], give, get)
	except:
		why = str(sys.exc_info()[1])
		writeEvent("deal_failed", {"id": int(n), "why": why})
		CyInterface().addImmediateMessage(u"Deal #%s can't be done: %s" % (n, why), "")
		return
	writeEvent("deal_done", {"id": int(n), "with": pname(human), "gave": [itemText(x) for x in give], "got": [itemText(x) for x in get]})
	CyInterface().addImmediateMessage(u"Deal #%s done." % n, "")

DEAL_EVENT_ID = 5918

def dealPopup(n, fromPlayer, give, get):
	# the game's own popup window with Accept / Decline buttons (the leader-screen diplomacy
	# itself can't be opened from Python); the answer comes back through dealApply
	import Popup as PyPopup
	p = gc.getPlayer(fromPlayer)
	popup = PyPopup.PyPopup(DEAL_EVENT_ID, EventContextTypes.EVENTCONTEXT_ALL)
	popup.setHeaderString(u"%s proposes a deal (#%d)" % (p.getName(), n))
	try:
		popup.addDDS(gc.getLeaderHeadInfo(p.getLeaderType()).getButton(), 0, 0, 64, 64)
	except:
		pass
	popup.setBodyString(u"You receive: %s\n\n%s receives: %s" % (", ".join([itemText(x) for x in give]) or u"nothing",
		p.getName(), ", ".join([itemText(x) for x in get]) or u"nothing"))
	popup.addButton(u"Accept")
	popup.addButton(u"Decline")
	popup.setUserData((n,))
	popup.launch(False)

def dealApply(playerID, userData, popupReturn):
	n = userData[0]
	verb = u"!decline"
	if popupReturn.getButtonClicked() == 0:
		verb = u"!accept"
	answerOffer(u"%s %d" % (verb, n), playerID)
	return 0

def dealApplyTrampoline(playerID, userData, popupReturn):
	return sys.modules["ClaudeBridge"].dealApply(playerID, userData, popupReturn)

def dealBeginTrampoline(argsList=-1):
	return 0

def cmdOffers(args):
	o = loadOffers()
	return {"open": ["#%s to %s: give %s; get %s" % (k, pname(v["to"]), ", ".join([itemText(tuple(x)) for x in v["give"]]) or "nothing",
		", ".join([itemText(tuple(x)) for x in v["get"]])) for k, v in o["open"].items()]}

def cmdWar(args):
	# Claude's own declaration of war (the built-in AI no longer declares wars for this civ)
	iMe, iTeam = myIds()
	other = gc.getPlayer(findPlayer(args["player"])).getTeam()
	if not gc.getTeam(iTeam).canDeclareWar(other):
		raise Exception("we can't declare war on %s now (peace treaty still running, or not met?)" % args["player"])
	gc.getTeam(iTeam).declareWar(other, True, WarPlanTypes.WARPLAN_TOTAL)
	return {"war_declared_on": gc.getTeam(other).getName()}


def cmdTradeable(args):
	# what each side could put on the table right now -- the same as the game's trade screen
	iMe, iTeam = myIds()
	other = findPlayer(args["player"])
	if not gc.getTeam(iTeam).isHasMet(gc.getPlayer(other).getTeam()):
		raise Exception("we haven't met %s" % args["player"])
	def side(a, b):
		out = []
		pa = gc.getPlayer(a)
		for t in range(gc.getNumTechInfos()):
			try:
				if gc.getTeam(pa.getTeam()).isHasTech(t) and pa.canTradeItem(b, tradeData(("tech", t)), False):
					out.append("tech:" + gc.getTechInfo(t).getDescription())
			except:
				pass
		if pa.getGold() > 0 and pa.canTradeItem(b, tradeData(("gold", 1)), False):
			out.append("gold (up to %d)" % pa.getGold())
		for k in ("open_borders", "defensive_pact"):
			if pa.canTradeItem(b, tradeData((k, -1)), False):
				out.append(k)
		if gc.getTeam(pa.getTeam()).isAtWar(gc.getPlayer(b).getTeam()):
			out.append("peace")
		return out
	d = {"with": pname(other), "we_can_give": side(iMe, other), "they_can_give": side(other, iMe)}
	if not gc.getPlayer(other).isHuman():
		d["their_attitude"] = gc.getAttitudeInfo(gc.getPlayer(other).AI_getAttitude(iMe)).getDescription()
	return d

# ------------------------------------------------------------------------ rules
#
# Game rules straight from the game (exact for this install and mod), so the player
# never has to rely on memory: techs, units, buildings, civics, improvements, resources.

def techList(ids):
	return [gc.getTechInfo(i).getDescription() for i in ids if i >= 0]

def cmdRules(args):
	iMe, iTeam = myIds()
	me, team = gc.getPlayer(iMe), gc.getTeam(iTeam)
	want = args["name"]
	if args.get("path"):
		t = findInfo(want, gc.getNumTechInfos(), gc.getTechInfo, "tech_")
		if t < 0:
			raise Exception("no tech called %s" % want)
		need, seen = [], {}
		def walk(i):
			if i < 0 or seen.has_key(i) or team.isHasTech(i):
				return
			seen[i] = 1
			info = gc.getTechInfo(i)
			for k in range(gc.getNUM_AND_TECH_PREREQS()):
				walk(info.getPrereqAndTechs(k))
			ors = [info.getPrereqOrTechs(k) for k in range(gc.getNUM_OR_TECH_PREREQS()) if info.getPrereqOrTechs(k) >= 0]
			if ors and not [o for o in ors if team.isHasTech(o)]:
				ors.sort(lambda a, b: cmp(team.getResearchCost(a), team.getResearchCost(b)))
				walk(ors[0])   # cheapest way through an "or"
			need.append(i)
		walk(t)
		rate = max(1, me.calculateResearchRate(-1))
		total = sum([team.getResearchCost(i) - team.getResearchProgress(i) for i in need])
		return {"path_to": gc.getTechInfo(t).getDescription(), "techs_in_order": techList(need),
			"beakers": total, "turns_at_current_rate": total / rate + 1}
	i = findInfo(want, gc.getNumTechInfos(), gc.getTechInfo, "tech_")
	if i >= 0:
		info = gc.getTechInfo(i)
		return {"tech": info.getDescription(), "we_have_it": team.isHasTech(i),
			"cost_for_us": team.getResearchCost(i), "turns_for_us": me.getResearchTurnsLeft(i, True),
			"needs_all_of": techList([info.getPrereqAndTechs(k) for k in range(gc.getNUM_AND_TECH_PREREQS())]),
			"needs_one_of": techList([info.getPrereqOrTechs(k) for k in range(gc.getNUM_OR_TECH_PREREQS())]),
			"era": gc.getEraInfo(info.getEra()).getDescription(),
			"units": [gc.getUnitInfo(u).getDescription() for u in range(gc.getNumUnitInfos()) if gc.getUnitInfo(u).getPrereqAndTech() == i],
			"buildings": [gc.getBuildingInfo(b).getDescription() for b in range(gc.getNumBuildingInfos()) if gc.getBuildingInfo(b).getPrereqAndTech() == i],
			"worker_builds": [gc.getBuildInfo(b).getDescription() for b in range(gc.getNumBuildInfos()) if gc.getBuildInfo(b).getTechPrereq() == i],
			"civics": [gc.getCivicInfo(c).getDescription() for c in range(gc.getNumCivicInfos()) if gc.getCivicInfo(c).getTechPrereq() == i],
			"reveals": [gc.getBonusInfo(b).getDescription() for b in range(gc.getNumBonusInfos()) if gc.getBonusInfo(b).getTechReveal() == i],
			"leads_to": [gc.getTechInfo(t).getDescription() for t in range(gc.getNumTechInfos())
				if i in [gc.getTechInfo(t).getPrereqAndTechs(k) for k in range(gc.getNUM_AND_TECH_PREREQS())]
				+ [gc.getTechInfo(t).getPrereqOrTechs(k) for k in range(gc.getNUM_OR_TECH_PREREQS())]],
			"strategy": info.getStrategy()}
	i = findInfo(want, gc.getNumUnitInfos(), gc.getUnitInfo, "unit_")
	if i >= 0:
		info = gc.getUnitInfo(i)
		bonuses = []
		if info.getPrereqAndBonus() >= 0:
			bonuses = [gc.getBonusInfo(info.getPrereqAndBonus()).getDescription()]
		orb = [gc.getBonusInfo(info.getPrereqOrBonuses(k)).getDescription() for k in range(gc.getNUM_UNIT_PREREQ_OR_BONUSES()) if info.getPrereqOrBonuses(k) >= 0]
		return {"unit": info.getDescription(), "strength": info.getCombat(), "moves_per_turn": info.getMoves(),
			"cost": me.getUnitProductionNeeded(i), "needs_techs": techList([info.getPrereqAndTech()] +
				[info.getPrereqAndTechs(k) for k in range(gc.getNUM_UNIT_AND_TECH_PREREQS())]),
			"needs_resource": bonuses, "needs_one_resource_of": orb,
			"we_can_build_it": me.canTrain(i, False, False), "strategy": info.getStrategy(), "help": info.getHelp()}
	i = findInfo(want, gc.getNumBuildingInfos(), gc.getBuildingInfo, "building_")
	if i >= 0:
		info = gc.getBuildingInfo(i)
		return {"building": info.getDescription(), "cost": me.getBuildingProductionNeeded(i),
			"needs_tech": techList([info.getPrereqAndTech()]), "obsolete_with": techList([info.getObsoleteTech()]),
			"happiness": info.getHappiness(), "health": info.getHealth(), "strategy": info.getStrategy(), "help": info.getHelp()}
	i = findInfo(want, gc.getNumCivicInfos(), gc.getCivicInfo, "civic_")
	if i >= 0:
		info = gc.getCivicInfo(i)
		upkeep = "none"
		if info.getUpkeep() >= 0:
			upkeep = gc.getUpkeepInfo(info.getUpkeep()).getDescription()
		return {"civic": info.getDescription(), "category": gc.getCivicOptionInfo(info.getCivicOptionType()).getDescription(),
			"needs_tech": techList([info.getTechPrereq()]), "upkeep": upkeep,
			"we_can_adopt": me.canDoCivics(i), "strategy": info.getStrategy(), "help": info.getHelp()}
	i = findInfo(want, gc.getNumBuildInfos(), gc.getBuildInfo, "build_")
	if i >= 0:
		info = gc.getBuildInfo(i)
		return {"worker_build": info.getDescription(), "needs_tech": techList([info.getTechPrereq()]), "turns_of_work": info.getTime() / 100}
	i = findInfo(want, gc.getNumBonusInfos(), gc.getBonusInfo, "bonus_")
	if i >= 0:
		info = gc.getBonusInfo(i)
		return {"resource": info.getDescription(), "revealed_by": techList([info.getTechReveal()]),
			"usable_with": techList([info.getTechCityTrade()]), "happiness": info.getHappiness(), "health": info.getHealth(),
			"we_have_it": me.getNumAvailableBonuses(i)}
	raise Exception("nothing called %s among techs, units, buildings, civics, worker builds, resources" % want)

def aiDoDiplo(gu, argsList):
	if argsList[0] == getClaudePlayer():
		return True
	return gu._claudeOrigDoDiplo(argsList)

def aiDoWar(gu, argsList):
	if argsList[0] == gc.getPlayer(getClaudePlayer()).getTeam():
		return True
	return gu._claudeOrigDoWar(argsList)

def doDiploTrampoline(argsList):
	import CvGameInterfaceFile
	return sys.modules["ClaudeBridge"].aiDoDiplo(CvGameInterfaceFile.GameUtils, argsList)

def doWarTrampoline(argsList):
	import CvGameInterfaceFile
	return sys.modules["ClaudeBridge"].aiDoWar(CvGameInterfaceFile.GameUtils, argsList)

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
	# {"owner:cityID": [[orderType, data], ...]} -- Claude's queue for each city it manages
	if not os.path.exists(CITY_CLAIMS_FILE):
		return {}
	f = open(CITY_CLAIMS_FILE, "rb")
	try:
		d = fromJson(f.read()) or {}
	finally:
		f.close()
	if isinstance(d, list):   # older format: just the keys
		d = dict([(k, []) for k in d])
	return d

def saveCityClaims(d):
	writeAtomic(CITY_CLAIMS_FILE, toJson(d))

def cityKey(c):
	return "%d:%d" % (c.getOwner(), c.getID())

def claimCity(c):
	# remember the city's whole queue as Claude set it
	d = loadCityClaims()
	d[cityKey(c)] = [[int(c.getOrderFromQueue(k).eOrderType), c.getOrderFromQueue(k).iData1]
		for k in range(c.getOrderQueueLength())]
	saveCityClaims(d)

def cityItemDone(c, order, data):
	# an item finished: drop it from the remembered queue
	d = loadCityClaims()
	q = d.get(cityKey(c))
	if q and q[0][0] == int(order) and q[0][1] == data:
		q.pop(0)
		saveCityClaims(d)

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


def cmdHurry(args):
	# the game's Hurry button: whip (population) or buy (gold), whatever our civics allow.
	# Without "how", it only shows the options and their price.
	iMe, iTeam = myIds()
	c = findCity(args)
	if c.getOwner() != iMe:
		raise Exception("%s is not our city" % c.getName())
	opts = []
	for h in range(gc.getNumHurryInfos()):
		info = gc.getHurryInfo(h)
		if c.canHurry(HurryTypes(h), False):
			opts.append((info.getType()[len("HURRY_"):].lower(), h, c.hurryPopulation(h), c.hurryGold(h),
				c.hurryAngerLength(h)))
	if c.getOrderQueueLength() == 0:
		raise Exception("%s is building nothing" % c.getName())
	building = orderName(c.getOrderFromQueue(0))
	if not args.get("how"):
		return {"city": c.getName(), "building": building, "turns_left": c.getProductionTurnsLeft(),
			"can_hurry": ["%s: costs %d population and %d gold, unhappiness for %d turns" % (n, pop, gold, anger)
				for (n, h, pop, gold, anger) in opts] or ["no (civics, or nothing that can be hurried)"]}
	want = args["how"].lower()
	m = [o for o in opts if o[0] == want or (want == "whip" and o[2] > 0) or (want in ("buy", "gold") and o[2] == 0 and o[3] > 0)]
	if not m:
		raise Exception("%s can't hurry by %s now. Options: %s" % (c.getName(), want, ", ".join([o[0] for o in opts]) or "none"))
	n, h, pop, gold, anger = m[0]
	c.hurry(HurryTypes(h))
	writeEvent("hurried", {"city": c.getName(), "item": building, "population": pop, "gold": gold})
	return {"city": c.getName(), "hurried": building, "paid_population": pop, "paid_gold": gold,
		"finishes": "at the start of our next turn"}

def aiChooseProduction(gu, argsList):
	# the game clears a city's queue before asking us, so we put Claude's remaining
	# items back; only when Claude's queue is used up does the built-in AI choose
	c = argsList[0]
	q = loadCityClaims().get(cityKey(c))
	if q:
		if c.getOrderQueueLength() == 0:
			for (order, data) in q:
				c.pushOrder(OrderTypes(order), data, -1, False, False, True, False)
		if c.getOrderQueueLength() > 0:
			return True
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
	"great_person", "golden_age", "unit_arrived", "unit_done", "deal_done", "deal_declined", "deal_failed", "native_deal", "ai_change_undone")

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

def cmdExecGuard(args, req):
	# civ py sees everything: only requests marked as coming from the director (CIV_DEV=1) run it
	if not req.get("dev"):
		writeEvent("exec_refused", {"code": (args.get("code") or "")[:200]})
		raise Exception("civ py is for the director only (game sessions use civ research/build/do/offer/rules/...)")

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
	"area": cmdArea,
	"actions": cmdActions,
	"offer": cmdOffer,
	"offers": cmdOffers,
	"tradeable": cmdTradeable,
	"religion": cmdReligion,
	"civics": cmdCivics,
	"rules": cmdRules,
	"war": cmdWar,
	"do": cmdDo,
	"build": cmdBuild,
	"hurry": cmdHurry,
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
		if cmd == "exec":
			cmdExecGuard(req.get("args") or {}, req)
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
		if gameReady():
			try:
				guardChoices()
			except:
				log("choices guard FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
			try:
				checkNativeDeal()
			except:
				log("native deal check FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
		names = [n for n in os.listdir(IN_DIR) if n.endswith(".json")]
		names.sort()
		for n in names:
			handleRequest(n)
	except:
		log("poll FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
