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
import re

gc = CyGlobalContext()

BRIDGE_VERSION = 172
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
	for attempt in range(5):
		# under Wine a rename can fail for a moment (a reader holding the file): try again, then write in place
		try:
			if os.path.exists(path):
				os.remove(path)
			os.rename(tmp, path)
			return
		except OSError:
			time.sleep(0.05)
	f = open(path, "wb")
	try:
		f.write(text)
	finally:
		f.close()
	try:
		os.remove(tmp)
	except OSError:
		pass

def infoType(getter, i):
	if i < 0:
		return None
	return getter(i).getType()


# ------------------------------------------------------------ who is Claude

g_acting = [None]   # player a request acts for ("player" in the request), else the default

def configValue(key):
	try:
		if os.path.exists(CONFIG_FILE):
			f = open(CONFIG_FILE, "r")
			try:
				for line in f.readlines():
					if "=" in line and line.split("=")[0].strip() == key:
						return line.split("=", 1)[1].strip()
			finally:
				f.close()
	except:
		pass
	return None

def multiAgent():
	return (configValue("multi") or "").lower() in ("yes", "1", "true")

# ------------------------------------------------------------ seats (several agents in one game)
#
# config.txt "players = 1,2,3": each agent civ is a seat with its own files in claude_bridge\p<N>
# (events, chat, gate, proposals, offers, claims...). Every request and every game event is handled
# once per seat with that seat's files swapped in, so the code below only ever sees its own player.
# Without "players" (one agent, the original layout) the files stay in claude_bridge itself.
SEAT_FILES = ("EVENTS_FILE", "CLAIMS_FILE", "CHAT_FILE", "CHOICES_FILE", "SEAL_FILE", "OFFERS_FILE",
	"PROPOSALS_FILE", "CITY_CLAIMS_FILE", "GATE_FILE")
g_seatBase = {}

def seatsConfigured():
	return bool(configValue("players"))

def modelPlayers():
	# config "players = auto": the human picked, in the game, which AI plays each leader (models.json, see askModels)
	d = loadModels()
	return [int(k) for k in d.keys() if k.isdigit() and d[k] != "builtin"]

def agentPlayers():
	v = configValue("players")
	if v and v.strip() == "auto":
		return modelPlayers()
	if v:
		return [int(x) for x in v.split(",") if x.strip()]
	p = getClaudePlayer()
	return p >= 0 and [p] or []

def seatDir(p):
	if p is None or not seatsConfigured():
		return OUT_DIR
	return OUT_DIR + "\\p%d" % p

def actAs(p):
	# swap in player p's files (None: the default seat); returns the previous player
	if not g_seatBase:
		for name in SEAT_FILES:
			g_seatBase[name] = globals()[name].split("\\")[-1]
	prev = g_acting[0]
	g_acting[0] = p
	d = seatDir(p)
	if d != OUT_DIR and not os.path.isdir(d):
		os.makedirs(d)
	for name, base in g_seatBase.items():
		globals()[name] = d + "\\" + base
	return prev

def forEachSeat(fn, *args):
	# run fn once per agent civ, each time with that seat's files
	for p in agentPlayers():
		prev = actAs(p)
		try:
			fn(*args)
		finally:
			actAs(prev)

def isAgent(i):
	# another agent's civ in a game of several agents (it answers offers itself)
	return seatsConfigured() and i in agentPlayers()

def getClaudePlayer():
	# the request's own player if it names one; else config.txt "player = N";
	# otherwise the first living AI civ
	if g_acting[0] is not None:
		return g_acting[0]
	if seatsConfigured():
		return -1   # several agents: only a seat's own context has a "me" (asSeatOf, forEachSeat, a request)
	try:
		v = configValue("player")
		if v is not None:
			return int(v)
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
			d["name"] = realName(i)
			d["civ"] = p.getCivilizationShortDescription(0)
			d["leader"] = infoType(gc.getLeaderHeadInfo, p.getLeaderType())
			d["human"] = p.isHuman()
			# who you are dealing with: a leader who reads your messages and may answer in words, or the
			# game's own AI, which answers only deals and demands (no names of models: the game doesn't show them)
			if isAgent(i) or p.isHuman():
				d["played_by"] = "a leader who reads your messages (civ say) and can answer in words"
			else:
				d["played_by"] = "the game's built-in AI: it never reads messages; it answers deals and demands only"
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
		# the finance advisor's numbers (what a human sees there)
		"finances": {"income": p.getCommerceRate(CommerceTypes.COMMERCE_GOLD), "cities": p.getTotalMaintenance(),
			"civics": p.getCivicUpkeep([], False), "units": p.calculateUnitCost(), "unit_supply": p.calculateUnitSupply(),
			"inflation": p.calculateInflatedCosts() - p.calculatePreInflatedCosts()},
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
				riverEdges(pl),
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

def riverEdges(pl):
	# which of the 8 directions cross a river from this tile (bit d = DirectionTypes d; attacking across costs 25%)
	if not pl.isRiver():
		return 0
	m = 0
	for d in range(8):
		if pl.isRiverCrossing(DirectionTypes(d)):
			m = m | (1 << d)
	return m

TIMELINE_FILE = OUT_DIR + "\\timeline.json"

def rewindCheck():
	# a save was loaded. A save holds the start of its turn, so loading the same turn again also throws away
	# what happened in it since: orders, build lists, questions and log lines of this turn and later never
	# happened in the game being played now (only a later save loses nothing)
	now = gc.getGame().getGameTurn()
	last = -1
	if os.path.exists(TIMELINE_FILE):
		f = open(TIMELINE_FILE, "rb")
		try:
			last = int(fromJson(f.read()).get("turn", -1))
		finally:
			f.close()
	writeAtomic(TIMELINE_FILE, toJson({"turn": now}))
	if last < now:
		return
	if seatsConfigured():
		forEachSeat(rewindSeat, last, now)
	else:
		rewindSeat(last, now)

def rewindSeat(last, now):
	c = loadClaims()
	for k in c.keys():
		c[k]["target"] = None
		c[k]["mission"] = None
		c[k]["busy"] = False
	saveClaims(c)
	p = gc.getPlayer(getClaudePlayer())
	d = loadCityClaims()
	(cy, it) = p.firstCity(False)
	while cy and not cy.isNone():
		if d.has_key(cityKey(cy)):
			d[cityKey(cy)] = [[int(cy.getOrderFromQueue(i).eOrderType), cy.getOrderFromQueue(i).iData1] for i in range(cy.getOrderQueueLength())]
		(cy, it) = p.nextCity(it, False)
	saveCityClaims(d)
	o = loadProposals()
	for k in o["open"].keys():
		closeNote(o, k, "a reload went back to the start of turn %d, before it was made" % now)
	o["open"] = {}
	saveProposals(o)
	# the logs are append-only: these markers tell every reader that the later turns logged before them never happened
	wall = time.strftime("%Y-%m-%d %H:%M:%S")
	ensureDir()
	f = open(CHAT_FILE, "ab")
	try:
		f.write(toJson({"from": "system", "rewind_to": now, "turn": now, "text": "", "time": time.strftime("%H:%M:%S")}) + "\n")
	finally:
		f.close()
	writeEvent("rewind", {"from_turn": last, "to_turn": now, "wall": wall, "note": "a save from the start of turn %d was "
		"loaded: what happened from then on (orders, builds, units made, open questions) did not happen in this game; "
		"your memory files may describe it" % now})

def dump(reason):
	if reason == "load_game":
		# a loaded save is a new starting point: nothing in it is a deal made since the last look
		g_snap.d.clear()   # every seat's
		g_window.d.clear()
		try:
			rewindCheck()
		except:
			log("rewind check FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
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
			"improvement", "route", "river", "visible", "river_crossings"],
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
			"land": u.plot().getRevealedOwner(p.getTeam(), False),
			"moves": u.movesLeft(), "max_moves": u.maxMoves(),
			"damage": u.getDamage(),
			"level": u.getLevel(), "xp": u.getExperience(),
			"group": u.getGroupID(),
			"automated": u.isAutomated(),
			"fortified": u.getFortifyTurns() > 0,
			"waiting": u.isWaiting(),
			"missions_queued": g.getLengthMissionQueue(),
			"job": jobText(u),
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
		"foreign_seen": collectForeignSeen(iMe),
	}

def collectForeignSeen(iMe):
	# every foreign unit we see now (fog of war applies): inside our borders, near them, or elsewhere
	iTeam = gc.getPlayer(iMe).getTeam()
	m = CyMap()
	groups = {}
	for i in range(m.numPlots()):
		pl = m.plotByIndex(i)
		if not pl.isVisible(iTeam, False) or pl.getNumUnits() == 0:
			continue
		land = pl.getRevealedOwner(iTeam, False)
		if land == iMe:
			where = "inside"
		else:
			where = "elsewhere"
			for dx in range(-2, 3):
				for dy in range(-2, 3):
					q = m.plot(pl.getX() + dx, pl.getY() + dy)
					if q is not None and not q.isNone() and q.getRevealedOwner(iTeam, False) == iMe:
						where = "near"
		for k in range(pl.getNumUnits()):
			u = pl.getUnit(k)
			if u.isNone() or u.getOwner() == iMe or u.isInvisible(iTeam, False):
				continue
			key = (u.getOwner(), pl.getX(), pl.getY(), where, land)
			groups.setdefault(key, []).append(gc.getUnitInfo(u.getUnitType()).getDescription())
	out = []
	for (o, x, y, where, land), names in groups.items():
		out.append({"owner": o, "who": pname(o), "x": x, "y": y, "where": where, "land": land,
			"units": names, "war": gc.getTeam(iTeam).isAtWar(gc.getPlayer(o).getTeam())})
	return out

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
	else:
		d.update(unitLooks(u))
	return d

def unitLooks(u):
	# what a human sees hovering a unit: health bar, strength, promotions
	d = {"health": "%d%%" % (100 * (u.maxHitPoints() - u.getDamage()) / max(1, u.maxHitPoints())),
		"strength": "%g" % (u.baseCombatStr() * (u.maxHitPoints() - u.getDamage()) / float(max(1, u.maxHitPoints()))) + "/%d" % u.baseCombatStr()}
	promos = [gc.getPromotionInfo(k).getDescription() for k in range(gc.getNumPromotionInfos()) if u.isHasPromotion(k)]
	if promos:
		d["promotions"] = promos
	if u.getFortifyTurns() > 0:
		d["fortified"] = True
	return d

def cmdOdds(args):
	# the odds the game shows a human hovering an attack: our unit against the tile's best defender
	iMe, iTeam = myIds()
	me = gc.getPlayer(iMe)
	x, y = int(args["x"]), int(args["y"])
	pl = CyMap().plot(x, y)
	if pl is None or pl.isNone() or not pl.isVisible(iTeam, False):
		raise Exception("we can't see the tile %d,%d" % (x, y))
	if args.get("id") is not None:
		u = me.getUnit(int(args["id"]))
		if u is None or u.isNone():
			raise Exception("no unit of ours with id %s" % args["id"])
		attackers = [u]
	else:
		attackers = []
		(u, it) = me.firstUnit(False)
		while u and not u.isNone():
			if u.canAttack() and plotDistance(u.getX(), u.getY(), x, y) <= max(1, u.maxMoves() / gc.getMOVE_DENOMINATOR()):
				attackers.append(u)
			(u, it) = me.nextUnit(it, False)
	out = []
	for u in attackers:
		dfd = pl.getBestDefender(-1, iMe, u, True, False, False)
		row = {"unit": "#%d %s" % (u.getID(), gc.getUnitInfo(u.getUnitType()).getDescription()),
			"from": "%d,%d" % (u.getX(), u.getY()),
			"my_health": "%d%%" % (100 * (u.maxHitPoints() - u.getDamage()) / max(1, u.maxHitPoints()))}
		dist = plotDistance(u.getX(), u.getY(), x, y)
		if dist > 1:
			# the game shows odds only for an attack on a tile next to the unit
			row["reach"] = ("%d tiles away: no attack from where it stands. It must first walk next to the target; these "
				"odds are for the fight once there, and enemy units on the way (some not seen now) are fought first") % dist
		if dfd is None or dfd.isNone():
			row["defender"] = "none we can fight there"
		else:
			row["defender"] = "%s of %s" % (gc.getUnitInfo(dfd.getUnitType()).getDescription(), pname(dfd.getOwner()))
			row["defender_looks"] = unitLooks(dfd)
			row["win_odds"] = "%.1f%%" % (getCombatOdds(u, dfd) / 10.0)
			if u.withdrawalProbability() > 0:
				row["withdraw_chance"] = "%d%% (if it would lose)" % u.withdrawalProbability()
			if u.collateralDamage() > 0:
				row["collateral"] = "hits up to %d other units there" % u.collateralDamageMaxUnits()
		out.append(row)
	return {"target": "%d,%d" % (x, y), "attacks": out,
		"note": "the same odds the game shows a human hovering the attack, from where each unit stands now"}

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
	d["ground"] = "%s%s" % (gc.getTerrainInfo(pl.getTerrainType()).getDescription(),
		{0: " peak", 1: " hills", 2: " flat", 3: " water"}.get(int(pl.getPlotType()), ""))
	if pl.isRiver():
		d["ground"] += ", by a river"
	if c.getOwner() != iMe:
		d["in_sight_now"] = pl.isVisible(iTeam, False)
		if not d["in_sight_now"]:
			d["note"] = "out of sight: no unit of ours sees it now, so its garrison and defense are unknown"
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
		"food_note": c.isFoodProduction() and ("while it builds a %s, its food surplus (%+d) goes into production "
			"(the game's rule for settlers and workers): the city doesn't grow, and a food tile adds hammers"
			% (c.getProductionName(), c.getYieldRate(YieldTypes.YIELD_FOOD) - c.foodConsumption(False, 0))) or None,
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
		"can_create_projects": [gc.getProjectInfo(i).getDescription() for i in range(gc.getNumProjectInfos()) if c.canCreate(i, False, False)],
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
	d["trade_routes"] = tradeRoutes(c, iMe)
	return d

def tradeRoutes(c, iMe):
	# the city screen's trade routes: where each goes and the commerce it brings (foreign ones are what
	# Mercantilism and an embargo would cut)
	out = []
	for i in range(c.getTradeRoutes()):
		t = c.getTradeCity(i)
		if t is None or t.isNone():
			continue
		gain = c.calculateTradeYield(YieldTypes.YIELD_COMMERCE, c.calculateTradeProfit(t))
		owner = t.getOwner() == iMe and "ours" or pname(t.getOwner())
		out.append("%s (%s): +%d commerce" % (t.getName(), owner, gain))
	return out or ["none"]

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
		if want is not None and (str(i) == str(want) or realName(i).lower() == w
				or p.getCivilizationShortDescription(0).lower() == w
				or (len(w) >= 3 and (realName(i).lower().startswith(w)
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

def realName(i):
	# the leader's own name: what every seat reads. The screen may show another name for the player (its model,
	# set with claudeSetName for the video), which the seats must not learn
	p = gc.getPlayer(i)
	if p.isHuman() or p.getLeaderType() < 0:
		return p.getName()
	return gc.getLeaderHeadInfo(p.getLeaderType()).getDescription()

def teamName(t):
	return realName(gc.getTeam(t).getLeaderID())

def pname(i):
	iMe, iTeam = myIds()
	if i < 0:
		return "nobody"
	p = gc.getPlayer(i)
	if i == iMe or gc.getTeam(iTeam).isHasMet(p.getTeam()):
		return realName(i) + " (" + p.getCivilizationShortDescription(0) + ")"
	return "an unknown civilization"

def readEventTail(kind, names):
	# is the same first contact already among this seat's last events?
	try:
		f = open(EVENTS_FILE, "rb")
		try:
			tail = f.readlines()[-20:]
		finally:
			f.close()
	except:
		return False
	for line in tail:
		if ('"%s"' % kind) in line and fromJson(line).get("with") == names:
			return True
	return False

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

def humanAddressee(word):
	# the leader a human's "@word" names: a prefix of any word of his leader name, civ name or screen (model) name
	w = word.lower().strip(u",:.!?")
	if not w:
		return None
	for i in range(gc.getMAX_CIV_PLAYERS()):
		p = gc.getPlayer(i)
		if not p.isEverAlive() or p.isHuman():
			continue
		names = [realName(i), p.getName(), p.getCivilizationShortDescription(0), p.getCivilizationAdjective(0)]
		for n in names:
			for token in (u"%s" % n).lower().replace(u"(", u" ").replace(u")", u" ").split():
				if token.startswith(w):
					return i
	return None

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
		# "@name text": a private line from the human to one leader (by leader, civ or model name, a prefix is
		# enough: @genghis, @mongol, @opus); the other seats never get it
		private = False
		if text.startswith(u"@"):
			parts = text[1:].split(None, 1)
			to = parts and humanAddressee(parts[0]) or None
			if to is not None:
				if to != iMe:
					return
				text, private = (len(parts) > 1 and parts[1] or u""), True
		writeChat("player", text)
		if text.strip().lower() == u"!go":
			setReady("player")
			CyInterface().addImmediateMessage(u"Turn unlocked by you (!go).", "")
		elif text.strip().lower().startswith(u"!accept") or text.strip().lower().startswith(u"!decline"):
			human = humanPlayers()
			answerOffer(text.strip(), human and human[0] or 0)
		else:
			writeEvent("message_from_player", {"text": text, "via": "chat", "private": private})
	elif tag == "BeginPlayerTurn":
		# deals other leaders made with our civ during the turn that just ended
		w = ("pre", a[1])
		if a[1] == iMe:
			w = ("own", a[1])
		try:
			checkpoint(w)
		except:
			log("deal checkpoint FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
		g_turnOf[0] = a[1]
		g_guardDue[0] = True
		if a[1] == iMe:
			writeAtomic(TIMELINE_FILE, toJson({"turn": gc.getGame().getGameTurn()}))   # undo what the last window changed before Claude looks at anything
		if a[1] == iMe:
			snapCities(gc.getPlayer(iMe))
			snapUnits(gc.getPlayer(iMe))
			if engineControl():
				expireProposals()
			writeEvent("my_turn_begins", {})
		elif gc.getPlayer(a[1]).isHuman():
			# fired before the game turn counter moves on: the player is about to play turn a[0] + 1
			writeEvent("player_turn_begins", {"gate": readGate().get("on", False), "turn": a[0] + 1})
			autoReadyOrWake(a[0] + 1)
	elif tag == "BeginGameTurn" and seatsConfigured():
		seatTurnStart(a[0] + 1)   # reported before the turn counter moves on
	elif tag == "firstContact" and iTeam in (a[0], a[1]):
		other = a[1]
		if other == iTeam:
			other = a[0]
		# the game reports a contact before it marks the teams as met, so name them directly (they've just met)
		names = ["%s (%s)" % (realName(i), gc.getPlayer(i).getCivilizationShortDescription(0))
			for i in range(gc.getMAX_CIV_PLAYERS()) if gc.getPlayer(i).isAlive() and gc.getPlayer(i).getTeam() == other]
		if names and readEventTail("first_contact", names):
			return   # reported twice (each side meets the other)
		writeEvent("first_contact", {"with": names})
	elif tag == "cityBuilt":
		c = a[0]
		if c.getOwner() == iMe or c.plot().isRevealed(iTeam, False):
			writeEvent("city_founded", {"name": c.getName(), "owner": pname(c.getOwner()), "x": c.getX(), "y": c.getY()})
	elif tag == "improvementBuilt":
		# a worker's job finished on our land: the farm, mine or cottage is there now
		pl = CyMap().plot(a[1], a[2])
		if not pl.isNone() and pl.getOwner() == iMe and a[0] >= 0:
			writeEvent("improvement_built", {"improvement": gc.getImprovementInfo(a[0]).getDescription(), "x": a[1], "y": a[2]})
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
		claimKeyUnit(a[1])
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
			writeEvent(kind, {"team": teamName(t1), "against": teamName(t2)})
	elif tag == "claudeDiplomacy":
		frm, to, comment, data, gives, wants = engineArgs(a)
		if to == iMe:
			newProposal(frm, commentName(comment), data, fromEngineText(gives), fromEngineText(wants))
	elif tag == "claudeEvent":
		me, trig, ttype, ids, text, options = engineArgs(a)
		if me == iMe:
			opts = []
			for line in (u"%s" % options).split(u"\n"):
				line = stripTags(line).strip()
				if not line:
					continue
				if re.match(u"^\\d+: ", line) or not opts:
					opts.append(line)
				else:
					opts[-1] = opts[-1] + u"; " + line   # an option's effects stay with it
			newChoice("event", trig, stripTags(u"%s" % text) or gc.getEventTriggerInfo(ttype).getType(), opts)
	elif tag == "claudeFreeTech":
		if engineArgs(a)[0] == iMe:
			newChoice("free_tech", 0, "Oracle, a first-to-discover bonus or the like", [])
	elif tag == "claudeElection":
		me, selId, source, options = engineArgs(a)
		if me == iMe:
			newElection(me, selId, source, u"%s" % options)
	elif tag == "claudeVote":
		me, voteId, source, vote, player, cityId, other, text = engineArgs(a)
		if me == iMe:
			newVote(me, voteId, source, vote, player, cityId, other, u"%s" % text)
	elif tag == "claudeOffered":
		frm, to, change, gives, wants = engineArgs(a)
		if to == iMe:
			newProposal(frm, "screen_offer", change, fromEngineText(gives), fromEngineText(wants))
	elif tag == "cityHurry" and engineControl():
		pass
	elif tag == "cityHurry" and a[0].getOwner() == iMe and g_window[0] == ("own", iMe):
		undoHurry(a[0], int(a[1]))
	elif tag == "unitKilled" and a[0].getOwner() == iMe:
		g_killed[a[0].getID()] = True   # a real death (combat, capture); the game reports it only then
	elif tag == "unitLost" and a[0].getOwner() == iMe and engineControl():
		u = a[0]
		if g_killed.has_key(u.getID()):
			del g_killed[u.getID()]
		elif g_window[0] == ("own", iMe):
			# gone in our own between-turns processing with nobody killing it: unpaid units deserting
			writeEvent("unit_disbanded", {"unit": gc.getUnitInfo(u.getUnitType()).getDescription(), "id": u.getID(),
				"why": "lost at turn end: the treasury was empty and unpaid units desert (the game's rule)"})
	elif tag == "unitLost" and a[0].getOwner() == iMe:
		unitGone(a[0])
	elif tag == "greatPersonBorn" and a[1] == iMe:
		writeEvent("great_person", {"unit": gc.getUnitInfo(a[0].getUnitType()).getType(), "city": a[2].getName(),
			"id": a[0].getID()})
		claimKeyUnit(a[0])
	elif tag == "goldenAge" and a[0] == iMe:
		writeEvent("golden_age", {})
	elif tag == "goodyReceived" and a[0] == iMe:
		writeEvent("goody_hut", {"goody": gc.getGoodyInfo(a[3]).getType()})
	elif tag == "cultureExpansion" and a[0].getOwner() == iMe:
		writeEvent("borders_expanded", {"city": a[0].getName()})

def writeTruth(turn):
	# the director's record of every civ each turn (for the paper and the video); no agent can read it
	rows = []
	for i in range(gc.getMAX_CIV_PLAYERS()):
		p = gc.getPlayer(i)
		if not p.isEverAlive():
			continue
		t = gc.getTeam(p.getTeam())
		units, mil = 0, 0
		(u, it) = p.firstUnit(False)
		while u and not u.isNone():
			units = units + 1
			if u.canAttack():
				mil = mil + 1
			(u, it) = p.nextUnit(it, False)
		rows.append({"id": i, "name": realName(i), "civ": p.getCivilizationShortDescription(0), "alive": p.isAlive(),
			"agent": isAgent(i), "human": p.isHuman(), "score": gc.getGame().getPlayerScore(i), "cities": p.getNumCities(),
			"pop": p.getTotalPopulation(), "units": units, "military": mil, "gold": p.getGold(),
			"techs": len([k for k in range(gc.getNumTechInfos()) if t.isHasTech(k)]), "era": gc.getEraInfo(p.getCurrentEra()).getType(),
			"religion": p.getStateReligion(), "war": [j for j in range(gc.getMAX_CIV_TEAMS()) if j != p.getTeam() and t.isAtWar(j)],
			"met": [j for j in range(gc.getMAX_CIV_TEAMS()) if j != p.getTeam() and t.isHasMet(j)]})
	appendLine(OUT_DIR + "\\truth.jsonl", {"turn": turn, "year": gc.getGame().getTurnYear(turn),
		"time": time.strftime("%Y-%m-%d %H:%M:%S"), "civs": rows})

# The director's camera (the screen is for the recording only; no agent reads it). In a game of AI seats
# watched by a defeated spectator: the whole map once (debug view, needs the game's cheat code), then the
# camera goes to the newest news, at most every few seconds; a quiet turn shows the next AI leader's capital.
CAMERA_KINDS = {"cityAcquired": 3, "cityRazed": 3, "combatResult": 2, "cityBuilt": 1}
g_camera = {"at": 0.0, "prio": 0, "debug_tried": False, "turn_news": False, "next_seat": 0}

def spectating():
	if not seatsConfigured():
		return False
	a = gc.getGame().getActivePlayer()
	if a < 0:
		return False   # a save is still loading
	return not gc.getPlayer(a).isAlive() and not agentPlayers().count(a)

def camClock():
	# seconds for the camera's timing: in the game (under Wine) time.time() moves in 128 s steps, time.clock() doesn't
	return time.clock()

def cameraTo(x, y, prio):
	now = camClock()
	if prio < g_camera["prio"]:
		return   # this turn already showed bigger news
	plot = gc.getMap().plot(x, y)
	if plot.isNone():
		return
	CyCamera().JustLookAtPlot(plot)
	g_camera["at"], g_camera["prio"], g_camera["turn_news"] = now, prio, True
	pushIn(plot, EVENT_HOLD)

# Each leader's turn as it ends: what it did (moves, builds, messages, offers) and how long it took, shown when it
# says ready, at the place it acted most (the screen only; nothing here reaches a seat)
RECAP_SECONDS = 6
g_acts = {}
g_recap = []

def noteAct(kind, data):
	i = getClaudePlayer()
	a = g_acts.get(i)
	if a is None or a["turn"] != gc.getGame().getGameTurn():
		a = g_acts[i] = {"turn": gc.getGame().getGameTurn(), "t0": camClock(), "moves": [], "builds": [], "say": 0, "offer": 0}
	if kind == "move":
		a["moves"].append(data)
	elif kind == "build":
		a["builds"].append(data)
	else:
		a[kind] = a[kind] + 1

def queueRecap(i):
	a = g_acts.get(i) or {"turn": gc.getGame().getGameTurn(), "t0": None, "moves": [], "builds": [], "say": 0, "offer": 0}
	if [r for r in g_recap if r[0] == i]:
		return
	g_recap.append((i, a, camClock()))

def showRecap(now):
	# from the cameraman: the oldest waiting recap (a stale one, over a minute old, is dropped)
	while g_recap and now - g_recap[0][2] > 60:
		g_recap.pop(0)
	if not g_recap:
		return False
	i, a, at = g_recap.pop(0)
	p = gc.getPlayer(i)
	if not p.isAlive():
		return False
	m = gc.getMap()
	spots = {}
	for (x, y) in a["moves"]:
		spots[(x, y)] = spots.get((x, y), 0) + 2
	for (x, y, what) in a["builds"]:
		spots[(x, y)] = spots.get((x, y), 0) + 1
	if spots:
		x, y = sorted(spots.items(), key=lambda kv: -kv[1])[0][0]
		plot = m.plot(x, y)
	else:
		c = p.getCapitalCity()
		if not c or c.isNone():
			return False
		plot = c.plot()
	did = []
	if a["moves"]:
		did.append("%d unit order%s" % (len(a["moves"]), len(a["moves"]) > 1 and "s" or ""))
	if a["builds"]:
		did.append("builds " + a["builds"][-1][2] + (len(a["builds"]) > 1 and " (+%d)" % (len(a["builds"]) - 1) or ""))
	if a["say"]:
		did.append("%d message%s" % (a["say"], a["say"] > 1 and "s" or ""))
	if a["offer"]:
		did.append("%d offer%s" % (a["offer"], a["offer"] > 1 and "s" or ""))
	took = a.get("t0") is not None and " in %d s" % max(1, int(at - a["t0"])) or ""
	who = p.getName() != realName(i) and u"%s \u00b7 %s" % (p.getName(), realName(i)) or realName(i)
	caption(u"%s ends turn %d%s: %s" % (who, a["turn"], took, did and ", ".join(did) or "no orders"))
	cam = CyCamera()
	cam.JustLookAtPlot(plot)
	cam.SetZoom(0.55)
	glide(plot, plot, 0.55, 0.53, RECAP_SECONDS)
	shotLabel([i])
	g_camera["until"] = now + RECAP_SECONDS
	return True

MOVE_WATCH_GAP = 8      # seconds: the camera follows at most one army move this often (an attack always)

def watchMove(u, target, attack):
	# the filmed screen sees armies move: an attack, or soldiers heading for a civ their owner is at war with or
	# into foreign land, puts the camera on the unit as the order is given, so the walk and the fight play on screen
	if not spectating() or not u.canAttack():
		return
	now = camClock()
	owner = target.getOwner()
	team = gc.getTeam(gc.getPlayer(u.getOwner()).getTeam())
	hostile = owner >= 0 and owner != u.getOwner() and team.isAtWar(gc.getPlayer(owner).getTeam())
	foreign = owner >= 0 and owner != u.getOwner()
	army = u.getGroup().getNumUnits() >= 2
	if not (attack or hostile or (foreign and army)):
		return
	if not attack and now - g_camera["at"] < MOVE_WATCH_GAP:
		return
	start = u.plot()
	cam = CyCamera()
	cam.JustLookAtPlot(start)
	cam.SetZoom(0.5)
	g_camera["at"], g_camera["turn_news"] = now, True
	# a long march: the camera drifts only its first few tiles (the unit walks about that far this turn)
	dx, dy = target.getX() - start.getX(), target.getY() - start.getY()
	far = max(abs(dx), abs(dy))
	if far > 3:
		target = gc.getMap().plot(start.getX() + dx * 3 / far, start.getY() + dy * 3 / far)
	glide(start, target, 0.5, 0.48, EVENT_HOLD)
	shotLabel([u.getOwner(), owner])

def cameraHold(x, y):
	# a shot chosen from outside (the studio): the camera goes there and the cameraman leaves it a while
	plot = gc.getMap().plot(int(x), int(y))
	if not plot.isNone():
		CyCamera().JustLookAtPlot(plot)
		g_camera["at"] = camClock()
		pushIn(plot, EVENT_HOLD)

SHOT_SECONDS = 14       # one shot of the cameraman (calm: the edit cuts it short anyway)
EVENT_HOLD = 12         # an event's shot (a battle, a city taken) is held this long before the cameraman moves on
SHOT_KINDS = ("army", "frontier", "tour", "city", "frontier", "army", "tour", "wide")
TOUR_SECONDS = 30     # a tour: the whole world from far out, gliding from one capital to another

def cameraman():
	# the spectator's camera never rests: between events it cuts every few seconds to something worth seeing,
	# an army in the field, a border where two leaders meet, a growing city, a wide view of an empire. Only the
	# screen moves (the game's own random numbers are never used, so nothing in the game changes)
	if not spectating():
		return
	now = camClock()
	# a leader's turn ending cuts in, unless an event's shot is still holding
	if g_recap and now - g_camera["at"] >= EVENT_HOLD and now >= g_camera.get("recap_until", 0):
		if showRecap(now):
			g_camera["recap_until"] = now + RECAP_SECONDS
			return
	if cameraMoving(now):
		return
	if now - g_camera["at"] < EVENT_HOLD or now < g_camera.get("until", 0):
		return
	import random
	kinds = list(SHOT_KINDS)
	k = g_camera.get("shot", 0)
	shot = None
	for i in range(len(kinds)):
		kind = kinds[(k + i) % len(kinds)]
		shot = pickShot(kind, random)
		if shot:
			g_camera["shot"] = k + i + 1
			break
	if not shot:
		return
	if shot[0] == "tour":
		a, b, who = shot[1], shot[2], shot[3]
		shotLabel(who)
		cam = CyCamera()
		cam.JustLookAtPlot(a)
		cam.SetBasePitch(0.0)
		cam.SetZoom(0.8)
		glide(a, b, 0.8, 0.8, TOUR_SECONDS)
		g_camera["until"] = now + TOUR_SECONDS
		return
	x, y, zoom, pitch, who = shot
	shotLabel(who)
	cam = CyCamera()
	plot = gc.getMap().plot(x, y)
	cam.JustLookAtPlot(plot)
	cam.SetBasePitch(pitch)
	cam.SetZoom(zoom)
	g_camera["until"] = now + SHOT_SECONDS
	# a shot never stands still: the camera drifts a tile or two across it and pushes in a little
	dx, dy = random.choice(((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)))
	glide(plot, gc.getMap().plot(x + dx, y + dy), zoom, zoom * 0.96, SHOT_SECONDS)

def glide(a, b, z0, z1, seconds):
	if a.isNone():
		return
	if b.isNone():
		b = a
	p, q = a.getPoint(), b.getPoint()
	g_camera["move"] = {"a": (p.x, p.y, p.z), "b": (q.x, q.y, q.z), "z": (z0, z1), "t0": camClock(), "dur": float(seconds)}

def pushIn(plot, seconds):
	# an event's shot holds on the place and slowly pushes in
	z = 0.5   # an event is seen from a middle distance, whatever shot came before (a far tour hid the city)
	CyCamera().SetZoom(z)
	glide(plot, plot, z, z * 0.96, seconds)
	shotLabel([plot.getOwner()])

def cameraMoving(now):
	# from every poll (about 25 a second): the next small step of the current shot's drift
	m = g_camera.get("move")
	if not m:
		return False
	t = (now - m["t0"]) / m["dur"]
	if t >= 1.0 or t < 0:
		g_camera["move"] = None
		return False
	e = t * t * (3 - 2 * t)   # ease in and out
	a, b = m["a"], m["b"]
	cam = CyCamera()
	cam.JustLookAt(NiPoint3(a[0] + (b[0] - a[0]) * e, a[1] + (b[1] - a[1]) * e, a[2] + (b[2] - a[2]) * e))
	cam.SetZoom(m["z"][0] + (m["z"][1] - m["z"][0]) * e)
	return True

def pickShot(kind, random):
	seats = [i for i in agentPlayers() if gc.getPlayer(i).isAlive()]
	if not seats:
		return None
	m = gc.getMap()
	if kind == "army":
		stacks = {}
		for i in seats:
			p = gc.getPlayer(i)
			atWar = [j for j in seats if j != i and gc.getTeam(p.getTeam()).isAtWar(gc.getPlayer(j).getTeam())]
			(u, it) = p.firstUnit(False)
			while u and not u.isNone():
				if u.canAttack() and not u.plot().isCity() and u.getDomainType() == DomainTypes.DOMAIN_LAND:
					key = (u.getX(), u.getY())
					stacks[key] = stacks.get(key, 0) + 1 + (atWar and 2 or 0)
				(u, it) = p.nextUnit(it, False)
		best = [k for k, v in sorted(stacks.items(), key=lambda kv: -kv[1])[:3] if v >= 2]
		if best:
			x, y = random.choice(best)
			pl = m.plot(x, y)
			return (x, y, 0.55, -12.0, [pl.getUnit(0).getOwner()])
		return None
	if kind == "frontier":
		edges = []
		for n in range(0, m.numPlots(), 3):
			pl = m.plotByIndex(n)
			a = pl.getOwner()
			if a not in seats:
				continue
			for dx, dy in ((1, 0), (0, 1), (1, 1), (-1, 1)):
				q = m.plot(pl.getX() + dx, pl.getY() + dy)
				if not q.isNone() and q.getOwner() in seats and q.getOwner() != a:
					war = gc.getTeam(gc.getPlayer(a).getTeam()).isAtWar(gc.getPlayer(q.getOwner()).getTeam())
					edges.append((war and 3 or 1, pl.getX(), pl.getY(), q.getOwner()))
					break
		if edges:
			top = max([e[0] for e in edges])
			w, x, y, b = random.choice([e for e in edges if e[0] == top])
			return (x, y, 0.62, -8.0, [m.plot(x, y).getOwner(), b])
		return None
	if kind == "city":
		cities = []
		for i in seats:
			(c, it) = gc.getPlayer(i).firstCity(False)
			while c and not c.isNone():
				cities.append(c)
				(c, it) = gc.getPlayer(i).nextCity(it, False)
		if cities:
			c = random.choice(cities)
			return (c.getX(), c.getY(), 0.5, -15.0, [c.getOwner()])
		return None
	if kind == "tour":
		caps = [gc.getPlayer(i).getCapitalCity() for i in seats]
		caps = [c for c in caps if c and not c.isNone()]
		if len(caps) < 2:
			return None
		n = g_camera.get("tour", 0)
		g_camera["tour"] = n + 1
		a, b = caps[n % len(caps)], caps[(n + 1) % len(caps)]
		return ("tour", a.plot(), b.plot(), [a.getOwner(), b.getOwner()])
	if kind == "wide":
		i = seats[g_camera.get("wide", 0) % len(seats)]
		g_camera["wide"] = g_camera.get("wide", 0) + 1
		c = gc.getPlayer(i).getCapitalCity()
		if c and not c.isNone():
			return (c.getX(), c.getY(), 0.8, 0.0, [i])
	return None

def spectatorView():
	# once per loaded game, from the bridge's own update (the game refuses it inside an event): the spectator's
	# team sees all the land (screen only), then the debug view draws every unit and city; turning it on
	# (or off and on) is what redraws the map
	if g_camera["debug_tried"] or not spectating():
		return
	g_camera["debug_tried"] = True
	g = gc.getGame()
	m, team = gc.getMap(), gc.getPlayer(g.getActivePlayer()).getTeam()
	for i in range(m.numPlots()):
		m.plotByIndex(i).setRevealed(team, True, False, -1)
	if g.isDebugMode():
		g.toggleDebugMode()
	g.toggleDebugMode()
	if not g.isDebugMode():
		g.toggleDebugMode()   # no cheat code: the game ignores it; leave the view as it was
		log("director camera: no full-map view (set CheatCode in CivilizationIV.ini)")

def directorCamera(tag, a):
	if not spectating():
		return
	if tag == "BeginGameTurn":
		if not g_camera["turn_news"]:
			seats = [i for i in agentPlayers() if gc.getPlayer(i).isAlive() and not gc.getPlayer(i).getCapitalCity().isNone()]
			if seats:
				c = gc.getPlayer(seats[g_camera["next_seat"] % len(seats)]).getCapitalCity()
				g_camera["next_seat"] = g_camera["next_seat"] + 1
				cameraTo(c.getX(), c.getY(), 0)
		g_camera["turn_news"], g_camera["prio"] = False, 0
		return
	prio = CAMERA_KINDS.get(tag)
	if not prio:
		return
	if tag == "combatResult":
		if a[0].isAnimal() or a[1].isAnimal():
			return
		cameraTo(a[1].getX(), a[1].getY(), prio)
	elif tag == "cityAcquired":
		cameraTo(a[2].getX(), a[2].getY(), prio)
	else:
		cameraTo(a[0].getX(), a[0].getY(), prio)

def safeRecordEvent(tag, args):
	try:
		directorCamera(tag, args)
	except:
		log("director camera FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
	try:
		if tag == "BeginGameTurn" and seatsConfigured():
			try:
				writeTruth(args[0] + 1)
			except:
				log("truth FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
		if seatsConfigured():
			forEachSeat(recordEvent, tag, args)
		else:
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

def isKeyUnit(info):
	# units whose use is a big decision: where a city goes, a great person's gift, where a faith spreads
	if info.isFound() or info.getProductionCost() < 0:
		return True
	for r in range(gc.getNumReligionInfos()):
		if info.getReligionSpreads(r) > 0:
			return True
	for k in range(gc.getNumCorporationInfos()):
		if info.getCorporationSpreads(k) > 0:
			return True
	if info.isSpy() or info.getNukeRange() >= 0:
		return True   # spy missions and nukes are a ruler's decisions, not the automation's
	return False

def claimKeyUnit(u):
	# such a unit waits for Claude's orders instead of being used by the built-in AI
	info = gc.getUnitInfo(u.getUnitType())
	if not isKeyUnit(info):
		return
	c = loadClaims()
	if not c.has_key(u.getID()):
		c[u.getID()] = {"target": None}
		saveClaims(c)
	writeEvent("unit_waiting", {"id": u.getID(), "unit": info.getType(), "x": u.getX(), "y": u.getY(),
		"note": "waits for your orders (civ actions %d); civ release %d hands it to the built-in AI" % (u.getID(), u.getID())})

def aiUnitUpdate(gu, argsList):
	u = argsList[0]
	if g_window[0] and g_window[0][0] == "human":
		try:
			checkpointTick()   # the human's turn just ended: close that window before units move
		except:
			log("deal checkpoint FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
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
		before = (u.getX(), u.getY(), u.getMoves())
		g.pushMission(MissionTypes(m), d1, d2, 0, False, True, MissionAITypes.NO_MISSIONAI, pl, u)
		if not u.isDead() and g.getLengthMissionQueue() == 0 and (u.getX(), u.getY(), u.getMoves()) == before:
			# the game refused the order now that our turn came (the target changed, no moves left...): say so
			cl["busy"] = False
			cl["mission"] = None
			saveClaims(claims)
			writeEvent("order_failed", {"id": u.getID(), "unit": gc.getUnitInfo(u.getUnitType()).getType(),
				"x": u.getX(), "y": u.getY(), "order": gc.getMissionInfo(m).getType(),
				"note": "the order you gave during the other player's turn couldn't be carried out when our turn came; "
				"the unit waits (civ actions %d)" % u.getID()})
			g.pushMission(MissionTypes.MISSION_SKIP, -1, -1, 0, False, False, MissionAITypes.NO_MISSIONAI, u.plot(), u)
		return 1
	if g.getLengthMissionQueue() > 0:
		return 1   # an order of the agent's is under way (a multi-turn move, a worker's job): leave it to run
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
		m = cl.get("mission")
		cl["busy"] = False
		cl["mission"] = None
		saveClaims(claims)
		left = unfinishedBuild(u, m)
		if left:
			# the game stops a worker's job when hostile units come near (a human's workers stop the same way):
			# the job is not done, and the progress made stays on the tile
			writeEvent("job_interrupted", {"id": u.getID(), "unit": gc.getUnitInfo(u.getUnitType()).getType(),
				"x": u.getX(), "y": u.getY(), "job": left,
				"note": "the game stopped this job before it was finished, as it does when hostile units are near "
				"(barbarians, animals or an enemy); the progress stays on the tile. Order it again when it is safe"})
		else:
			writeEvent("unit_done", {"id": u.getID(), "unit": gc.getUnitInfo(u.getUnitType()).getType(),
				"x": u.getX(), "y": u.getY()})
	g.pushMission(MissionTypes.MISSION_SKIP, -1, -1, 0, False, False, MissionAITypes.NO_MISSIONAI, u.plot(), u)
	return 1

def unfinishedBuild(u, mission):
	# a worker's build order whose work isn't on the tile: "FARM, 300 of 500 done", else None
	if not mission or int(mission[0]) != int(MissionTypes.MISSION_BUILD):
		return None
	b = int(mission[1])
	pl = u.plot()
	info = gc.getBuildInfo(b)
	if info.getImprovement() >= 0 and pl.getImprovementType() == info.getImprovement():
		return None
	if info.getRoute() >= 0 and pl.getRouteType() >= info.getRoute():
		return None
	if pl.getBuildProgress(b) <= 0:
		return None
	return "%s, %d of %d done" % (info.getType()[len("BUILD_"):], pl.getBuildProgress(b), pl.getBuildTime(b))

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

def asSeatOf(owner, fn, *args):
	# the game asks about one civ's unit, city or turn: answer with that civ's own seat (its unit
	# claims, build lists, choices). Without this, every agent but one was run by the built-in AI.
	B = sys.modules["ClaudeBridge"]
	if B.seatsConfigured() and owner in B.agentPlayers() and B.g_acting[0] != owner:
		prev = B.actAs(owner)
		try:
			return fn(*args)
		finally:
			B.actAs(prev)
	return fn(*args)

def teamAgent(eTeam):
	for i in sys.modules["ClaudeBridge"].agentPlayers():
		if gc.getPlayer(i).getTeam() == eTeam:
			return i
	return -1

def unitUpdateTrampoline(argsList):
	import CvGameInterfaceFile
	B = sys.modules["ClaudeBridge"]
	return B.asSeatOf(argsList[0].getOwner(), B.aiUnitUpdate, CvGameInterfaceFile.GameUtils, argsList)

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

def alone(u, args):
	# an order for one unit is that unit's own: it leaves the stack it is in (the built-in AI grouped
	# units, e.g. a settler with its escort, and the stack followed one unit's orders), unless --stack
	if not args.get("stack") and u.getGroup().getNumUnits() > 1 and hasattr(u, "claudeLeaveGroup"):
		u.claudeLeaveGroup()

def whyNoMove(u, pl, turns):
	# the reason a move was refused, in the game's terms, so the player can choose another way
	land = gc.getUnitInfo(u.getUnitType()).getDomainType() == DomainTypes.DOMAIN_LAND
	iTeam = gc.getPlayer(u.getOwner()).getTeam()
	if not pl.isRevealed(iTeam, False):
		return "that tile is unexplored; the pathfinder only plans through tiles you have seen"
	if gc.getUnitInfo(u.getUnitType()).getDomainType() == DomainTypes.DOMAIN_AIR:
		d = plotDistance(u.getX(), u.getY(), pl.getX(), pl.getY())
		if d > u.airRange():
			return ("an air unit acts only within its range of %d tiles from its base; %d,%d is %d tiles away. Rebase it first "
				"to a city of yours (or a carrier) within %d tiles of both: civ move %d X Y") % (u.airRange(), pl.getX(), pl.getY(),
				d, u.airRange(), u.getID())
		if u.movesLeft() <= 0:
			return "the air unit has already acted this turn; order it again next turn"
		return ("an air unit strikes enemy units within range (civ move %d X Y --attack) or rebases to a city or carrier of "
			"yours; this tile is neither") % u.getID()
	if land and pl.isWater():
		return "it is water (%s); a land unit needs a boat to cross" % gc.getTerrainInfo(pl.getTerrainType()).getDescription()
	if not land and not pl.isWater() and not pl.isCity():
		return "it is land; a ship moves on water and into coastal cities only"
	if pl.isImpassable():
		return "it is impassable (peak)"
	if u.movesLeft() <= 0:
		return "the unit has no moves left this turn; order it again next turn"
	owner = pl.getOwner()
	if owner >= 0 and gc.getPlayer(owner).getTeam() != iTeam and not gc.getTeam(iTeam).isOpenBorders(gc.getPlayer(owner).getTeam()) \
			and not gc.getTeam(iTeam).isAtWar(gc.getPlayer(owner).getTeam()):
		return "it is %s's land, and without open borders (or war) your units can't enter it" % pname(owner)
	if turns < 0:
		return ("the game's pathfinder finds no route: every way there is blocked (water, peaks, or the land of a civ "
			"you have no open borders with). `civ around %d %d` shows the tiles around it" % (u.getX(), u.getY()))
	return "the game refused the order (try `civ actions %d`)" % u.getID()

def cmdMove(args):
	# order a unit to walk to x, y (alone, or with its stack: --stack); multi-turn paths are fine
	u = myUnit(args["id"])
	alone(u, args)
	x = int(args["x"])
	y = int(args["y"])
	pl = CyMap().plot(x, y)
	if pl.isNone():
		raise Exception("no such tile %d,%d" % (x, y))
	if not args.get("attack") and pl.isVisibleEnemyUnit(u.getOwner()):
		# moving onto an enemy is an attack (the game's rule); a human sees the odds before clicking
		dfd = pl.getBestDefender(-1, u.getOwner(), u, True, False, False)
		odds = ""
		if dfd is not None and not dfd.isNone() and u.canAttack():
			odds = ": %s of %s defends, win odds %.1f%%" % (gc.getUnitInfo(dfd.getUnitType()).getDescription(),
				pname(dfd.getOwner()), getCombatOdds(u, dfd) / 10.0)
		raise Exception("%d,%d holds enemy units, so this move would attack%s. Add --attack to attack, or move "
			"next to it (`civ odds %d %d` for every unit in reach)" % (x, y, odds, x, y))
	g = u.getGroup()
	before = (u.getX(), u.getY())
	turns = -1
	if hasattr(g, "claudePathTurns"):
		turns = g.claudePathTurns(x, y)   # the game's pathfinder: terrain, roads, rivers, this unit's speed
	had = loadClaims().get(u.getID())
	setClaim(u.getID(), [x, y])
	noteAct("move", (x, y))
	try:
		watchMove(u, pl, bool(args.get("attack")))
	except:
		log("watch move FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
	g.pushMission(MissionTypes.MISSION_MOVE_TO, x, y, 0, False, True, MissionAITypes.NO_MISSIONAI, pl, u)
	if (u.getX(), u.getY()) == before and g.getLengthMissionQueue() == 0 and before != (x, y):
		# a refused order leaves no standing order behind (else the unit hook would try it again every turn)
		c = loadClaims()
		c[u.getID()] = had or {"target": None}
		saveClaims(c)
		raise Exception("unit #%d can't go to %d,%d: %s" % (u.getID(), x, y, whyNoMove(u, pl, turns)))
	r = {"id": u.getID(), "from": before, "now_at": (u.getX(), u.getY()), "target": (x, y),
		"moves_left": u.movesLeft(), "missions_queued": g.getLengthMissionQueue()}
	if args.get("attack") and plotDistance(before[0], before[1], x, y) > 1:
		r["attack_note"] = "the target was not next to the unit: it walks first, and fights any enemy it runs into on the way"
	if turns >= 0:
		r["arrives"] = "in %d of our turns by the game's pathfinder (a group moves at its slowest unit's pace)" % turns
	if not gc.getPlayer(u.getOwner()).isTurnActive():
		r["when"] = "it moves in our own turn, which comes after the human ends theirs: they see it there only then"
	return r

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

def writeChat(who, text, to=None):
	# one line in the acting seat's chat (who: "claude" = this seat, "player" = the human, else a leader's name)
	ensureDir()
	row = {"from": who, "text": text, "turn": gc.getGame().getGameTurn(), "time": time.strftime("%H:%M:%S")}
	if to is not None:
		row["to"] = to
	f = open(CHAT_FILE, "ab")
	try:
		f.write(toJson(row) + "\n")
	finally:
		f.close()

def appendLine(path, row):
	ensureDir()
	f = open(path, "ab")
	try:
		f.write(toJson(row) + "\n")
	finally:
		f.close()

def deliverChat(frm, text, to, aim=None):
	"""Several agents: a message from seat frm to everyone (to=None, public) or to one player (private).
	Each seat's chat holds only what that seat may read; chat_all.jsonl (the director's and the video's)
	holds everything."""
	turn = gc.getGame().getGameTurn()
	full = lambda i: "%s (%s)" % (realName(i), gc.getPlayer(i).getCivilizationShortDescription(0))
	shown = lambda i: gc.getPlayer(i).getName() != realName(i) and u"%s \u00b7 %s" % (gc.getPlayer(i).getName(), realName(i)) or full(i)
	appendLine(OUT_DIR + "\\chat_all.jsonl", {"from": full(frm), "from_id": frm,
		"to": to is None and "all" or full(to), "to_id": to, "text": text, "turn": turn, "time": time.strftime("%H:%M:%S")})
	# like the game's own diplomacy: only leaders who have met the speaker hear him
	met = lambda i: i == frm or gc.getTeam(gc.getPlayer(i).getTeam()).isHasMet(gc.getPlayer(frm).getTeam())
	readers = [x for x in agentPlayers() if met(x)]
	if to is not None:
		readers = [x for x in readers if x in (frm, to)]
	for r in readers:
		prev = actAs(r)
		try:
			if r == frm:
				writeChat("claude", text, to is None and "all" or pname(to))
			else:
				writeChat(pname(frm), text, to is None and "all" or "you")
				writeEvent("message_from_leader", {"from": pname(frm), "text": text, "private": to is not None})
		finally:
			actAs(prev)
	# the spectator's filmed screen shows every line (the video sees all channels); a human who plays sees only
	# what reaches him: lines to all, to him, and his own. The speaker in his civ's colour; a private line says to
	# whom and that it is private
	head = to is None and u"%s to all" % colored(frm, shown(frm)) or \
		u"%s to %s  <color=170,170,170,255>(private)</color>" % (colored(frm, shown(frm)), colored(to, shown(to)))
	line = u"<font=4>%s:  <color=255,235,180,255>%s</color></font>" % (head, text)   # the message panel wraps it
	for i in humanPlayers():
		if to is not None and i not in (to, frm) and not spectating():
			continue
		CyInterface().addMessage(i, True, gc.getEVENT_MESSAGE_TIME() * 4, line, "",
			InterfaceMessageTypes.MESSAGE_TYPE_MAJOR_EVENT, "", -1, -1, -1, False, False)
	if spectating():
		chatShow(head, text, aim)

# The filmed screen's chat: the game's own message panel grows over the middle of the map and, under Wine,
# keeps its lines for minutes (its clock moves in 128 s steps). So the spectator gets the bridge's own panel at
# the left edge: the last few lines, each for a while by the camera's clock; a long one is cut short (the
# full text is in chat_all.jsonl for the edit)
CHAT_LINES, CHAT_SECONDS, CHAT_CHARS = 3, 25, 220
g_chat = {"lines": [], "shown": None}

def chatShow(head, text, aim=None):
	if len(text) > CHAT_CHARS:
		text = text[:CHAT_CHARS].rsplit(" ", 1)[0] + u"..."   # the game's font has no ellipsis sign
	if aim:
		# what the speaker privately meant by it (its own note, sent with the message): said vs meant, for the viewer
		text = text + u"\n<color=175,175,175,255>   meant: %s</color>" % aim[:140]
	g_chat["lines"] = (g_chat["lines"] + [(camClock(), head, text)])[-CHAT_LINES:]

CAPTION_SECONDS = 8
g_caption = {"text": None, "until": 0.0, "shown": None}
g_who = {"text": None, "shown": None}

def shotLabel(players):
	# whose land the shot shows, at the top of the screen: "Claude Sonnet · Asoka · India"
	names = []
	for i in players:
		if i is not None and i >= 0 and gc.getPlayer(i).isAlive() and agentPlayers().count(i):
			p = gc.getPlayer(i)
			t = p.getName() != realName(i) and u"%s \u00b7 %s \u00b7 %s" % (p.getName(), realName(i),
				p.getCivilizationShortDescription(0)) or u"%s \u00b7 %s" % (realName(i), p.getCivilizationShortDescription(0))
			if colored(i, t) not in names:
				names.append(colored(i, t))
	g_who["text"] = names and u"  |  ".join(names) or None

def whoPanel(sc):
	if g_who["text"] == g_who["shown"]:
		return
	g_who["shown"] = g_who["text"]
	sc.deleteWidget("CIVAIWhoBG")
	sc.deleteWidget("CIVAIWho")
	if g_who["text"]:
		W = sc.getXResolution()
		w = min(int(W * 0.7), 40 + len(re.sub("<[^>]*>", "", g_who["text"])) * 13)
		sc.addPanel("CIVAIWhoBG", u"", u"", True, False, (W - w) / 2, 54, w, 38, PanelStyles.PANEL_STYLE_MAIN_BLACK50)
		sc.setLabel("CIVAIWho", "Background", u"<font=4>%s</font>" % g_who["text"], 1 << 2,
			W / 2, 61, -0.1, FontTypes.TITLE_FONT, WidgetTypes.WIDGET_GENERAL, -1, -1)

def caption(text):
	# the event's title over the shot (the game shows its own pop-up only to the civs involved, never to the
	# filmed spectator): the studio calls it with each event it films
	if isinstance(text, str):
		text = text.decode("utf-8", "replace")   # the studio sends UTF-8 bytes ("Claude Sonnet \xc2\xb7 Asoka")
	g_caption["text"], g_caption["until"] = text, camClock() + CAPTION_SECONDS

def captionPanel(sc, now):
	text = now < g_caption["until"] and g_caption["text"] or None
	if text == g_caption["shown"]:
		return
	g_caption["shown"] = text
	sc.deleteWidget("CIVAICaptionBG")
	sc.deleteWidget("CIVAICaption")
	if not text:
		return
	W = sc.getXResolution()
	w = min(int(W * 0.6), 40 + len(text) * 15)
	x = (W - w) / 2
	sc.addPanel("CIVAICaptionBG", u"", u"", True, False, x, 96, w, 46, PanelStyles.PANEL_STYLE_MAIN_BLACK50)
	sc.setLabel("CIVAICaption", "Background", u"<font=4b><color=255,220,120,255>%s</color></font>" % text, 1 << 2,
		W / 2, 106, -0.1, FontTypes.TITLE_FONT, WidgetTypes.WIDGET_GENERAL, -1, -1)

def chatPanel():
	import CvScreenEnums
	now = camClock()
	try:
		captionPanel(CyGInterfaceScreen("MainInterface", CvScreenEnums.MAIN_INTERFACE), now)
		whoPanel(CyGInterfaceScreen("MainInterface", CvScreenEnums.MAIN_INTERFACE))
	except:
		g_caption["text"] = None
		log("caption FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
	g_chat["lines"] = [l for l in g_chat["lines"] if now - l[0] < CHAT_SECONDS]
	key = tuple([l[0] for l in g_chat["lines"]])
	if key == g_chat["shown"]:
		return
	g_chat["shown"] = key
	sc = CyGInterfaceScreen("MainInterface", CvScreenEnums.MAIN_INTERFACE)
	sc.deleteWidget("CIVAIChatBG")
	sc.deleteWidget("CIVAIChat")
	if not g_chat["lines"]:
		return
	W, H = sc.getXResolution(), sc.getYResolution()
	w = int(W * 0.34)
	per = w / 13   # characters per line at the chat's font, about (a low guess: a scroll bar is worse than space)
	rows = 0
	for t, head, text in g_chat["lines"]:
		rows = rows + 1 + text.count("\n") + (len(re.sub("<[^>]*>", "", head)) + len(re.sub("<[^>]*>", "", text)) + 3) / per
	h = min(int(H * 0.6), rows * 27 + 28)
	x, y = 12, int(H * 0.86) - h
	body = u"\n".join([u"<font=4>%s:  <color=255,235,180,255>%s</color></font>" % (head, text)
		for t, head, text in g_chat["lines"]])
	sc.addPanel("CIVAIChatBG", u"", u"", True, False, x, y, w + 16, h, PanelStyles.PANEL_STYLE_MAIN_BLACK50)
	sc.addMultilineText("CIVAIChat", body, x + 8, y + 8, w, h - 8, WidgetTypes.WIDGET_GENERAL, -1, -1, 1 << 0)

def colored(i, text):
	# a leader's name in his civ's colour, as the game's own score list shows it
	try:
		c = gc.getColorInfo(gc.getPlayerColorInfo(gc.getPlayer(i).getPlayerColor()).getColorTypePrimary()).getColor()
		# lifted toward white: a dark civ colour (navy, purple) must still read on the dark chat panel
		lift = lambda v: int((v + (1.0 - v) * 0.4) * 255)
		return u"<color=%d,%d,%d,255>%s</color>" % (lift(c.r), lift(c.g), lift(c.b), text)
	except:
		return text

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
	em.Events[MODEL_EVENT_ID] = ("ClaudeModel", modelApplyTrampoline, modelBeginTrampoline)
	if MODEL_EVENT_ID not in CvUtil.SilentEvents:
		CvUtil.SilentEvents.append(MODEL_EVENT_ID)
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
	if not hasattr(gu, "_claudeOrigDoGold"):
		gu._claudeOrigDoGold = gu.doGold
	gu.doGold = doGoldTrampoline
	if not hasattr(gu, "_claudeOrigCanRaze"):
		gu._claudeOrigCanRaze = gu.canRazeCity
	gu.canRazeCity = canRazeTrampoline
	g_patched[0] = True
	log("hooks installed: chat, unit claims, city claims, diplomacy, war, budget, razing, turn gate")

def cmdSay(args):
	# a chat line in the game's chat log (like a human opponent), or a popup with popup=true;
	# in a game of several agents: to everyone, or privately to one leader ("to")
	text = args["text"]
	noteAct("say", None)
	if seatsConfigured():
		to = None
		if args.get("to"):
			to = findPlayer(args["to"])
			if to == getClaudePlayer():
				raise Exception("that is you")
			if not gc.getTeam(gc.getPlayer(getClaudePlayer()).getTeam()).isHasMet(gc.getPlayer(to).getTeam()):
				raise Exception("you have not met %s yet" % args["to"])
		deliverChat(getClaudePlayer(), text, to, args.get("aim"))   # the aim only ever reaches the filmed screen
		me = gc.getPlayer(getClaudePlayer()).getTeam()
		heard = [i for i in range(gc.getMAX_CIV_PLAYERS()) if i != getClaudePlayer() and gc.getPlayer(i).isAlive()
			and gc.getTeam(gc.getPlayer(i).getTeam()).isHasMet(me) and (to is None or i == to)]
		readers = [pname(i) for i in heard if isAgent(i) or gc.getPlayer(i).isHuman()]
		deaf = [pname(i) for i in heard if not isAgent(i) and not gc.getPlayer(i).isHuman()]
		r = {"shown": True, "to": to is None and "all" or pname(to), "read_by": readers or ["nobody"],
			"turn": gc.getGame().getGameTurn()}
		if deaf:
			r["note"] = "%s: run by the game's own AI, which reads no chat; deals and deeds speak to it" % ", ".join(deaf)
		return r
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
	return {"shown": True, "turn": gc.getGame().getGameTurn()}


def cmdNotice(args):
	# a line from CIVAI itself (not from the leader): the loop explains a silent leader this way
	line = u"<color=160,160,160,255>[CIVAI] %s</color>" % args["text"]
	for i in range(gc.getMAX_CIV_PLAYERS()):
		if gc.getPlayer(i).isAlive() and gc.getPlayer(i).isHuman():
			CyInterface().addMessage(i, True, gc.getEVENT_MESSAGE_TIME() * 3, line, "",
				InterfaceMessageTypes.MESSAGE_TYPE_MAJOR_EVENT, "", -1, -1, -1, False, False)
	writeEvent("civai_notice", {"text": args["text"]})
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
			"an UPPERCASE letter = the same on hills, e.g. G = grassland hill), feature (f forest, j jungle, l flood plains, o oasis, i ice, . none), "
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
		if t == "MISSION_SPREAD" and a.getMissionData() >= 0:
			return "SPREAD_" + gc.getReligionInfo(a.getMissionData()).getType()[len("RELIGION_"):]
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

def spyOptions(i, target, pl):
	# the choices of a two-phase mission (the game's second popup): which building, tech, civic, religion, project
	k = gc.getEspionageMissionInfo(i)
	tp = gc.getPlayer(target)
	tt = gc.getTeam(tp.getTeam())
	c = pl.isCity() and pl.getPlotCity() or None
	if k.getDestroyBuildingCostFactor() > 0 and c:
		return [(b, gc.getBuildingInfo(b).getDescription()) for b in range(gc.getNumBuildingInfos()) if c.getNumRealBuilding(b) > 0]
	if k.getBuyTechCostFactor() > 0:
		mine = gc.getTeam(gc.getPlayer(getClaudePlayer()).getTeam())
		return [(t, gc.getTechInfo(t).getDescription()) for t in range(gc.getNumTechInfos()) if tt.isHasTech(t) and not mine.isHasTech(t)]
	if k.getSwitchCivicCostFactor() > 0:
		return [(v, gc.getCivicInfo(v).getDescription()) for v in range(gc.getNumCivicInfos())]
	if k.getSwitchReligionCostFactor() > 0:
		return [(v, gc.getReligionInfo(v).getDescription()) for v in range(gc.getNumReligionInfos())]
	if k.getType() == "ESPIONAGEMISSION_DESTROY_PROJECT":
		return [(v, gc.getProjectInfo(v).getDescription()) for v in range(gc.getNumProjectInfos()) if tt.getProjectCount(v) > 0]
	return []

def spyMissions(u):
	# a spy's missions where it stands, as the game's espionage popup lists them: (name, mission, data, cost, possible)
	# and why there are none. The game's rules: in another leader's land, not moved this turn (a spy must begin its
	# turn there), and enough espionage points against that leader
	if not gc.getUnitInfo(u.getUnitType()).isSpy():
		return [], None
	pl = u.plot()
	target = pl.getOwner()
	if target < 0 or target == u.getOwner():
		return [], "a spy's missions are done in another leader's land"
	if u.hasMoved() or u.isMadeAttack():
		return [], "a spy must begin its turn where it acts: it has moved (or acted) this turn, so its missions open next turn"
	if not u.canEspionage(pl):
		return [], "the game allows no mission here now (e.g. a vassal's land, or the spy is seen)"
	me = gc.getPlayer(u.getOwner())
	out = []
	for i in range(gc.getNumEspionageMissionInfos()):
		k = gc.getEspionageMissionInfo(i)
		if k.isPassive():
			continue   # passive missions (see research, demographics) need no spy: the Espionage screen
		if k.getTechPrereq() >= 0 and not gc.getTeam(me.getTeam()).isHasTech(k.getTechPrereq()):
			continue
		name = k.getType()[len("ESPIONAGEMISSION_"):]
		opts = k.isTwoPhases() and spyOptions(i, target, pl) or [(-1, None)]
		for data, label in opts:
			cost = me.getEspionageMissionCost(i, target, pl, data)
			if cost < 0:
				continue
			out.append((label and "%s %s" % (name, label) or name, i, data, cost, me.canDoEspionageMission(i, target, pl, data)))
	return out, None

def jobText(u):
	# a worker's job in progress, as the game shows it on the unit: what, how far, how many more turns. A job
	# goes on by itself every turn until it is done; ordering it again only restarts nothing (progress stays on the tile)
	b = u.getBuildType()
	if b < 0:
		return None
	pl = u.plot()
	info = gc.getBuildInfo(b)
	left = pl.getBuildTurnsLeft(b, 0, 0)
	return "%s: %d of %d done, about %d more turn%s (it goes on by itself)" % (info.getType()[len("BUILD_"):],
		pl.getBuildProgress(b), pl.getBuildTime(b), left, left != 1 and "s" or "")

def cmdActions(args):
	u = myUnit(args["id"])
	acts = unitActions(u)
	r = {"id": u.getID(), "unit": gc.getUnitInfo(u.getUnitType()).getDescription(), "at": (u.getX(), u.getY()),
		"moves_left": u.movesLeft() / gc.getMOVE_DENOMINATOR(),
		"actions": [n for (n, a, t) in acts if not t], "with_target_x_y": [n for (n, a, t) in acts if t]}
	if jobText(u):
		r["job"] = jobText(u)
	if [n for (n, a, t) in acts if n.startswith("BUILD_")]:
		# a worker's jobs depend on the tile it stands on: say what that tile is, so a missing job is explained
		pl = u.plot()
		ground = [pl.isHills() and "hill" or pl.isPeak() and "peak" or "flat",
			gc.getTerrainInfo(pl.getTerrainType()).getDescription().lower()]
		if pl.getFeatureType() >= 0:
			ground.append(gc.getFeatureInfo(pl.getFeatureType()).getDescription().lower())
		if pl.getImprovementType() >= 0:
			ground.append("has a %s" % gc.getImprovementInfo(pl.getImprovementType()).getDescription())
		r["jobs_are_for_this_tile"] = ("%d,%d is %s. Jobs differ by tile: a mine needs a hill or a mineral resource, "
			"chopping needs forest or jungle on the tile; move the worker there to get them" % (u.getX(), u.getY(), ", ".join(ground)))
	if u.getDomainType() == DomainTypes.DOMAIN_AIR:
		r["air"] = ("range %d tiles from its base. Strike enemy units: civ move %d X Y --attack (a tile within range; "
			"`civ odds X Y %d` first); rebase: civ move %d X Y to a city or carrier of yours within range") % (
			u.airRange(), u.getID(), u.getID(), u.getID())
	if gc.getUnitInfo(u.getUnitType()).isSpy():
		missions, why = spyMissions(u)
		target = u.plot().getOwner()
		if target >= 0 and target != u.getOwner():
			r["espionage_points"] = "%d against %s" % (gc.getTeam(gc.getPlayer(u.getOwner()).getTeam()).getEspionagePointsAgainstTeam(
				gc.getPlayer(target).getTeam()), pname(target))
		if why:
			r["spy_missions"] = why
		else:
			r["spy_missions"] = ["%s: %d points%s" % (n, cost, not ok and " (not possible now)" or "")
				for (n, i, data, cost, ok) in missions] or ["none here"]
			r["spy_order"] = "civ do %d <mission> (e.g. civ do %d STEAL_TREASURY); the target can catch the spy" % (u.getID(), u.getID())
	gives = actionYields(u, [n for (n, a, t) in acts], acts)
	if gives:
		r["what_they_give"] = gives
	return r

def actionYields(u, names, acts=()):
	# what a great person's action would give here (a human sees it hovering the button)
	pl = u.plot()
	out = []
	if "DISCOVER" in names:
		t = u.getDiscoveryTech()
		if t >= 0:
			out.append("DISCOVER: %s, %d research" % (gc.getTechInfo(t).getDescription(), u.getDiscoverResearch(t)))
	if "HURRY" in names:
		out.append("HURRY: %d production in %s" % (u.getHurryProduction(pl), pl.isCity() and pl.getPlotCity().getName() or "this city"))
	if "TRADE" in names:
		out.append("TRADE: %d gold" % u.getTradeGold(pl))
	if "GREAT_WORK" in names:
		out.append("GREAT_WORK: %d culture in %s" % (u.getGreatWorkCulture(pl), pl.isCity() and pl.getPlotCity().getName() or "this city"))
	for (n, a, t) in acts:
		if n == "CONSTRUCT" and a.getMissionData() >= 0:
			out.append("CONSTRUCT: builds %s here" % gc.getBuildingInfo(a.getMissionData()).getDescription())
		if n == "JOIN" and a.getMissionData() >= 0:
			out.append("JOIN: settles in this city as a %s for good" % gc.getSpecialistInfo(a.getMissionData()).getDescription())
	if "ESPIONAGE" in names or "INFILTRATE" in names:
		out.append("INFILTRATE: %d espionage points" % u.getEspionagePoints(pl))
	return out

ACTION_WORDS = {"DISBAND": "DELETE", "FOUND_CITY": "FOUND", "SETTLE": "FOUND", "EXPLORE": "AUTO_EXPLORE",
	"DISCOVER_TECH": "DISCOVER", "GOLDEN_AGE": "GOLDEN_AGE", "WAIT": "SKIP"}

def whyNoFound(u):
	pl = u.plot()
	if pl.isCity():
		return "this tile is already a city"
	if pl.isWater():
		return "a city can't stand on water"
	owner = pl.getOwner()
	if owner >= 0 and owner != u.getOwner():
		return "this is %s's land" % pname(owner)
	r = gc.getDefineINT("MIN_CITY_RANGE")
	for dx in range(-r, r + 1):
		for dy in range(-r, r + 1):
			q = CyMap().plot(u.getX() + dx, u.getY() + dy)
			if not q.isNone() and q.isCity():
				if not q.isRevealed(u.getTeam(), False):
					# a city in the fog: the rule, not the city (a human sees only that FOUND isn't possible)
					return "another city stands too close (cities must be more than %d tiles apart)" % r
				return "%s at %d,%d is too close (cities must be more than %d tiles apart)" % (q.getPlotCity().getName(), q.getX(), q.getY(), r)
	if u.movesLeft() <= 0:
		return "the settler has no moves left this turn"
	return "the game's rules don't allow a city on this tile"

def doSpyMission(u, want):
	# the game's own path (the espionage popup's answer): push MISSION_ESPIONAGE with the mission and its choice;
	# CvUnit::espionage tests interception, pays the points and sends the spy home
	missions, why = spyMissions(u)
	if why:
		raise Exception(why)
	w = want.upper().replace("_", " ")
	pick = [x for x in missions if x[0].upper().replace("_", " ") == w] or \
		[x for x in missions if x[0].upper().replace("_", " ").startswith(w)]
	if len(pick) != 1:
		raise Exception("%s: %s. The missions here: %s" % (want, pick and "say which one" or "no such mission here",
			", ".join([x[0] for x in (pick or missions)]) or "none"))
	name, i, data, cost, ok = pick[0]
	if not ok:
		have = gc.getTeam(gc.getPlayer(u.getOwner()).getTeam()).getEspionagePointsAgainstTeam(gc.getPlayer(u.plot().getOwner()).getTeam())
		raise Exception("%s is not possible now: it costs %d points; you have %d against %s" % (name, cost, have, pname(u.plot().getOwner())))
	if not gc.getPlayer(u.getOwner()).isTurnActive():
		raise Exception("a spy acts during our own turn; give the order when the turn begins")
	target = u.plot().getOwner()
	spot = u.plot().getPlotCity()   # where the mission happens (after it the game sends the spy home)
	where = spot and not spot.isNone() and spot.getName() or ("%d,%d" % (u.getX(), u.getY()))
	alone(u, {})
	before = gc.getTeam(gc.getPlayer(u.getOwner()).getTeam()).getEspionagePointsAgainstTeam(gc.getPlayer(target).getTeam())
	u.getGroup().pushMission(MissionTypes.MISSION_ESPIONAGE, i, data, 0, False, True, MissionAITypes.NO_MISSIONAI, u.plot(), u)
	after = gc.getTeam(gc.getPlayer(u.getOwner()).getTeam()).getEspionagePointsAgainstTeam(gc.getPlayer(target).getTeam())
	refreshSnapshot()
	alive = gc.getPlayer(u.getOwner()).getUnit(u.getID())
	if after < before:
		# the victim hears what the game would show its screen: what was done and where, not by whom
		try:
			if isAgent(target):
				prev = actAs(target)
				try:
					writeEvent("espionage_against_us", {"mission": name, "where": where,
						"text": "enemy infiltrators carried out %s at %s (the game does not say whose)" % (name, where)})
				finally:
					actAs(prev)
		except:
			log("espionage notice FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
		r = {"mission": name, "against": pname(target), "points_spent": before - after}
		if alive and not alive.isNone():
			r["spy"] = "escaped to (%d,%d)" % (alive.getX(), alive.getY())
		else:
			r["spy"] = "caught after the mission"
		return r
	if not alive or alive.isNone():
		return {"mission": name, "result": "the spy was caught before it could act (no points spent)"}
	return {"mission": name, "result": "the game did not carry it out", "points": after}

def cmdDo(args):
	# do one of the unit's available actions; queue=true adds it after its current orders
	u = myUnit(args["id"])
	want = args["action"].strip().upper().replace(" ", "_")
	if gc.getUnitInfo(u.getUnitType()).isSpy() and want not in ("MOVE_TO", "ROUTE_TO") and \
			[n for (n, a, t) in unitActions(u) if n == ACTION_WORDS.get(want, want)] == []:
		return doSpyMission(u, (want + " " + (args.get("target") or "")).strip())
	acts = unitActions(u)
	want = ACTION_WORDS.get(want, want)
	if want in ("SPREAD", "SPREAD_RELIGION"):
		spreads = [n for (n, a, t) in acts if n.startswith("SPREAD_")]
		if len(spreads) == 1:
			want = spreads[0]   # the one faith this unit carries
	if want in ("FORTIFY", "SLEEP", "SENTRY") and "WAKE" in [n for (n, a, t) in acts]:
		# already fortified or asleep: the order is already in effect
		return {"id": u.getID(), "already": "the unit is already fortified or asleep (WAKE to wake it)"}
	match = [x for x in acts if x[0] == want]
	if not match:
		# the start or part of an available action's name, if only one fits ("FARM" -> BUILD_FARM)
		part = [x for x in acts if want in x[0]]
		if len(part) == 1:
			match = part
	if not match:
		why = ""
		if want == "FOUND" and gc.getUnitInfo(u.getUnitType()).isFound():
			why = " (%s)" % whyNoFound(u)
		raise Exception("%s #%d can't %s here now%s. It can: %s" % (gc.getUnitInfo(u.getUnitType()).getDescription(),
			u.getID(), want, why, ", ".join([n for (n, a, t) in acts])))
	name, a, targeted = match[0]
	if name != "LEAD":
		alone(u, args)
	g = u.getGroup()
	m, c, au = a.getMissionType(), a.getCommandType(), a.getAutomateType()
	discovery = None
	if name == "DISCOVER":
		# a great person's discovery is research toward one tech (the game picks it), not always a whole tech
		dt = u.getDiscoveryTech()
		if dt >= 0:
			team = gc.getTeam(u.getTeam())
			discovery = (dt, u.getDiscoverResearch(dt), team.getResearchProgress(dt), team.getResearchCost(dt))
	if name == "LEAD":
		# without a unit the game opens a "which unit?" window that only a human's screen shows
		promo = gc.getUnitInfo(u.getUnitType()).getLeaderPromotion()
		pl = u.plot()
		can = [pl.getUnit(k) for k in range(pl.getNumUnits()) if pl.getUnit(k).getOwner() == u.getOwner()
			and pl.getUnit(k).getID() != u.getID() and pl.getUnit(k).canPromote(promo, u.getID())]
		want = args.get("unit")
		pick = [v for v in can if v.getID() == want]
		if not pick:
			raise Exception("LEAD needs the unit to join: civ do %d LEAD <unit id>. Units here that can take it: %s" % (u.getID(),
				", ".join(["#%d %s" % (v.getID(), gc.getUnitInfo(v.getUnitType()).getDescription()) for v in can]) or "none"))
		v = pick[0]
		if not u.lead(v.getID()):
			raise Exception("the game refused: %s can't lead %s now" % (gc.getUnitInfo(u.getUnitType()).getDescription(),
				gc.getUnitInfo(v.getUnitType()).getDescription()))
		c2 = loadClaims()
		if c2.has_key(u.getID()):
			del c2[u.getID()]
			saveClaims(c2)
		return {"led": "#%d %s now carries the general (%s)" % (v.getID(), gc.getUnitInfo(v.getUnitType()).getDescription(),
			gc.getPromotionInfo(promo).getDescription())}
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
		if name.startswith("UPGRADE"):
			g_ownUpgrades[u.getID()] = True
		u.doCommand(CommandTypes(c), a.getCommandData(), -1)
	else:
		# automation hands the unit back to the game's own automation
		c2 = loadClaims()
		if c2.has_key(u.getID()):
			del c2[u.getID()]
			saveClaims(c2)
		g.setAutomateType(AutomateTypes(au))
	if u.isNone() or u.plot().isNone():
		r = {"id": args["id"], "done": name, "unit": "gone (used up by the order)"}
		if discovery:
			dt, beakers, before, cost = discovery
			team = gc.getTeam(gc.getPlayer(getClaudePlayer()).getTeam())
			r["research"] = team.isHasTech(dt) and ("%s learned" % gc.getTechInfo(dt).getDescription()) or (
				"%d research put into %s (now %d of %d; the rest comes from normal research)" % (
				beakers, gc.getTechInfo(dt).getDescription(), team.getResearchProgress(dt), cost))
		return r
	r = {"id": u.getID(), "done": name, "at": (u.getX(), u.getY()), "moves_left": u.movesLeft() / gc.getMOVE_DENOMINATOR()}
	if g.getLengthMissionQueue():
		r["orders_queued"] = g.getLengthMissionQueue()
		if not u.movesLeft():
			# no moves left: the order waits in the queue and runs when the unit has moves again (next turn)
			del r["done"]
			r["queued"] = "%s: not done yet; it runs when the unit has moves again (next turn)" % name
	else:
		# an order that takes effect at once (fortify, sleep, sentry...) leaves no queue; say what the unit does now
		r["now"] = unitActivity(u)
	return r


def unitActivity(u):
	act = u.getGroup().getActivityType()
	if act == ActivityTypes.ACTIVITY_SLEEP:
		return u.isFortifyable() and "fortified" or "asleep"
	return {ActivityTypes.ACTIVITY_HOLD: "holding (skips this turn)", ActivityTypes.ACTIVITY_HEAL: "healing",
		ActivityTypes.ACTIVITY_SENTRY: "on sentry", ActivityTypes.ACTIVITY_INTERCEPT: "intercepting",
		ActivityTypes.ACTIVITY_PATROL: "patrolling", ActivityTypes.ACTIVITY_PLUNDER: "plundering",
		ActivityTypes.ACTIVITY_MISSION: "carrying out the order"}.get(act, "awaiting orders")




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

g_guardDue = [True]

def guardChoices(force=False):
	g_guardTick[0] = g_guardTick[0] + 1
	if g_guardTick[0] % 25 and not force and not g_guardDue[0]:
		return
	g_guardDue[0] = False
	p = gc.getPlayer(getClaudePlayer())
	if not p.isAlive():
		return
	if engineControl():
		# the engine keeps the built-in AI out: civics, religion and budget change only by Claude's
		# choice or by the game's rules (answers, deals, votes); only build lists need putting back
		restoreCityQueues(p)
		return
	want = loadChoices()
	now = currentChoices(p)
	if want is None:
		saveChoices(now)   # start from whatever the civ has now
		return
	if want.get("budget") and want["budget"] != budgetNow(p):
		before = budgetNow(p)
		applyBudget(p, want["budget"])   # the AI re-split it (it does so whenever income changes)
		if p.getGold() + p.calculateGoldRate() < 0:
			applyBudget(p, before)
	undone = []
	if now["religion"] != want["religion"]:
		p.setLastStateReligion(want["religion"])
		undone.append("state religion %s" % religionName(now["religion"]))
	for o in range(len(want["civics"])):
		if now["civics"][o] != want["civics"][o]:
			p.setCivics(o, want["civics"][o])
			undone.append("civic %s" % gc.getCivicInfo(now["civics"][o]).getDescription())
	if undone or p.isAnarchy():
		# anarchy Claude didn't cause (an AI revolution, even one already undone) is taken away
		now = gc.getGame().getGameTurn()
		extra = p.getAnarchyTurns() - max(0, int(want.get("own_anarchy_until", 0)) - now)
		if extra > 0:
			p.changeAnarchyTurns(-extra)
			if not undone:
				undone.append("%d turns of anarchy" % extra)
	restoreCityQueues(p)
	restoreDisbanded(p)
	snapUnits(p)
	if undone:
		writeEvent("ai_change_undone", {"undone": undone,
			"note": "the built-in AI changed this without your order; the bridge put it back"})

g_disbanded = []
g_strike = [0]
g_units = {}        # our units as last seen (the game forgets a unit's place before reporting it lost)
g_killed = {}       # ids that died a real death (unitKilled comes before unitLost)
g_ownUpgrades = {}  # ids Claude upgraded himself (`civ do <id> UPGRADE_...`)

def snapUnits(p):
	(u, it) = p.firstUnit(False)
	while u and not u.isNone():
		if not u.isDead() and u.getX() >= 0:
			g_units[u.getID()] = {"id": u.getID(), "type": u.getUnitType(), "x": u.getX(), "y": u.getY(),
				"xp": u.getExperience(), "level": u.getLevel(), "damage": u.getDamage(),
				"promos": [k for k in range(gc.getNumPromotionInfos()) if u.isHasPromotion(k)],
				"turn": gc.getGame().getGameTurn(), "created": u.getGameTurnCreated()}
		(u, it) = p.nextUnit(it, False)

def upgradeTypes(t):
	civ = gc.getCivilizationInfo(gc.getPlayer(getClaudePlayer()).getCivilizationType())
	info = gc.getUnitInfo(t)
	return [civ.getCivilizationUnits(k) for k in range(gc.getNumUnitClassInfos()) if info.getUpgradeUnitClass(k)]

def unitGone(u):
	# one of our units left the map: a real death, our own order, the game's bankruptcy rule,
	# or the built-in AI (an upgrade with our gold, or a disband in "financial trouble")
	iMe = getClaudePlayer()
	rec = g_units.pop(u.getID(), None)
	if g_killed.has_key(u.getID()):
		del g_killed[u.getID()]
		return
	if g_ownUpgrades.has_key(u.getID()):
		del g_ownUpgrades[u.getID()]
		return
	if rec is None:
		return
	now = gc.getGame().getGameTurn()
	ups = upgradeTypes(rec["type"])
	p = gc.getPlayer(iMe)
	pl = CyMap().plot(rec["x"], rec["y"])
	taken = [d.get("upgraded_to") for d in g_disbanded]
	for k in range(pl.getNumUnits()):
		v = pl.getUnit(k)
		if (v.getOwner() == iMe and v.getUnitType() in ups and v.getExperience() == rec["xp"] and v.getLevel() == rec["level"]
				and v.getGameTurnCreated() == rec["created"] and v.getID() not in taken):   # an upgrade keeps the birth turn
			rec["upgraded_to"] = v.getID()
			g_disbanded.append(rec)
			g_guardDue[0] = True
			return
	if g_window[0] != ("own", iMe):
		return   # used up by an order of ours (a settler founding, a missionary...)
	if g_strike[0] > 0:
		g_strike[0] = g_strike[0] - 1
		writeEvent("unit_disbanded", {"unit": gc.getUnitInfo(rec["type"]).getDescription(), "id": rec["id"],
			"at": [rec["x"], rec["y"]], "why": "the treasury was empty: units go unpaid and desert (the game's rule)"})
		return
	g_disbanded.append(rec)
	g_guardDue[0] = True

g_citySnap = {}

def refundGold(p, n):
	# gold the bridge gives back is no deal: the deal detector's snapshot moves with it
	p.changeGold(n)
	if g_snap[0] is not None:
		g_snap[0]["gold"] = g_snap[0]["gold"] + n

def snapCities(p):
	# our cities as our between-turns processing starts, before the city AI may hurry anything
	g_citySnap.clear()
	(c, it) = p.firstCity(False)
	while c and not c.isNone():
		h = {}
		for k in range(gc.getNumHurryInfos()):
			h[k] = (c.hurryGold(k), c.hurryPopulation(k), c.hurryAngerLength(k))
		g_citySnap[c.getID()] = {"production": c.getProduction(), "hurry": h}
		(c, it) = p.nextCity(it, False)

def undoHurry(c, h):
	# the city AI rushed a build with our gold or people (CvCityAI::AI_doHurry): put both back
	snap = g_citySnap.get(c.getID())
	if not snap or not snap["hurry"].has_key(h):
		log("hurry in %s not undone: no snapshot" % c.getName())
		return
	gold, pop, anger = snap["hurry"][h]
	c.setProduction(snap["production"])
	if gold:
		refundGold(gc.getPlayer(c.getOwner()), gold)
	if pop:
		c.changePopulation(pop)
	if anger:
		c.changeHurryAngerTimer(-anger)
	paid = [x for x in (pop and "%d population" % pop, gold and "%d gold" % gold) if x]
	writeEvent("ai_change_undone", {"undone": ["%s: its build was rushed with %s" % (c.getName(), " and ".join(paid))],
		"note": "the built-in AI rushed this build on its own; the bridge put the gold and people back (nothing to do)"})

def restoreDisbanded(p):
	if not g_disbanded or g_window[0] == ("own", getClaudePlayer()):
		return
	claims = loadClaims()
	back = []
	while g_disbanded:
		d = g_disbanded.pop(0)
		v = None
		if d.get("upgraded_to") is not None:
			v = p.getUnit(d["upgraded_to"])
			if v is None or v.isNone() or v.isDead():
				continue   # the upgraded unit is gone already; nothing to swap back
		u = p.initUnit(d["type"], d["x"], d["y"], UnitAITypes.NO_UNITAI, DirectionTypes.DIRECTION_SOUTH)
		u.setExperience(d["xp"], -1)
		u.setLevel(d["level"])
		for k in d["promos"]:
			u.setHasPromotion(k, True)
		u.setDamage(d["damage"], -1)
		what = "disbanded"
		old = d["id"]
		if v is not None:
			# the AI upgraded it with our gold: take the new unit away and pay the gold back
			price = u.upgradePrice(v.getUnitType())
			refundGold(p, price)
			what = "upgraded to %s for %d gold (gold returned)" % (gc.getUnitInfo(v.getUnitType()).getDescription(), price)
			if claims.has_key(v.getID()):
				claims[old] = claims[v.getID()]
				del claims[v.getID()]
			g_killed[v.getID()] = True   # our own undo, not a loss to undo again
			v.kill(False, -1)
		if claims.has_key(old):
			claims[u.getID()] = claims[old]
			del claims[old]
		back.append("%s #%d %s at (%d,%d), back as #%d" % (gc.getUnitInfo(d["type"]).getDescription(),
			old, what, d["x"], d["y"], u.getID()))
	snapUnits(p)
	if back:
		saveClaims(claims)
		writeEvent("ai_change_undone", {"undone": back,
			"note": "the built-in AI disbanded or upgraded these on its own; the bridge put them back (nothing to do)"})

def restoreCityQueues(p):
	# the game empties a city's queue whenever its AI re-plans production (civics, techs...), and in
	# anarchy it never asks the bridge to put Claude's list back: do it here
	d = loadCityClaims()
	(c, it) = p.firstCity(False)
	while c and not c.isNone():
		q = d.get(cityKey(c))
		if q and c.getOrderQueueLength() == 0:
			for (order, data) in q:
				c.pushOrder(OrderTypes(order), data, -1, False, False, True, False)
		(c, it) = p.nextCity(it, False)

def saveOwnChoice(p, anarchy):
	# Claude's own change: remember it, and until when its anarchy and the game's lock last
	c = loadChoices() or {}
	c.update(currentChoices(p))
	now = gc.getGame().getGameTurn()
	c["own_anarchy_until"] = now + p.getAnarchyTurns()
	if anarchy is not None:
		lock = max(1, ((100 + p.getAnarchyModifier()) * gc.getDefineINT("MIN_REVOLUTION_TURNS")) / 100) + anarchy
		c["own_lock_until"] = now + lock
	c.pop("own_anarchy", None)
	saveChoices(c)

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
	saveOwnChoice(p, None)
	return {"state_religion": religionName(p.getStateReligion()), "anarchy_turns": anarchy}

def civicsOpenedByWonder(p):
	# a wonder (The Pyramids: every Government civic) can open a whole category without its techs
	cats = [gc.getCivicOptionInfo(o).getDescription() for o in range(gc.getNumCivicOptionInfos()) if p.isHasCivicOption(o)]
	return cats and ("every %s civic is open to you without its tech: a wonder of yours grants it (e.g. The Pyramids "
		"open all Government civics)" % " and ".join(cats)) or None

def ownCivicsLock(p):
	# the game's rule after Claude's own change (anarchy, then MIN_REVOLUTION_TURNS); a lock the
	# built-in AI caused with a revolution the bridge undid doesn't count
	if engineControl():
		# the engine keeps the built-in AI out of our civics, so the game's own timers are ours, and a save
		# restores them with everything else (the bridge's record would outlive a reload)
		return max(0, p.getRevolutionTimer(), p.getAnarchyTurns())
	c = loadChoices() or {}
	now = gc.getGame().getGameTurn()
	return max(0, int(c.get("own_lock_until", 0)) - now, int(c.get("own_anarchy_until", 0)) - now)

def cmdCivics(args):
	# no names: show current civics and what we could adopt; names: switch to them
	p = gc.getPlayer(getClaudePlayer())
	cur = [p.getCivics(o) for o in range(gc.getNumCivicOptionInfos())]
	if not args.get("names"):
		r = {"current": ["%s: %s" % (gc.getCivicOptionInfo(o).getDescription(), gc.getCivicInfo(cur[o]).getDescription())
				for o in range(len(cur))],
			"can_adopt": [gc.getCivicInfo(c).getDescription() for c in range(gc.getNumCivicInfos())
				if p.canDoCivics(c) and c not in cur],
			"turns_until_allowed": ownCivicsLock(p)}
		opened = civicsOpenedByWonder(p)
		if opened:
			r["opened_without_techs"] = opened
		return r
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
	if ownCivicsLock(p) > 0:
		raise Exception("too soon to change civics again (%d turns), or in anarchy" % ownCivicsLock(p))
	anarchy = p.getCivicAnarchyLength(new)
	for o in range(len(new)):
		if new[o] != cur[o]:
			p.setCivics(o, new[o])
	if anarchy > 0:
		p.changeAnarchyTurns(anarchy)
	saveOwnChoice(p, anarchy)
	return {"civics": [gc.getCivicInfo(x).getDescription() for x in new], "anarchy_turns": anarchy}

# ------------------------------------------------- the budget slider is Claude's
#
# The built-in AI resets the gold/research/culture/espionage split every turn
# (AI_doCommerce, no hook). The game's doGold hook runs after that and before gold and
# research are counted, so the split Claude chose (`civ budget`, kept in choices.json)
# is put back there. If it would leave the treasury below zero (the game then disbands
# units), the AI's split stays for that turn and Claude is told.

def budgetNow(p):
	return [p.getCommercePercent(CommerceTypes(i)) for i in range(len(COMMERCES))]

def applyBudget(p, want):
	for k in range(3):
		for i in range(len(want)):
			if p.getCommercePercent(CommerceTypes(i)) != want[i]:
				p.setCommercePercent(CommerceTypes(i), want[i])

def budgetInfo(p):
	return {"split": ", ".join(["%s %d%%" % (COMMERCES[i], v) for i, v in enumerate(budgetNow(p)) if v or i < 2]),
		"per_turn": ", ".join(["%s %d" % (COMMERCES[i], p.getCommerceRate(CommerceTypes(i))) for i in range(len(COMMERCES))]),
		"gold": p.getGold(), "gold_change_per_turn": p.calculateGoldRate(),
		"adjustable": [COMMERCES[i] for i in range(len(COMMERCES)) if i == 0 or p.isCommerceFlexible(CommerceTypes(i))]}

def cmdBudget(args):
	# no args: the split now; "research 70 gold 30": set it (steps of 10, summing to 100); "auto": back to the AI
	p = gc.getPlayer(getClaudePlayer())
	if not args.get("set"):
		r = budgetInfo(p)
		if engineControl():
			r["chosen_by"] = "you (it stays until you change it)"
		elif (loadChoices() or {}).get("budget"):
			r["chosen_by"] = "you (kept every turn)"
		else:
			r["chosen_by"] = "the built-in AI (until you set it)"
		return r
	if [w for w in args["set"] if w.lower() == "auto"]:
		c = loadChoices() or currentChoices(p)
		if c.has_key("budget"):
			del c["budget"]
		saveChoices(c)
		r = budgetInfo(p)
		r["chosen_by"] = "the built-in AI again"
		return r
	want = [0] * len(COMMERCES)
	words = args["set"]
	for j in range(0, len(words) - 1, 2):
		k = words[j].lower()
		if k not in COMMERCES:
			raise Exception("%s? say e.g. research 70 gold 30 (also culture, espionage)" % words[j])
		want[COMMERCES.index(k)] = int(words[j + 1])
	step = gc.getDefineINT("COMMERCE_PERCENT_CHANGE_INCREMENTS")
	if sum(want) != 100 or [v for v in want if v % step or v < 0]:
		raise Exception("the split must add up to 100 in steps of %d: %s" % (step, want))
	cur = budgetNow(p)
	for i in range(len(want)):
		if i and want[i] != cur[i] and not p.isCommerceFlexible(CommerceTypes(i)):   # gold takes the rest
			raise Exception("we can't adjust %s yet (needs a tech)" % COMMERCES[i])
	c = loadChoices() or currentChoices(p)
	c["budget"] = want
	saveChoices(c)
	applyBudget(p, want)
	r = budgetInfo(p)
	if r["gold"] + r["gold_change_per_turn"] < 0:
		r["warning"] = "this split runs the treasury dry: the AI's split will be used on such turns until you change it"
	return r

def doGoldHook(gu, argsList):
	try:
		if argsList[0] == getClaudePlayer() and engineControl():
			p = gc.getPlayer(argsList[0])
			if p.getGold() + p.calculateGoldRate() < 0:
				writeEvent("treasury_empty", {"gold": p.getGold(), "per_turn": p.calculateGoldRate(),
					"note": "the treasury runs dry this turn: research stalls and unpaid units desert (raise gold in civ budget)"})
		elif argsList[0] == getClaudePlayer():
			p = gc.getPlayer(argsList[0])
			want = (loadChoices() or {}).get("budget")
			if want and want != budgetNow(p):
				before = budgetNow(p)
				applyBudget(p, want)
				if p.getGold() + p.calculateGoldRate() < 0:
					applyBudget(p, before)
					writeEvent("budget_suspended", {"note": "your split would leave us below zero gold this turn; "
						"the built-in AI's split was used instead", "split": before})
			g_strike[0] = 0
			if p.getGold() + p.calculateGoldRate() < 0 and p.getNumCities() > 0:
				g_strike[0] = (p.getStrikeTurns() + 1) / 2   # how many units the game itself disbands now
	except:
		log("doGold hook FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
	return gu._claudeOrigDoGold(argsList)

def doGoldTrampoline(argsList):
	import CvGameInterfaceFile
	B = sys.modules["ClaudeBridge"]
	return B.asSeatOf(argsList[0], B.doGoldHook, CvGameInterfaceFile.GameUtils, argsList)

# ------------------------------------------------- captured cities: keep or burn is Claude's
#
# When our units take a city, the built-in AI would decide on the spot whether to raze
# it (AI_conquerCity). The canRazeCity hook stops that: the city is kept (size-1 cities
# still burn by the game's own rule), Claude is woken (city_changed_hands) and may
# raze it with `civ raze` on that turn or the next.

g_razeOK = [False]

def canRazeHook(gu, argsList):
	iPlayer, city = argsList
	if iPlayer == getClaudePlayer() and not g_razeOK[0] and city.getHighestPopulation() > 1:
		return False
	return gu._claudeOrigCanRaze(argsList)

def canRazeTrampoline(argsList):
	import CvGameInterfaceFile
	B = sys.modules["ClaudeBridge"]
	return B.asSeatOf(argsList[0], B.canRazeHook, CvGameInterfaceFile.GameUtils, argsList)

def cmdRaze(args):
	iMe = getClaudePlayer()
	p = gc.getPlayer(iMe)
	c = findCity({"name": args["name"]})
	if c.getOwner() != iMe:
		raise Exception("%s isn't ours" % c.getName())
	if c.getPreviousOwner() in (-1, iMe) or c.getGameTurnAcquired() < gc.getGame().getGameTurn() - 1:
		raise Exception("only a city we just captured (this turn or last) can be razed")
	g_razeOK[0] = True
	try:
		if not p.canRaze(c):
			raise Exception("the game won't let us raze %s (game option, or too much of its culture is ours)" % c.getName())
		name, pop = c.getName(), c.getPopulation()
		p.raze(c)
	finally:
		g_razeOK[0] = False
	return {"razed": name, "population_was": pop}

# ------------------------------------------------- deals Claude didn't make: Claude's seal
#
# The built-in AI still answers for Claude's civ in two places the game gives no hook
# for: the human's own diplomacy screen, and deals other AI leaders propose during
# their diplomacy. Those deals can't be stopped, so they are held for Claude's seal:
# the bridge spots them (snapshots at every checkpoint: each player's turn start, each
# AI's diplomacy start, and often during the human's turn), records exactly what moved
# and wakes Claude ("native_deal" with a number). `civ ratify N` keeps the deal;
# `civ reject N` undoes it: ongoing parts are ended without the usual grudge, traded
# techs are taken back on both sides, gold is returned. Peace and vassal treaties
# can't be undone this way; Claude is told.
#
# Who traded what is read from evidence, not guessed: ongoing deals are listed by the
# game; a traded tech leaves a "traded tech to us" memory on the receiving side; gold
# between turns only moves by deals. Research or a goody hut never counts as a deal.

class PerSeat:
	# a value each agent seat has its own copy of (read and written as x[0], for the acting seat)
	def __init__(self, default):
		self.d = {}
		self.default = default
	def __getitem__(self, i):
		return self.d.get(g_acting[0], self.default)
	def __setitem__(self, i, v):
		self.d[g_acting[0]] = v

g_snap = PerSeat(None)   # this seat's deals and holdings at the last checkpoint
g_snapTick = [0]
g_turnOf = [None]   # whose turn is running (set at BeginPlayerTurn)
g_window = PerSeat(None)   # (kind, player) since this seat's last checkpoint: own, pre, diplo, human
SEAL_FILE = OUT_DIR + "\\seal.json"

def takeSnapshot():
	iMe, iTeam = myIds()
	me, team = gc.getPlayer(iMe), gc.getTeam(iTeam)
	d = {"techs": [t for t in range(gc.getNumTechInfos()) if team.isHasTech(t)], "gold": me.getGold(), "rel": {}, "theirs": {},
		"mem": {}, "deals": {},
		"researching": [t for t in range(gc.getNumTechInfos()) if me.isResearchingTech(t)]}
	for i in range(gc.getMAX_CIV_PLAYERS()):
		p = gc.getPlayer(i)
		if i == iMe or not p.isAlive() or not team.isHasMet(p.getTeam()):
			continue
		d["rel"][i] = [team.isOpenBorders(p.getTeam()), team.isDefensivePact(p.getTeam()), team.isAtWar(p.getTeam()),
			team.isVassal(p.getTeam()), gc.getTeam(p.getTeam()).isVassal(iTeam)]
		d["theirs"][i] = [t for t in range(gc.getNumTechInfos()) if gc.getTeam(p.getTeam()).isHasTech(t)]
		d["mem"][i] = [p.AI_getMemoryCount(iMe, MemoryTypes.MEMORY_TRADED_TECH_TO_US),
			me.AI_getMemoryCount(i, MemoryTypes.MEMORY_TRADED_TECH_TO_US)]
	for (deal, other, give, get) in ourDeals():
		d["deals"][deal.getID()] = [other, give, get]
	return d

def refreshSnapshot():
	try:
		g_snap[0] = takeSnapshot()
	except:
		g_snap[0] = None

def loadSeal():
	if not os.path.exists(SEAL_FILE):
		return {"next": 1, "open": {}}
	f = open(SEAL_FILE, "rb")
	try:
		return fromJson(f.read())
	finally:
		f.close()

def saveSeal(o):
	writeAtomic(SEAL_FILE, toJson(o))

# The game runs every player's upkeep (research, AI diplomacy) in one batch at the end
# of a round: BeginPlayerTurn(p) -> p's research -> p's AI_doDiplo -> next player.
# Then the players act in turn: the human first, then the others' units.
# Windows: "pre" (a player's upkeep), "diplo" (an AI's diplomacy), "own" (ours),
# "human" (the human's active turn), "active" (the others' moves after it).

def checkpoint(window):
	# a new window starts; what changed belongs to the one that just ended
	old, ended = g_snap[0], g_window[0]
	new = takeSnapshot()
	g_snap[0] = new
	g_window[0] = window
	if old is None:
		return
	kind, who = "unknown", None
	if ended:
		kind, who = ended
	if kind in ("own", "pre", "active"):
		# research, upkeep, unit moves (huts...): nobody deals with us there, but the game's
		# team AI can end a war with "another AI" (us) on its own, with no deal: CvTeamAI::AI_doWar
		findDeals(old, new, "team_ai", who, True)
		return
	findDeals(old, new, kind, who)

def checkpointTick():
	# from poll(): notice the human's turn starting and ending; check often while it runs
	hs = [i for i in humanPlayers() if gc.getPlayer(i).isTurnActive()]
	kind = g_window[0] and g_window[0][0]
	if hs and kind != "human":
		checkpoint(("human", hs[0]))
	elif not hs and kind == "human":
		checkpoint(("active", None))
	elif hs:
		g_snapTick[0] = g_snapTick[0] + 1
		if g_snapTick[0] % 40 == 0:
			checkpoint(("human", hs[0]))

def findDeals(old, new, kind, who, onlyTreaties=False):
	iMe = getClaudePlayer()
	recs = {}
	notes = []
	if onlyTreaties:
		new = dict(new)
		new["deals"], new["techs"], new["theirs"], new["mem"], new["gold"] = old["deals"], old["techs"], old["theirs"], old["mem"], old["gold"]
	def rec(i):
		if not recs.has_key(i):
			recs[i] = {"with": i, "we_gave": [], "we_got": [], "deal_ids": [], "techs_given": [], "techs_got": [],
				"gold": 0, "permanent": []}
		return recs[i]
	# ongoing deals, exactly as the game lists them
	for did, v in new["deals"].items():
		if not old["deals"].has_key(did):
			r = rec(v[0])
			r["deal_ids"].append(did)
			r["we_gave"] = r["we_gave"] + v[1]
			r["we_got"] = r["we_got"] + v[2]
	for did, v in old["deals"].items():
		if not new["deals"].has_key(did):
			notes.append("deal #%d with %s ended (we gave %s; they gave %s)" % (did, pname(v[0]), ", ".join(v[1]) or "nothing",
				", ".join(v[2]) or "nothing"))
	# techs: only with the "traded tech to us" memory as proof
	got = [t for t in new["techs"] if t not in old["techs"] and t not in old.get("researching", [])]
	for i in new["theirs"].keys():
		if not old["theirs"].has_key(i):
			continue
		dm = new["mem"][i][0] - old["mem"][i][0]
		gained = [t for t in new["theirs"][i] if t not in old["theirs"][i] and t in old["techs"]]
		if dm > 0 and gained:
			if len(gained) <= dm:
				rec(i)["techs_given"] = gained
			else:
				notes.append("%s got %s, some of it from us (can't tell which)" % (pname(i), ", ".join(techNames(gained))))
		dk = new["mem"][i][1] - old["mem"][i][1]
		mine = [t for t in got if t in old["theirs"][i]]
		if dk > 0 and mine:
			rec(i)["techs_got"] = mine[:dk]
			got = [t for t in got if t not in mine[:dk]]
	if got:
		notes.append("we also got %s (not traded: e.g. a goody hut)" % ", ".join(techNames(got)))
	# gold: between turns it only moves by deals
	dg = new["gold"] - old["gold"]
	if dg and kind in ("diplo", "human") and who is not None:
		rec(who)["gold"] = dg
	# peace and vassal treaties
	for i, rel in new["rel"].items():
		was = old["rel"].get(i)
		if was is None:
			continue
		if was[2] and not rel[2]:
			rec(i)["permanent"].append("peace with %s" % pname(i))
		if rel[3] and not was[3]:
			rec(i)["permanent"].append("we became %s's vassal" % pname(i))
		if rel[4] and not was[4]:
			rec(i)["permanent"].append("%s became our vassal" % pname(i))
	o = None
	for i, r in recs.items():
		r["we_gave"] = r["we_gave"] + techNames(r["techs_given"])
		r["we_got"] = r["we_got"] + techNames(r["techs_got"])
		if r["gold"] > 0:
			r["we_got"].append("%d gold" % r["gold"])
		elif r["gold"] < 0:
			r["we_gave"].append("%d gold" % -r["gold"])
		if not (r["we_gave"] or r["we_got"] or r["permanent"]):
			continue
		if engineControl():
			# with the engine nobody can deal for Claude: an unexplained change is a bug or a game rule
			# (a gift, a capture, a hut...) for the director to look at, not a deal for Claude to seal
			writeEvent("unexplained_change", {"with": pname(i), "window": kind, "we_gave": r["we_gave"], "we_got": r["we_got"],
				"permanent": r["permanent"], "turn": gc.getGame().getGameTurn()})
			continue
		if o is None:
			o = loadSeal()
		n = o["next"]
		o["next"] = n + 1
		r["turn"] = gc.getGame().getGameTurn()
		r["how"] = "the game's diplomacy screen"
		if kind == "diplo":
			r["how"] = "%s's proposal during their turn" % pname(i)
		elif kind == "team_ai":
			r["how"] = ("%s's AI ended the war on its own between turns (the game lets an AI do that to another "
				"AI without asking; it never does it to a human)" % pname(i))
		o["open"][str(n)] = r
		d = {"n": n, "with": pname(i), "how": r["how"], "we_gave": r["we_gave"] or ["nothing"], "we_got": r["we_got"] or ["nothing"],
			"note": "the built-in AI agreed to this for us; it waits for your seal: `civ ratify %d` keeps it, "
				"`civ reject %d` undoes it" % (n, n)}
		if [x for x in r["permanent"] if not x.startswith("peace")]:
			d["can't_be_undone"] = [x for x in r["permanent"] if not x.startswith("peace")]
		if [x for x in r["permanent"] if x.startswith("peace")]:
			d["peace"] = "rejecting it puts the war back (no grudge from anyone; but the war counts as new, so %s refuses to talk again for a while)" % pname(i)
		if notes:
			d["also"] = notes
		writeEvent("native_deal", d)
	if o is not None:
		saveSeal(o)
	elif notes and [x for x in notes if x.find("ended") >= 0]:
		writeEvent("deal_ended", {"changes": notes})

def techNames(ts):
	return [gc.getTechInfo(t).getDescription() for t in ts]

def sealLine(n, r):
	s = "#%s with %s (turn %s, %s): we gave %s; we got %s" % (n, pname(r["with"]), r.get("turn"), r.get("how"),
		", ".join(r["we_gave"]) or "nothing", ", ".join(r["we_got"]) or "nothing")
	peace = [x for x in r.get("permanent") or [] if x.startswith("peace")]
	other = [x for x in r.get("permanent") or [] if not x.startswith("peace")]
	if peace:
		s = s + "; " + ", ".join(peace) + " (reject = war again)"
	if other:
		s = s + "; can't be undone: " + ", ".join(other)
	return s

def cmdRatify(args):
	o = loadSeal()
	n = str(args["n"]).lstrip("#")
	if not o["open"].has_key(n):
		raise Exception("no deal #%s waits for your seal (see `civ offers`)" % n)
	r = o["open"][n]
	del o["open"][n]
	saveSeal(o)
	writeEvent("deal_ratified", {"n": int(n), "deal": sealLine(n, r)})
	return {"ratified": sealLine(n, r)}

def memorySnapshot():
	# every leader's memory of every other: a quiet undo must not leave grudges behind
	alive = [i for i in range(gc.getMAX_CIV_PLAYERS()) if gc.getPlayer(i).isAlive()]
	snap = {}
	for a in alive:
		for b in alive:
			if a != b:
				snap[(a, b)] = [gc.getPlayer(a).AI_getMemoryCount(b, m) for m in range(MemoryTypes.NUM_MEMORY_TYPES)]
	return snap

def memoryRestore(snap):
	for (a, b), counts in snap.items():
		for m in range(len(counts)):
			now = gc.getPlayer(a).AI_getMemoryCount(b, m)
			if now != counts[m]:
				gc.getPlayer(a).AI_changeMemoryCount(b, m, counts[m] - now)

def cmdReject(args):
	iMe = getClaudePlayer()
	me = gc.getPlayer(iMe)
	o = loadSeal()
	n = str(args["n"]).lstrip("#")
	if not o["open"].has_key(n):
		raise Exception("no deal #%s waits for your seal (see `civ offers`)" % n)
	r = o["open"][n]
	x = r["with"]
	them = gc.getPlayer(x)
	done, left = [], list(r.get("permanent") or [])
	g = gc.getGame()
	for did in r["deal_ids"]:
		deal = g.getDeal(did)
		if deal.isNone():
			left.append("deal #%d had already ended" % did)
			continue
		ob = [k for k in range(deal.getLengthFirstTrades()) if tradeName(deal.getFirstTrade(k)) == "open borders"]
		deal.kill()
		if ob:
			# the game's cancel leaves a grudge on both sides; this deal was never sealed
			for (a, b) in ((x, iMe), (iMe, x)):
				if gc.getPlayer(a).AI_getMemoryCount(b, MemoryTypes.MEMORY_CANCELLED_OPEN_BORDERS) > 0:
					gc.getPlayer(a).AI_changeMemoryCount(b, MemoryTypes.MEMORY_CANCELLED_OPEN_BORDERS, -1)
		done.append("ended deal #%d" % did)
	for t in r["techs_got"]:
		if gc.getTeam(me.getTeam()).isHasTech(t):
			gc.getTeam(me.getTeam()).setHasTech(t, False, iMe, False, False)
			if me.AI_getMemoryCount(x, MemoryTypes.MEMORY_TRADED_TECH_TO_US) > 0:
				me.AI_changeMemoryCount(x, MemoryTypes.MEMORY_TRADED_TECH_TO_US, -1)
			done.append("gave back %s" % gc.getTechInfo(t).getDescription())
	for t in r["techs_given"]:
		if gc.getTeam(them.getTeam()).isHasTech(t):
			gc.getTeam(them.getTeam()).setHasTech(t, False, x, False, False)
			if them.AI_getMemoryCount(iMe, MemoryTypes.MEMORY_TRADED_TECH_TO_US) > 0:
				them.AI_changeMemoryCount(iMe, MemoryTypes.MEMORY_TRADED_TECH_TO_US, -1)
			done.append("took back %s" % gc.getTechInfo(t).getDescription())
	if r["gold"] > 0:
		back = min(r["gold"], me.getGold())
		me.changeGold(-back)
		them.changeGold(back)
		done.append("returned %d gold" % back)
	elif r["gold"] < 0:
		back = min(-r["gold"], them.getGold())
		them.changeGold(-back)
		me.changeGold(back)
		done.append("got back %d gold" % back)
	for x2 in [x2 for x2 in left if x2.startswith("peace")]:
		left.remove(x2)
		tt = them.getTeam()
		if gc.getTeam(me.getTeam()).isAtWar(tt):
			done.append("already at war with %s" % pname(x))
		else:
			mem = memorySnapshot()
			gc.getTeam(me.getTeam()).declareWar(tt, False, WarPlanTypes.WARPLAN_TOTAL)
			memoryRestore(mem)
			done.append("war with %s again (the peace was never ours)" % pname(x))
	del o["open"][n]
	saveSeal(o)
	refreshSnapshot()
	line = sealLine(n, r)
	writeEvent("deal_rejected", {"n": int(n), "deal": line, "undone": done, "not_undone": left})
	if them.isHuman():
		msg = u"<font=4><color=255,200,60,255>%s refuses to seal the deal his ministers made with you: %s</color></font>" % (
			me.getName(), "; ".join(done) or "nothing to undo")
		CyInterface().addMessage(x, True, gc.getEVENT_MESSAGE_TIME() * 3, msg, "",
			InterfaceMessageTypes.MESSAGE_TYPE_MAJOR_EVENT, "", -1, -1, -1, False, False)
	return {"rejected": line, "undone": done or ["nothing"], "not_undone": left or ["nothing"]}

# ------------------------------------------------- ongoing deals: list and cancel

TRADE_NAMES = {}

def tradeName(t):
	if not TRADE_NAMES:
		for k in dir(TradeableItems):
			if k.startswith("TRADE_"):
				TRADE_NAMES[int(getattr(TradeableItems, k))] = k[6:].lower()
	kind = TRADE_NAMES.get(int(t.ItemType), "item %d" % int(t.ItemType))
	if kind == "technologies":
		return "tech " + gc.getTechInfo(t.iData).getDescription()
	if kind == "resources":
		return gc.getBonusInfo(t.iData).getDescription()
	if kind in ("gold", "gold_per_turn"):
		return "%d %s" % (t.iData, kind.replace("_", " "))
	if kind == "cities":
		return "a city"
	return kind.replace("_", " ")

def ourDeals():
	iMe = getClaudePlayer()
	g = gc.getGame()
	out = []
	for i in range(g.getIndexAfterLastDeal()):
		d = g.getDeal(i)
		if d.isNone() or iMe not in (d.getFirstPlayer(), d.getSecondPlayer()):
			continue
		first = [tradeName(d.getFirstTrade(j)) for j in range(d.getLengthFirstTrades())]
		second = [tradeName(d.getSecondTrade(j)) for j in range(d.getLengthSecondTrades())]
		if d.getFirstPlayer() == iMe:
			other, give, get = d.getSecondPlayer(), first, second
		else:
			other, give, get = d.getFirstPlayer(), second, first
		out.append((d, other, give, get))
	return out

def dealCancelState(d, give, get):
	if [x for x in give + get if x in ("peace treaty", "vassal", "surrender")]:
		return "can't be cancelled (peace treaties run out by themselves; vassal deals aren't supported)"
	left = d.getInitialGameTurn() + gc.getDefineINT("PEACE_TREATY_LENGTH") - gc.getGame().getGameTurn()
	if left > 0:
		return "can be cancelled in %d turns" % left
	return "can be cancelled now"

def dealLine(d, other, give, get):
	return "#%d with %s since turn %d: we give %s; they give %s (%s)" % (d.getID(), pname(other), d.getInitialGameTurn(),
		", ".join(give) or "nothing", ", ".join(get) or "nothing", dealCancelState(d, give, get))

def cmdDeals(args):
	return {"deals": [dealLine(*x) for x in ourDeals()] or ["none"]}

def cmdCancel(args):
	# end an ongoing deal by its number or by the other player, like the diplomacy screen's "cancel deal"
	want = unicode(args["what"]).strip().lstrip("#")
	deals = ourDeals()
	pick = [x for x in deals if str(x[0].getID()) == want]
	if not pick:
		other = findPlayer(want)
		pick = [x for x in deals if x[1] == other]
		if not pick:
			raise Exception("no ongoing deal with %s" % pname(other))
		if len(pick) > 1:
			raise Exception("several deals with %s, name one by its number: %s" % (pname(other),
				"; ".join([dealLine(*x) for x in pick])))
	d, other, give, get = pick[0]
	state = dealCancelState(d, give, get)
	if state != "can be cancelled now":
		raise Exception("deal #%d %s" % (d.getID(), state))
	line = dealLine(d, other, give, get)
	d.kill()   # the game's own cancel: both sides are told, the other leader remembers it
	refreshSnapshot()
	writeEvent("deal_cancelled", {"deal": line, "by": pname(getClaudePlayer())})
	return {"cancelled": line}

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
		if p.isAlive() and (str(i) == w or realName(i).lower().startswith(w)
				or p.getCivilizationShortDescription(0).lower().startswith(w)):
			return i
	raise Exception("no player called %s" % want)

def parseItem(text, owner):
	# `owner` gives the item: a city is named among its cities (a city's number is only unique per player)
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
	if kind in ("open_borders", "defensive_pact", "peace", "map", "permanent_alliance", "vassal", "surrender"):
		return (kind, -1)
	if kind in TEAM_ITEMS:
		return (kind, findPlayer(arg))
	if kind == "gold_per_turn":
		return (kind, int(arg))
	if kind == "resource":
		i = findInfo(arg, gc.getNumBonusInfos(), gc.getBonusInfo, "bonus_")
		if i < 0:
			raise Exception("no resource called %s" % arg)
		return (kind, i)
	if kind == "civic":
		i = findInfo(arg, gc.getNumCivicInfos(), gc.getCivicInfo, "civic_")
		if i < 0:
			raise Exception("no civic called %s" % arg)
		return (kind, i)
	if kind == "religion":
		i = findInfo(arg, gc.getNumReligionInfos(), gc.getReligionInfo, "religion_")
		if i < 0:
			raise Exception("no religion called %s" % arg)
		return (kind, i)
	if kind == "city":
		for i in range(gc.getMAX_CIV_PLAYERS()):
			(c, it) = gc.getPlayer(i).firstCity(False)
			while c and not c.isNone():
				if c.getName().lower() == arg.strip():
					if i != owner:
						raise Exception("%s is not %s's city to give: it belongs to %s" % (c.getName(), pname(owner), pname(i)))
					return (kind, c.getID())
				(c, it) = gc.getPlayer(i).nextCity(it, False)
		raise Exception("no city called %s" % arg)
	raise Exception("unknown deal item %s (tech:<name>, gold:<n>, gold_per_turn:<n>, resource:<name>, city:<name>, map, open_borders, "
		"defensive_pact, permanent_alliance, peace, war:<player>, peace_with:<player>, embargo:<player>, civic:<name>, religion:<name>, vassal, surrender)" % text)

def itemText(it, owner):
	# `owner` is the player who gives the item: a city's number means a city only among its owner's cities
	kind, d = it
	if kind == "tech":
		return gc.getTechInfo(d).getDescription()
	if kind == "gold":
		return "%d gold" % d
	if kind == "war":
		return "war on " + pname(d)
	if kind == "peace_with":
		return "peace with " + pname(d)
	if kind == "embargo":
		return "stop trading with " + pname(d)
	if kind == "gold_per_turn":
		return "%d gold per turn" % d
	if kind == "resource":
		return gc.getBonusInfo(d).getDescription()
	if kind == "civic":
		return "switch to " + gc.getCivicInfo(d).getDescription()
	if kind == "religion":
		return "convert to " + gc.getReligionInfo(d).getDescription()
	if kind == "city":
		if owner is None or owner < 0:
			return "a city"
		c = gc.getPlayer(owner).getCity(d)
		if c and not c.isNone():
			return "the city of " + c.getName()
		return "a city %s no longer holds" % pname(owner)
	if kind == "other":
		return "a trade item of type %d" % d
	return kind.replace("_", " ")

TRADE_TYPES = {"tech": "TRADE_TECHNOLOGIES", "gold": "TRADE_GOLD", "open_borders": "TRADE_OPEN_BORDERS",
	"defensive_pact": "TRADE_DEFENSIVE_PACT", "peace": "TRADE_PEACE_TREATY", "war": "TRADE_WAR",
	"peace_with": "TRADE_PEACE", "resource": "TRADE_RESOURCES", "city": "TRADE_CITIES",
	"gold_per_turn": "TRADE_GOLD_PER_TURN", "map": "TRADE_MAPS", "vassal": "TRADE_VASSAL",
	"surrender": "TRADE_SURRENDER", "permanent_alliance": "TRADE_PERMANENT_ALLIANCE",
	"embargo": "TRADE_EMBARGO", "civic": "TRADE_CIVIC", "religion": "TRADE_RELIGION"}
TEAM_ITEMS = ("war", "peace_with", "embargo")   # their data is a team in the game, a player here
DATA_ITEMS = ("tech", "gold", "resource", "city", "gold_per_turn", "civic", "religion")

def engineText(items):
	# items as the CIVAI engine reads them: "item:data,..." (TradeableItems numbers)
	out = []
	for it in items:
		t = tradeData(it)
		out.append("%d:%d" % (int(t.ItemType), t.iData))
	return ",".join(out)

def fromEngineText(text):
	kinds = {}
	for k, name in TRADE_TYPES.items():
		kinds[int(getattr(TradeableItems, name))] = k
	out = []
	for part in (text or "").split(","):
		if ":" not in part:
			continue
		t, d = [int(x) for x in part.split(":")]
		k = kinds.get(t)
		if k is None:
			out.append(("other", t))
			continue
		if k in TEAM_ITEMS:
			d = gc.getTeam(d).getLeaderID()
		elif k not in DATA_ITEMS:
			d = -1
		out.append((k, d))
	return out

def tradeData(it):
	kind, d = it
	t = TradeData()
	t.ItemType = getattr(TradeableItems, TRADE_TYPES[kind])
	if kind in TEAM_ITEMS:
		t.iData = gc.getPlayer(d).getTeam()
	elif kind in DATA_ITEMS:
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
		if kind == "tech":
			gt, tt = gc.getTeam(g.getTeam()), gc.getTeam(t.getTeam())
			if not gt.isTechTrading() and not tt.isTechTrading():
				why = "tech trading needs Alphabet on at least one side"
			elif not t.canResearch(d, True):
				why = "%s can't take it now (already has it, or lacks a tech it needs first)" % pname(taker)
			elif giver == getClaudePlayer() and gt.isNoTradeTech(d):
				why = "you received it in a trade this turn; the game lets a traded tech be passed on from the next turn"
			else:
				# the other side's reason stays theirs: only the rules that can stand in the way
				why = "the game doesn't allow it now (a tech received in a trade can be passed on only from the next turn)"
			raise Exception("%s can't give %s to %s: %s" % (pname(giver), itemText(it, giver), pname(taker), why))
		raise Exception("%s can't give %s to %s under the game's rules (e.g. open borders need contact and no war...)"
			% (pname(giver), itemText(it, giver), pname(taker)))

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
	elif kind == "peace_with":
		gc.getTeam(g.getTeam()).makePeace(gc.getPlayer(d).getTeam())

def itemValue(owner, it, taker=-1):
	kind, d = it
	if kind == "tech":
		return gc.getTeam(gc.getPlayer(owner).getTeam()).getResearchCost(d)
	if kind == "gold":
		return d
	if kind == "peace_with" and taker >= 0:
		return makePeaceTradeVal(d, taker)
	return 0

def makePeaceTradeVal(peace, taker):
	# the game's CvTeamAI::AI_makePeaceTradeVal: what making peace with `peace` is worth to the AI
	# when `taker` asks for it (dearer the more the two hate each other, cheaper the longer the war)
	pe, ta = gc.getPlayer(peace), gc.getPlayer(taker)
	v = 50 + gc.getGame().getGameTurn() + (gc.getTeam(ta.getTeam()).getNumCities() + gc.getTeam(pe.getTeam()).getNumCities()) * 8
	att = (ta.AI_getAttitude(peace) + pe.AI_getAttitude(taker)) / 2
	v = v * (100 + {0: 400, 1: 200, 2: 100, 3: 50}.get(att, 0)) / 100
	v = v * 40 / (gc.getTeam(ta.getTeam()).AI_getAtWarCounter(pe.getTeam()) + 10)
	return v - v % gc.getDefineINT("DIPLOMACY_VALUE_REMAINDER")

def warDeclaredBy(a, b):
	# which side declared the current war between teams a and b (from our own event log)
	names = (teamName(a), teamName(b))
	found = []   # (turn, declaring team) in log order; a reload drops the declarations of its abandoned turns
	try:
		for line in open(EVENTS_FILE):
			if '"rewind"' not in line and '"war_declared"' not in line:
				continue
			try:
				e = fromJson(line)
			except:
				continue
			if e.get("kind") == "rewind":
				found = [x for x in found if x[0] < e.get("to_turn", 10 ** 6)]
			elif e.get("kind") == "war_declared" and e.get("team") in names and e.get("against") in names:
				found.append((e.get("turn", 0), e.get("team")))
	except:
		pass
	who = found and found[-1][1] or None
	if who == names[0]:
		return a
	if who == names[1]:
		return b
	return -1

def aiWillingToTalk(ai, me):
	# the game's CvPlayerAI::AI_isWillingToTalk: whether the AI opens the diplomacy screen at all
	p = gc.getPlayer(ai)
	t, o = p.getTeam(), gc.getPlayer(me).getTeam()
	team = gc.getTeam(t)
	if team.isAtWar(o):
		dur = gc.getLeaderHeadInfo(p.getPersonalityType()).getRefuseToTalkWarThreshold()
		if warDeclaredBy(t, o) == t:
			dur *= 2          # a war they chose themselves
		ours = 1 + team.AI_getWarSuccess(o)
		theirs = 1 + gc.getTeam(o).AI_getWarSuccess(t)
		if theirs > ours * 2:
			dur = dur * (20 + (80 * ours * 2) / theirs) / 100
		if team.AI_getAtWarCounter(o) < dur or team.isAVassal():
			return False
	elif p.AI_getMemoryCount(me, MemoryTypes.MEMORY_STOPPED_TRADING_RECENT) > 0:
		return False
	return True

def aiDenial(ai, me, get):
	# the game's refusals by item (getTradeDenial), e.g. "we don't want to trade that"
	p = gc.getPlayer(ai)
	for it in get:
		if it[0] == "peace":
			continue
		den = p.getTradeDenial(me, tradeData(it))
		if den != DenialTypes.NO_DENIAL:
			return False, "%s refuses to give %s (%s)" % (pname(ai), itemText(it, ai), gc.getDenialInfo(den).getDescription())
	return True, "accepted"

def aiAccepts(ai, me, give, get):
	# give = what Claude gives the AI, get = what the AI gives Claude; follows the game's
	# CvPlayerAI::AI_considerOffer: refusals by item (getTradeDenial), then value
	p = gc.getPlayer(ai)
	for it in get:
		if it[0] == "peace":
			continue      # the game has no refusal for a peace treaty itself
		den = p.getTradeDenial(me, tradeData(it))
		if den != DenialTypes.NO_DENIAL:
			return False, "%s refuses to give %s (%s)" % (pname(ai), itemText(it, ai), gc.getDenialInfo(den).getDescription())
	vin = sum([itemValue(ai, it) for it in give])
	vout = sum([itemValue(ai, it, me) for it in get])
	if vout > vin * 1.1 + 10:
		return False, "%s finds it unfair: gives about %d, gets about %d" % (pname(ai), vout, vin)
	return True, "accepted"

def executeDeal(a, b, giveA, giveB):
	for it in giveA:
		checkItem(a, b, it)
	for it in giveB:
		checkItem(b, a, it)
	if engineReady():
		# the game's own CvGame::implementDeal: ongoing items become real deals, memories as usual
		if not gc.getPlayer(a).implementDealText(b, engineText(giveA), engineText(giveB)):
			raise Exception("the game refused the deal")
	else:
		for it in giveA:
			doItem(a, b, it)
		for it in giveB:
			doItem(b, a, it)
	# a deal made through CIVAI is explained for both sides: each agent's own snapshot takes it in (else
	# the other agent saw it as an unexplained change, e.g. a peace it had agreed to)
	refreshSnapshot()
	for x in (a, b):
		if isAgent(x):
			asSeatOf(x, refreshSnapshot)

DUAL_ITEMS = ("open_borders", "defensive_pact", "permanent_alliance", "peace")   # the game's two-way treaties

def cmdOffer(args):
	noteAct("offer", None)
	return cmdOfferInner(args)

def cmdOfferInner(args):
	iMe, iTeam = myIds()
	other = findPlayer(args["player"])
	if other == iMe:
		raise Exception("that's us")
	if not gc.getTeam(iTeam).isHasMet(gc.getPlayer(other).getTeam()):
		raise Exception("we haven't met %s" % args["player"])
	give = [parseItem(x, iMe) for x in args.get("give") or []]
	get = [parseItem(x, other) for x in args.get("get") or []]
	if not give and not get:
		raise Exception("an offer needs something to give or to get")
	# treaties are two-way, as on the game's trade screen (adding one on either side puts it on both)
	for it in [x for x in give + get if x[0] in DUAL_ITEMS]:
		if it not in give:
			give.append(it)
		if it not in get:
			get.append(it)
	for it in give:
		checkItem(iMe, other, it)
	for it in get:
		checkItem(other, iMe, it)
	atWar = gc.getTeam(iTeam).isAtWar(gc.getPlayer(other).getTeam())
	kinds = [x[0] for x in give + get]
	if atWar and engineReady() and "peace" not in kinds and "surrender" not in kinds:
		raise Exception("we are at war with %s: any deal with them ends the war by the game's rule. Put peace in the "
			"deal (--give peace --get peace ...) if you want that" % pname(other))
	agent = isAgent(other)
	if not gc.getPlayer(other).isHuman() and not agent and not aiWillingToTalk(other, iMe):
		why = "%s refuses to talk to us for now (the game's diplomacy screen stays closed); try again in a later turn" % pname(other)
		if gc.getTeam(iTeam).isAtWar(gc.getPlayer(other).getTeam()):
			why += ". At war, a leader refuses to talk for a while after the war begins; war success shortens it"
		writeEvent("deal_refused", {"with": pname(other), "why": why})
		return {"done": False, "why": why}
	if not get and "vassal" not in kinds and "surrender" not in kinds:
		# a gift needs no answer (becoming someone's vassal does: the master must accept it)
		executeDeal(iMe, other, give, [])
		writeEvent("deal_done", {"with": pname(other), "gave": [itemText(x, iMe) for x in give], "got": []})
		if agent:
			prev = actAs(other)
			try:
				writeEvent("gift_received", {"from": pname(iMe), "got": [itemText(x, iMe) for x in give]})
			finally:
				actAs(prev)
		if gc.getPlayer(other).isHuman():
			CyInterface().addMessage(other, True, gc.getEVENT_MESSAGE_TIME() * 3,
				u"<font=4><color=255,200,60,255>%s gives you: %s</color></font>" % (gc.getPlayer(iMe).getName(),
				", ".join([itemText(x, iMe) for x in give])), "", InterfaceMessageTypes.MESSAGE_TYPE_MAJOR_EVENT, "", -1, -1, -1, False, False)
		return {"done": True, "gave": [itemText(x, iMe) for x in give]}
	if agent:
		# another agent decides for itself: the offer waits in its proposals (civ answer N yes|no)
		prev = actAs(other)
		try:
			newProposal(iMe, "agent_offer", 0, give, get)
			n = loadProposals()["next"] - 1
		finally:
			actAs(prev)
		writeEvent("deal_offered", {"to": pname(other), "their_number": n, "give": [itemText(x, iMe) for x in give],
			"get": [itemText(x, other) for x in get]})
		return {"offer": "sent", "waiting_for": pname(other), "note": "they answer in their own time; you hear it as an event"}
	if not gc.getPlayer(other).isHuman():
		if engineReady():
			# the AI's own answer (CvPlayerAI::AI_considerOffer), as on the diplomacy screen
			ok, why = aiDenial(other, iMe, get)
			if ok and (get or give) and not gc.getPlayer(other).AI_considerOfferText(iMe, engineText(give), engineText(get)):
				ok, why = False, "%s turns it down (not worth it to them)" % pname(other)
		else:
			ok, why = aiAccepts(other, iMe, give, get)
		if not ok:
			writeEvent("deal_refused", {"with": pname(other), "why": why})
			return {"done": False, "why": why}
		executeDeal(iMe, other, give, get)
		writeEvent("deal_done", {"with": pname(other), "gave": [itemText(x, iMe) for x in give], "got": [itemText(x, other) for x in get]})
		return {"done": True, "gave": [itemText(x, iMe) for x in give], "got": [itemText(x, other) for x in get]}
	o = loadOffers()
	n = o["next"]
	o["next"] = n + 1
	o["open"][str(n)] = {"from": iMe, "to": other, "give": [list(x) for x in give], "get": [list(x) for x in get],
		"turn": gc.getGame().getGameTurn()}
	saveOffers(o)
	line = u"<font=4><color=255,200,60,255>%s offers a deal #%d - you get: %s; he gets: %s. Answer in the window (or type !accept %d / !decline %d in chat).</color></font>" % (
		gc.getPlayer(iMe).getName(), n, ", ".join([itemText(x, iMe) for x in give]) or "nothing",
		", ".join([itemText(x, other) for x in get]), n, n)
	CyInterface().addMessage(other, True, gc.getEVENT_MESSAGE_TIME() * 4, line, "",
		InterfaceMessageTypes.MESSAGE_TYPE_MAJOR_EVENT, "", -1, -1, -1, False, False)
	dealPopup(n, iMe, other, give, get)
	writeEvent("deal_offered", {"id": n, "to": pname(other), "give": [itemText(x, iMe) for x in give], "get": [itemText(x, other) for x in get]})
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
	writeEvent("deal_done", {"id": int(n), "with": pname(human), "gave": [itemText(x, d["from"]) for x in give], "got": [itemText(x, d["to"]) for x in get]})
	CyInterface().addImmediateMessage(u"Deal #%s done." % n, "")

DEAL_EVENT_ID = 5918

def dealPopup(n, fromPlayer, toPlayer, give, get):
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
	popup.setBodyString(u"You receive: %s\n\n%s receives: %s" % (", ".join([itemText(x, fromPlayer) for x in give]) or u"nothing",
		p.getName(), ", ".join([itemText(x, toPlayer) for x in get]) or u"nothing"))
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

# ------------------------------------------------- who plays which leader: picked in the game
#
# With "players = auto" in config.txt, the human picks at the start, leader by leader, which AI plays it
# (a popup with the leader's portrait). The picks go to models.json; newgame.py starts those models, and the
# screen then shows each model's name. Until a leader is picked nothing is decided for it.
MODEL_EVENT_ID = 5919
MODELS_FILE = OUT_DIR + "\\models.json"
MODEL_CHOICES = [("opus", u"Claude Opus"), ("sonnet", u"Claude Sonnet"), ("gpt", u"GPT-5.6 Luna"),
	("deepseek", u"DeepSeek V4.1 Flash"), ("builtin", u"Civ IV AI (the game's own)")]
g_modelAsk = {"pending": -1}
g_modelsCache = {"stamp": None, "data": {}}

def loadModels():
	# read often (every seat lookup): re-read only when the file changes
	try:
		if not os.path.exists(MODELS_FILE):
			return {}
		st = os.stat(MODELS_FILE)
		stamp = (st.st_mtime, st.st_size)
		if stamp != g_modelsCache["stamp"]:
			g_modelsCache["data"] = fromJson(open(MODELS_FILE).read()) or {}
			g_modelsCache["stamp"] = stamp
		return dict(g_modelsCache["data"])
	except:
		log("models.json unreadable:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
	return {}

def saveModels(d):
	f = open(MODELS_FILE, "w")
	f.write(toJson(d))
	f.close()

def pickablePlayers():
	out = []
	for i in range(gc.getMAX_CIV_PLAYERS()):
		p = gc.getPlayer(i)
		if p.isEverAlive() and not p.isHuman() and not p.isBarbarian() and not p.isMinorCiv():
			out.append(i)
	return out

def askModels():
	v = configValue("players")
	if not v or v.strip() != "auto" or g_modelAsk["pending"] >= 0 or not humanPlayers():
		return
	d = loadModels()
	todo = [i for i in pickablePlayers() if not d.has_key(str(i))]
	if not todo:
		if not d.get("done"):
			d["done"] = True
			saveModels(d)
			names = [u"%s: %s" % (realName(i), dict(MODEL_CHOICES)[d[str(i)]]) for i in pickablePlayers()]
			CyInterface().addImmediateMessage(u"Players picked. " + u", ".join(names) + u". The models join in a moment.", "")
			log("models picked: %s" % toJson(d))
		return
	i = todo[0]
	p = gc.getPlayer(i)
	import Popup as PyPopup
	popup = PyPopup.PyPopup(MODEL_EVENT_ID, EventContextTypes.EVENTCONTEXT_ALL)
	popup.setHeaderString(u"Who plays %s?" % realName(i))
	try:
		popup.addDDS(gc.getLeaderHeadInfo(p.getLeaderType()).getButton(), 0, 0, 64, 64)
	except:
		pass
	popup.setBodyString(u"%s of %s. Pick the AI that plays this leader for the whole game." % (realName(i), p.getCivilizationDescription(0)))
	for key, label in MODEL_CHOICES:
		popup.addButton(label)
	popup.setUserData((i,))
	g_modelAsk["pending"] = i
	popup.launch(False)

def modelApply(playerID, userData, popupReturn):
	i = userData[0]
	k = popupReturn.getButtonClicked()
	if k >= 0 and k < len(MODEL_CHOICES):
		d = loadModels()
		d[str(i)] = MODEL_CHOICES[k][0]
		saveModels(d)
	g_modelAsk["pending"] = -1
	return 0

def modelApplyTrampoline(playerID, userData, popupReturn):
	return sys.modules["ClaudeBridge"].modelApply(playerID, userData, popupReturn)

def modelBeginTrampoline(argsList=-1):
	return 0

def dealApplyTrampoline(playerID, userData, popupReturn):
	return sys.modules["ClaudeBridge"].dealApply(playerID, userData, popupReturn)

def dealBeginTrampoline(argsList=-1):
	return 0

# ------------------------------------------------- the CIVAI engine: Claude decides
#
# With the CIVAI game engine (CvGameCoreDLL built from ~/civai-sdk/src/claude), Claude's civ is
# flagged (CyPlayer.setClaude) and the built-in AI makes no choices for it: research, budget,
# civics, religion, upgrades, promotions, rushing, disbanding, deals, war and peace. Units and
# cities Claude hasn't claimed stay with the game's automation (like a human's automated workers).
# AI leaders ask instead of deciding for him: their proposals, demands and requests arrive as the
# game event "claudeDiplomacy", offers made to him (the human's diplomacy screen) as "claudeOffered".
# They wait in proposals.json until Claude answers (`civ answer`) or the next turn ends.

PROPOSALS_FILE = OUT_DIR + "\\proposals.json"
g_engineOn = [False]

def engineReady():
	return hasattr(gc.getPlayer(0), "setClaude")

def engineControl():
	return g_engineOn[0]

def ensureEngineControl():
	iMe = getClaudePlayer()
	if (configValue("player") is None and not seatsConfigured()) or iMe < 0 or not engineReady():
		g_engineOn[0] = False
		return
	p = gc.getPlayer(iMe)
	if not p.isClaude():
		p.setClaude(True)
		log("engine control on for player %d" % iMe)
		if not g_engineOn[0]:
			writeEvent("engine_control", {"note": "the built-in AI makes no choices for your civ any more; "
				"AI leaders ask you (civ proposals / civ answer)"})
	g_engineOn[0] = True

def loadProposals():
	if not os.path.exists(PROPOSALS_FILE):
		return {"next": 1, "open": {}}
	f = open(PROPOSALS_FILE, "rb")
	try:
		return fromJson(f.read())
	finally:
		f.close()

def saveProposals(o):
	writeAtomic(PROPOSALS_FILE, toJson(o))

def commentName(i):
	try:
		return gc.getDiplomacyInfo(i).getType().replace("AI_DIPLOCOMMENT_", "").lower()
	except:
		return "comment_%d" % i

# what each request means and which answers the game records (CvDiplomacy.py, CvPlayer::handleDiploEvent)
ANSWERS = {
	"ask_for_help": ("DIPLOEVENT_GIVE_HELP", "DIPLOEVENT_REFUSED_HELP"),
	"demand_tribute": ("DIPLOEVENT_ACCEPT_DEMAND", "DIPLOEVENT_REJECTED_DEMAND"),
	"religion_pressure": ("DIPLOEVENT_CONVERT", "DIPLOEVENT_NO_CONVERT"),
	"civic_pressure": ("DIPLOEVENT_REVOLUTION", "DIPLOEVENT_NO_REVOLUTION"),
	"join_war": ("DIPLOEVENT_JOIN_WAR", "DIPLOEVENT_NO_JOIN_WAR"),
	"stop_trading": ("DIPLOEVENT_STOP_TRADING", "DIPLOEVENT_NO_STOP_TRADING"),
}
TRADES = ("offer_deal", "offer_peace", "offer_city", "offer_vassal", "give_help", "screen_offer", "agent_offer")

def proposalText(v):
	if v["comment"] == "vote":
		return voteText(v)
	if v["comment"] == "election":
		return "As Resident of %s you choose the resolution put to the vote: %s" % (v["source"],
			"; ".join(["%d: %s" % (k + 1, x) for k, x in enumerate(v["options"])]))
	if v["comment"] in ("event", "free_tech"):
		return choiceText(v)
	who = pname(v["from"])
	gives = ", ".join([itemText(tuple(x), v["from"]) for x in v["gives"]]) or "nothing"
	wants = ", ".join([itemText(tuple(x), getClaudePlayer()) for x in v["wants"]]) or "nothing"
	c = v["comment"]
	if c == "screen_offer":
		return "%s offers on the diplomacy screen: you get %s; they get %s" % (who, gives, wants)
	if c == "agent_offer":
		return "%s offers a deal: you get %s; they get %s" % (who, gives, wants)
	if c == "offer_peace":
		return "%s offers peace: you get %s; they get %s" % (who, gives, wants)
	if c in ("offer_deal", "offer_city", "offer_vassal"):
		return "%s offers a deal: you get %s; they get %s" % (who, gives, wants)
	if c == "give_help":
		return "%s offers help as a gift: %s" % (who, gives)
	if c == "ask_for_help":
		return "%s asks for help: %s" % (who, wants)
	if c == "demand_tribute":
		return "%s demands tribute: %s (refusing may mean war)" % (who, wants)
	if c == "religion_pressure":
		return "%s asks you to convert to %s" % (who, religionName(gc.getPlayer(v["from"]).getStateReligion()))
	if c == "civic_pressure":
		fav = gc.getLeaderHeadInfo(gc.getPlayer(v["from"]).getPersonalityType()).getFavoriteCivic()
		return "%s asks you to switch to %s" % (who, fav >= 0 and gc.getCivicInfo(fav).getDescription() or "their civic")
	if c == "join_war":
		return "%s asks you to join their war on %s" % (who, teamName(v["data"]))
	if c == "stop_trading":
		return "%s asks you to stop trading with %s" % (who, teamName(v["data"]))
	if c == "cancel_deal":
		return "%s cancels a deal with you: %s / %s" % (who, gives, wants)
	return "%s says something (%s)" % (who, c)

g_iconNames = {}

def iconNames():
	# the game's font draws icons with private characters: name them (gold, research, happiness...)
	if not g_iconNames:
		for i in range(CommerceTypes.NUM_COMMERCE_TYPES):
			g_iconNames[unichr(gc.getCommerceInfo(i).getChar())] = u" " + gc.getCommerceInfo(i).getDescription().lower()
		for i in range(YieldTypes.NUM_YIELD_TYPES):
			g_iconNames[unichr(gc.getYieldInfo(i).getChar())] = u" " + gc.getYieldInfo(i).getDescription().lower()
		for name, word in (("HAPPY_CHAR", u" happiness"), ("UNHAPPY_CHAR", u" unhappiness"), ("HEALTHY_CHAR", u" health"),
				("UNHEALTHY_CHAR", u" unhealthiness"), ("BULLET_CHAR", u""), ("STRENGTH_CHAR", u" strength"),
				("MOVES_CHAR", u" moves"), ("RELIGION_CHAR", u" religion"), ("GREAT_PEOPLE_CHAR", u" great people"),
				("ANGRY_POP_CHAR", u" angry citizens"), ("TRADE_CHAR", u" trade"), ("DEFENSE_CHAR", u" defence")):
			try:
				g_iconNames[unichr(CyGame().getSymbolID(getattr(FontSymbols, name)))] = word
			except:
				pass
	return g_iconNames

def stripTags(t):
	# game text carries markup such as <color=...> and [ICON_GOLD]; keep the words, name the icons
	t = re.sub(u"<[^>]*>|\\[[A-Z_]+\\]", u"", t)
	for ch, word in iconNames().items():
		t = t.replace(ch, word)
	return t

def newProposal(frm, comment, data, gives, wants):
	gives = [list(x) for x in gives]   # stored as JSON lists: compare in the same form
	wants = [list(x) for x in wants]
	o = loadProposals()
	for k, v in o["open"].items():
		if v["from"] == frm and v["comment"] == comment and v["gives"] == gives and v["wants"] == wants:
			return   # the same offer again (the diplomacy screen asks more than once)
	v = {"from": frm, "comment": comment, "data": data, "gives": gives, "wants": wants,
		"turn": gc.getGame().getGameTurn()}
	needs = comment in TRADES or ANSWERS.has_key(comment)
	if not needs:
		writeEvent("diplomacy", {"text": proposalText(v)})
		return
	n = o["next"]
	o["next"] = n + 1
	o["open"][str(n)] = v
	saveProposals(o)
	writeEvent("proposal", {"id": n, "text": proposalText(v),
		"answer": "civ answer %d yes|no (open until the end of next turn)" % n})

def closeNote(o, n, why):
	# remembered for a while, so a late answer learns what happened to it
	c = o.setdefault("closed", {})
	c[str(n)] = why
	for k in sorted(c.keys(), lambda a, b: cmp(int(a), int(b)))[:-30]:
		del c[k]

def answerProposal(n, yes, why=None):
	iMe = getClaudePlayer()
	o = loadProposals()
	v = o["open"].get(str(n))
	if v is None:
		closed = (o.get("closed") or {}).get(str(n))
		if closed:
			raise Exception("proposal #%s is closed: %s (civ proposals lists the open ones)" % (n, closed))
		openNow = ["#%s %s" % (k, x.get("comment") == "election" and "(choose the resolution: civ answer %s <option number>)" % k
			or "(civ answer %s yes|no)" % k) for k, x in o["open"].items()]
		raise Exception("no proposal #%s. Its number is the proposal's, not an option's. Open now: %s" % (n,
			", ".join(openNow) or "none"))
	ai = gc.getPlayer(v["from"])
	gives = [tuple(x) for x in v["gives"]]
	wants = [tuple(x) for x in v["wants"]]
	c = v["comment"]
	done = []
	if c == "vote":
		return answerVote(o, n, v, why)
	if yes and (gives or wants) and c in TRADES and c not in ("screen_offer", "agent_offer") and not ai.isHuman():
		# a turn may have passed: the AI must still want it (its own judgment, as when it proposed)
		if not ai.AI_considerOfferText(iMe, engineText(wants), engineText(gives)):
			yes = False
			why = "%s no longer agrees to it" % pname(v["from"])
			done.append(why)
	if yes and (gives or wants):
		executeDeal(v["from"], iMe, gives, wants)
		done.append("deal made")
		# our side of it, for the ledger: we gave what they wanted, we got what they gave
		writeEvent("deal_done", {"with": pname(v["from"]), "gave": [itemText(x, iMe) for x in wants],
			"got": [itemText(x, v["from"]) for x in gives], "their_proposal": int(n)})
	if ai.isHuman() and why != "no answer in time":
		CyInterface().addMessage(v["from"], True, gc.getEVENT_MESSAGE_TIME() * 3,
			u"<font=4><color=255,200,60,255>%s %s your offer.</color></font>" % (gc.getPlayer(iMe).getName(),
			(yes and "accepts") or "declines"), "", InterfaceMessageTypes.MESSAGE_TYPE_MAJOR_EVENT, "", -1, -1, -1, False, False)
	if ANSWERS.has_key(c) and not ai.isHuman():
		ev = getattr(DiploEventTypes, ANSWERS[c][not yes and 1 or 0])
		ai.handleDiploEvent(ev, iMe, v.get("data", -1), -1)
		done.append(ANSWERS[c][not yes and 1 or 0].replace("DIPLOEVENT_", "").lower().replace("_", " "))
		if c == "demand_tribute" and not yes and ai.AI_demandRebukedWar(iMe):
			ai.handleDiploEvent(DiploEventTypes.DIPLOEVENT_DEMAND_WAR, iMe, -1, -1)
			done.append("%s declares war" % pname(v["from"]))
	o = loadProposals()   # a deal or answer can raise new proposals meanwhile (a vote, an AI's reply): keep them
	if o["open"].has_key(str(n)):
		del o["open"][str(n)]
	closeNote(o, n, why == "no answer in time" and "nobody answered it by the end of turn %d" % (v["turn"] + 1)
		or "answered %s on turn %d" % (yes and "yes" or "no", gc.getGame().getGameTurn()))
	saveProposals(o)
	refreshSnapshot()
	writeEvent("proposal_answered", {"id": int(n), "answer": yes and "yes" or "no", "what": proposalText(v),
		"result": done, "why": why})
	if c == "agent_offer":
		# the agent who offered hears the answer
		me = getClaudePlayer()
		prev = actAs(v["from"])
		try:
			writeEvent(yes and "deal_done" or "deal_declined", {"id": int(n), "with": pname(me), "by": pname(me),
				"gave": [itemText(tuple(x), v["from"]) for x in v["gives"]], "got": [itemText(tuple(x), me) for x in v["wants"]],
				"why": why})
		finally:
			actAs(prev)
	return {"id": int(n), "answer": yes and "yes" or "no", "result": done or ["nothing changes"]}

def newVote(me, voteId, source, vote, player, cityId, other, text):
	o = loadProposals()
	for k, v in o["open"].items():
		if v["comment"] == "vote" and v["data"] == voteId:
			return
	info = gc.getVoteInfo(vote)
	v = {"from": me, "comment": "vote", "data": voteId, "gives": [], "wants": [], "turn": gc.getGame().getGameTurn(),
		"source": gc.getVoteSourceInfo(source).getDescription(), "text": text,
		"election": bool(info.isSecretaryGeneral() or info.isVictory())}
	n = o["next"]
	o["next"] = n + 1
	o["open"][str(n)] = v
	saveProposals(o)
	writeEvent("proposal", {"id": n, "text": voteText(v), "answer": voteHow(n, v)})

def voteText(v):
	return "%s vote: %s" % (v["source"], v["text"])

def voteHow(n, v):
	if v["election"]:
		return "civ answer %d <leader to vote for> (or abstain); open until the vote is counted" % n
	return "civ answer %d yes|no|abstain; open until the vote is counted" % n

def answerVote(o, n, v, why):
	iMe = getClaudePlayer()
	a = (why or "").strip().lower()
	if v["election"] and a not in ("abstain", "", "no answer in time"):
		choice = gc.getPlayer(findPlayer(a)).getTeam()   # an election counts votes per team
	else:
		choice = {"yes": PlayerVoteTypes.PLAYER_VOTE_YES, "no": PlayerVoteTypes.PLAYER_VOTE_NO}.get(a, PlayerVoteTypes.PLAYER_VOTE_ABSTAIN)
	gc.getGame().castVote(iMe, v["data"], choice)
	o = loadProposals()   # counting a vote can trigger the next one: keep it
	if o["open"].has_key(str(n)):
		del o["open"][str(n)]
	saveProposals(o)
	writeEvent("proposal_answered", {"id": int(n), "answer": a or "abstain", "what": voteText(v)})
	return {"id": int(n), "voted": a or "abstain", "vote": voteText(v)}

def newChoice(kind, data, text, options):
	# a random event / quest, or a free tech: Claude picks (`civ answer N <choice>`)
	o = loadProposals()
	if kind == "event":
		for k, v in o["open"].items():
			if v["comment"] == "event" and v["data"] == data:
				return
	iMe = getClaudePlayer()
	v = {"from": iMe, "comment": kind, "data": data, "gives": [], "wants": [], "turn": gc.getGame().getGameTurn(),
		"text": text, "options": options}
	n = o["next"]
	o["next"] = n + 1
	o["open"][str(n)] = v
	saveProposals(o)
	writeEvent("proposal", {"id": n, "text": choiceText(v), "answer": choiceHow(n, v)})

def choiceText(v):
	if v["comment"] == "free_tech":
		return "a free tech is yours to pick (%s)" % v["text"]
	return "event: %s; options: %s" % (v["text"], " | ".join(v["options"]))

def choiceHow(n, v):
	if v["comment"] == "free_tech":
		return "civ answer %d <tech> (any tech you can research now; it waits for you)" % n
	return "civ answer %d <option number> (no answer by the end of next turn: the first option)" % n

def answerChoice(o, n, v, a):
	iMe = getClaudePlayer()
	p = gc.getPlayer(iMe)
	if v["comment"] == "free_tech":
		t = findInfo(a, gc.getNumTechInfos(), gc.getTechInfo, "tech_")
		if t < 0 or not p.canResearch(t, False):
			raise Exception("pick a tech you can research now (civ research lists them)")
		gc.getTeam(p.getTeam()).setHasTech(t, True, iMe, True, True)
		done = "got %s for free" % gc.getTechInfo(t).getDescription()
	else:
		ids = [int(re.match(u"^(\\d+):", x).group(1)) for x in v["options"] if re.match(u"^\\d+:", x)]
		e = int(str(a).split(":")[0].strip().lstrip("#"))
		if e not in ids:
			raise Exception("pick one of the options: %s" % ", ".join([str(i) for i in ids]))
		if not p.claudeApplyEvent(e, v["data"]):
			raise Exception("the game no longer allows that option")
		done = "chose: %s" % gc.getEventInfo(e).getDescription()
	o = loadProposals()   # the choice may raise new proposals meanwhile: keep them
	if o["open"].has_key(str(n)):
		del o["open"][str(n)]
	saveProposals(o)
	refreshSnapshot()
	writeEvent("proposal_answered", {"id": int(n), "answer": a, "what": choiceText(v), "result": [done]})
	return {"id": int(n), "result": done}

def expireProposals():
	# a human must answer on the screen at once; Claude has until his next turn ends
	now = gc.getGame().getGameTurn()
	o = loadProposals()
	for k, v in o["open"].items():
		if v["comment"] == "free_tech":
			continue
		if v["comment"] == "event":
			if v["turn"] < now and v["options"]:
				try:
					answerChoice(o, k, v, v["options"][0])
				except:
					del o["open"][k]
					saveProposals(o)
			continue
		if v["comment"] == "election":
			if v["turn"] < now - 1:
				try:
					answerElection(o, k, v, None)
				except:
					del o["open"][k]
					saveProposals(o)
			continue
		if v["comment"] == "vote":
			if v["turn"] < now - 2:   # counted by now; a late vote would not count
				del o["open"][k]
				saveProposals(o)
			continue
		if v["turn"] < now - 1:   # open until the end of the turn after the one it was made in (what the event says)
			try:
				answerProposal(k, False, "no answer in time")
			except:
				log("proposal expiry FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))

def cmdProposals(args):
	o = loadProposals()
	return {"open": ["#%s (turn %d): %s" % (k, v["turn"], proposalText(v)) for k, v in o["open"].items()] or ["none"],
		"answer": "civ answer N yes|no; a resolution to choose: civ answer N <option number>",
		"resolutions": "as Resident, the choice of a resolution arrives here as a proposal when the session opens (an event wakes you)"}

def newElection(me, selId, source, options):
	# the agent Resident picks the resolution (the engine waits for CyGame.claudeChooseElection)
	o = loadProposals()
	for k, v in o["open"].items():
		if v["comment"] == "election" and v["data"] == selId:
			return
	v = {"from": me, "comment": "election", "data": selId, "gives": [], "wants": [], "turn": gc.getGame().getGameTurn(),
		"source": gc.getVoteSourceInfo(source).getDescription(),
		"options": [re.sub(u"<[^>]*>", u"", x).strip() for x in options.split(u"\n") if x.strip()]}
	n = o["next"]
	o["next"] = n + 1
	o["open"][str(n)] = v
	saveProposals(o)
	writeEvent("proposal", {"id": n, "text": proposalText(v),
		"answer": "civ answer %d <option number> (open until the end of next turn; then the game picks)" % n})

def answerElection(o, n, v, a):
	if a is None:
		i = -1   # no answer in time: the pick the game itself would make
	else:
		try:
			i = int(str(a).strip().lstrip("#")) - 1
		except ValueError:
			raise Exception("answer with the option's number, 1 to %d" % len(v["options"]))
		if i < 0 or i >= len(v["options"]):
			raise Exception("answer with the option's number, 1 to %d" % len(v["options"]))
	if not gc.getGame().claudeChooseElection(v["data"], i):
		raise Exception("the game no longer has this election open")
	# the choice starts the vote at once and puts a ballot in this seat's proposals: read them again, or this
	# save would wipe that ballot
	o = loadProposals()
	if o["open"].has_key(str(n)):
		del o["open"][str(n)]
	what = i >= 0 and v["options"][i] or "the game's own pick (no answer in time)"
	closeNote(o, n, "resolution chosen: %s" % what)
	saveProposals(o)
	writeEvent("proposal_answered", {"id": int(n), "answer": a, "what": proposalText(v), "result": ["put to the vote: " + what]})
	return {"id": int(n), "put_to_the_vote": what}

def cmdAnswer(args):
	n = str(args["id"]).lstrip("#")
	a = args["answer"]
	v = loadProposals()["open"].get(n)
	if v is not None and v["comment"] == "election":
		return answerElection(loadProposals(), n, v, a)
	if v is not None and v["comment"] == "vote":
		return answerProposal(n, True, a)
	if v is not None and v["comment"] in ("event", "free_tech"):
		return answerChoice(loadProposals(), n, v, a)
	return answerProposal(n, a.lower() in ("yes", "y", "accept", "ok"))

def engineArgs(a):
	# a generic game event's arguments arrive wrapped (a tuple or list inside the event's own list)
	a = list(a)
	while len(a) == 1 and type(a[0]) in (type(()), type([])):
		a = list(a[0])
	return a

def cmdOffers(args):
	o = loadOffers()
	seal = loadSeal()
	return {"waiting_for_your_seal": [sealLine(k, v) for k, v in seal["open"].items()] or ["none"],
		"open": ["#%s to %s: give %s; get %s" % (k, pname(v["to"]), ", ".join([itemText(tuple(x), v["from"]) for x in v["give"]]) or "nothing",
		", ".join([itemText(tuple(x), v["to"]) for x in v["get"]])) for k, v in o["open"].items()]}

def cmdWar(args):
	# Claude's own declaration of war (the built-in AI no longer declares wars for this civ)
	iMe, iTeam = myIds()
	other = gc.getPlayer(findPlayer(args["player"])).getTeam()
	can = gc.getTeam(iTeam).canDeclareWar(other)
	# the game's rule: declaring war first ends every deal between us (open borders too), then
	# every unit standing in the other side's land is moved to the nearest tile outside it
	ours = []
	(u, it) = gc.getPlayer(iMe).firstUnit(False)
	while u and not u.isNone():
		if u.getDomainType() == DomainTypes.DOMAIN_LAND and u.plot().getTeam() == other:
			ours.append([u.getID(), gc.getUnitInfo(u.getUnitType()).getDescription(), u.getX(), u.getY()])
		(u, it) = gc.getPlayer(iMe).nextUnit(it, False)
	deals = [dealLine(d, o, give, get) for (d, o, give, get) in ourDeals() if gc.getPlayer(o).getTeam() == other]
	if args.get("check"):
		return {"check": True, "can_declare": can, "against": teamName(other),
			"our_units_pushed_out": ours, "deals_that_end": deals}
	if not can:
		raise Exception("we can't declare war on %s now (peace treaty still running, or not met?)" % args["player"])
	gc.getTeam(iTeam).declareWar(other, True, WarPlanTypes.WARPLAN_TOTAL)
	moved = []
	for uid, name, x, y in ours:
		u = gc.getPlayer(iMe).getUnit(uid)
		if u is None or u.isNone():
			moved.append("%s #%d was in their land at (%d,%d) and is gone" % (name, uid, x, y))
		elif (u.getX(), u.getY()) != (x, y):
			moved.append("%s #%d pushed out of their land: (%d,%d) -> (%d,%d)" % (name, uid, x, y, u.getX(), u.getY()))
	refreshSnapshot()
	return {"war_declared_on": teamName(other), "deals_ended": deals, "units_pushed_out": moved}


def cmdRelations(args):
	# what a human sees on the Foreign Advisor screen, for the leaders we have met: wars, treaties,
	# vassals, each AI's mood toward every other met leader, and its worst enemy
	iMe, iTeam = myIds()
	me = gc.getTeam(iTeam)
	met = [i for i in range(gc.getMAX_CIV_PLAYERS()) if gc.getPlayer(i).isAlive() and i != iMe
		and me.isHasMet(gc.getPlayer(i).getTeam())]
	everyone = [iMe] + met
	out = {}
	for a in everyone:
		pa = gc.getPlayer(a)
		ta = gc.getTeam(pa.getTeam())
		line = []
		wars = [pname(b) for b in everyone if b != a and ta.isAtWar(gc.getPlayer(b).getTeam())]
		if wars:
			line.append("at war with " + ", ".join(wars))
		for what, test in (("open borders", ta.isOpenBorders), ("defensive pact", ta.isDefensivePact)):
			x = [pname(b) for b in everyone if b != a and test(gc.getPlayer(b).getTeam())]
			if x:
				line.append("%s with %s" % (what, ", ".join(x)))
		masters = [pname(b) for b in everyone if b != a and ta.isVassal(gc.getPlayer(b).getTeam())]
		if masters:
			line.append("vassal of " + ", ".join(masters))
		if not pa.isHuman() and not pa.isClaude():
			moods = ["%s %s" % (pname(b), gc.getAttitudeInfo(pa.AI_getAttitude(b)).getDescription().lower())
				for b in everyone if b != a]
			line.append("feels: " + "; ".join(moods))
			worst = pa.getWorstEnemyName()
			if worst:
				line.append("worst enemy: %s" % worst)
		state = pa.getStateReligion()
		if state >= 0:
			line.append("state religion " + gc.getReligionInfo(state).getDescription())
		out[pname(a)] = "; ".join(line) or "at peace with everyone we know"
	return out

def cmdVictory(args):
	# the Victory screen: scores of the leaders we've met, and how far we are from each way to win
	iMe, iTeam = myIds()
	g = gc.getGame()
	me = gc.getPlayer(iMe)
	team = gc.getTeam(iTeam)
	scores = []
	for i in range(gc.getMAX_CIV_PLAYERS()):
		p = gc.getPlayer(i)
		if p.isAlive() and (i == iMe or team.isHasMet(p.getTeam())):
			scores.append((g.getPlayerScore(i), pname(i)))
	scores.sort()
	scores.reverse()
	r = {"turn": "%d of %d" % (g.getGameTurn(), g.getMaxTurns() or g.getEstimateEndTurn()),
		"scores": ", ".join(["%s %d" % (n, sc) for sc, n in scores])}
	if g.getWinner() >= 0:
		r["winner"] = teamName(g.getWinner())
		r["won_by"] = g.getVictory() >= 0 and gc.getVictoryInfo(g.getVictory()).getDescription() or "-"
	ships = ["%s arrives in %d turns" % (teamName(t), gc.getTeam(t).getVictoryCountdown(v))
		for t in range(gc.getMAX_CIV_TEAMS()) for v in range(gc.getNumVictoryInfos())
		if gc.getTeam(t).isAlive() and gc.getTeam(t).getVictoryCountdown(v) > 0]
	if ships:
		r["spaceships_flying"] = "; ".join(ships)
	land = CyMap().getLandPlots()
	for v in range(gc.getNumVictoryInfos()):
		if not g.isVictoryValid(v):
			continue
		info = gc.getVictoryInfo(v)
		t = info.getType()
		if info.getLandPercent() > 0:
			r["domination"] = "we hold %d%% of the land (need %d%%) and %d%% of all people (need %d points more than the next civ)" % (
				100 * team.getTotalLand() / max(1, land), info.getLandPercent(),
				100 * team.getTotalPopulation() / max(1, g.getTotalPopulation()), info.getPopulationPercentLead())
		elif info.getCityCulture() > 0:
			need = info.getNumCultureCities()
			cities = []
			(c, it) = me.firstCity(False)
			while c and not c.isNone():
				cities.append((c.getCulture(iMe), c.getName()))
				(c, it) = me.nextCity(it, False)
			cities.sort()
			cities.reverse()
			goal = gc.getCultureLevelInfo(info.getCityCulture()).getSpeedThreshold(g.getGameSpeedType())
			r["culture"] = "%d cities need %d culture each; our best: %s" % (need, goal,
				", ".join(["%s %d" % (n, cu) for cu, n in cities[:need]]))
		elif info.isConquest():
			r["conquest"] = "eliminate every rival"
		elif info.isDiploVote():
			r["diplomatic"] = "win a victory vote in the UN or the Apostolic Palace: %s (`civ votes` for members and " \
				"votes; `civ relations` for who backs whom)" % "; ".join([x for vs in range(gc.getNumVoteSourceInfos())
				for x in victoryVotes(vs)])
		elif t.find("SPACE") >= 0:
			r["space"] = "build and launch the spaceship (Apollo Program first)"
		elif info.isEndScore():
			r["time"] = "at the last turn (%d) the highest score wins" % (g.getMaxTurns() or g.getEstimateEndTurn())
		elif info.isTargetScore():
			if g.getTargetScore() > 0:
				r["score"] = "the first to reach %d points wins" % g.getTargetScore()
			else:
				r["score"] = "no target score is set in this game, so this road can't end it (at the last turn the time victory goes to the highest score)"
		else:
			r[t.replace("VICTORY_", "").lower()] = info.getDescription()
	return r

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
		for k, what in (("vassal", "vassal (become their vassal, in peace)"),
				("surrender", "surrender (capitulate: become their vassal, ends the war)")):
			if pa.canTradeItem(b, tradeData((k, -1)), False):
				out.append(what)
		for k in ("war", "peace_with"):
			for c in range(gc.getMAX_CIV_PLAYERS()):
				if c in (a, b) or not gc.getPlayer(c).isAlive():
					continue
				try:
					if not pa.canTradeItem(b, tradeData((k, c)), False):
						continue
				except:
					continue
				txt = "%s:%s" % (k, realName(c))
				if a != iMe and not pa.isHuman() and not isAgent(a):   # our side and an agent's are their own decision
					den = pa.getTradeDenial(b, tradeData((k, c)))
					if den != DenialTypes.NO_DENIAL:
						txt += " (refuses: %s)" % gc.getDenialInfo(den).getDescription()
				out.append(txt)
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
			"we_can_build_it": me.canTrain(i, False, False), "our_version": ownVersion(me.getID(), i) != i and gc.getUnitInfo(ownVersion(me.getID(), i)).getDescription() or "the same", "strategy": info.getStrategy(), "help": info.getHelp()}
	i = findInfo(want, gc.getNumBuildingInfos(), gc.getBuildingInfo, "building_")
	if i >= 0:
		info = gc.getBuildingInfo(i)
		return {"building": info.getDescription(), "cost": me.getBuildingProductionNeeded(i),
			"needs_tech": techList([info.getPrereqAndTech()]), "obsolete_with": techList([info.getObsoleteTech()]),
			"happiness": info.getHappiness(), "health": info.getHealth(), "strategy": info.getStrategy(), "help": info.getHelp()}
	i = findInfo(want, gc.getNumProjectInfos(), gc.getProjectInfo, "project_")
	if i >= 0:
		info = gc.getProjectInfo(i)
		return {"project": info.getDescription(), "cost": me.getProjectProductionNeeded(i),
			"needs_tech": techList([info.getTechPrereq()]),
			"needs_project_first": info.getAnyoneProjectPrereq() >= 0 and gc.getProjectInfo(info.getAnyoneProjectPrereq()).getDescription() or "-",
			"limit_per_world": info.getMaxGlobalInstances(), "limit_per_team": info.getMaxTeamInstances(),
			"spaceship_part": info.isSpaceship(), "help": info.getHelp()}
	i = findInfo(want, gc.getNumCivicInfos(), gc.getCivicInfo, "civic_")
	if i >= 0:
		info = gc.getCivicInfo(i)
		upkeep = "none"
		if info.getUpkeep() >= 0:
			upkeep = gc.getUpkeepInfo(info.getUpkeep()).getDescription()
		return {"civic": info.getDescription(), "category": gc.getCivicOptionInfo(info.getCivicOptionType()).getDescription(),
			"needs_tech": techList([info.getTechPrereq()]), "upkeep": upkeep,
			"we_can_adopt": me.canDoCivics(i), "strategy": info.getStrategy(), "help": info.getHelp(),
			"why_without_tech": me.isHasCivicOption(info.getCivicOptionType()) and civicsOpenedByWonder(me) or None}
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
	# the game's own Civilopedia articles about how the game works (war, borders, combat, happiness...)
	concepts = conceptList()
	if want.strip().lower() in ("concepts", "mechanics", "list"):
		return {"concepts": [c[0] for c in concepts],
			"how": "civ rules <concept> reads the game's own Civilopedia article"}
	w = want.strip().lower().replace(" ", "_")
	for name, typ, text in concepts:
		if w in (name.lower().replace(" ", "_"), typ.lower(), typ.lower().replace("concept_", "")):
			return {"concept": name, "article": pediaText(text)}
	raise Exception("nothing called %s among techs, units, buildings, projects, civics, worker builds, resources, "
		"concepts (civ rules concepts lists them)" % want)

def conceptList():
	out = []
	for i in range(gc.getNumConceptInfos()):
		c = gc.getConceptInfo(i)
		out.append((c.getDescription(), c.getType(), c.getCivilopedia()))
	try:
		for i in range(gc.getNumNewConceptInfos()):
			c = gc.getNewConceptInfo(i)
			out.append((c.getDescription(), c.getType(), c.getCivilopedia()))
	except:
		pass
	return out

def pediaText(t):
	t = re.sub(r"<link=[^>]*>", "", t)
	t = re.sub(r"<font=[^>]*>([^<]*)</font>", r"## \1", t)
	t = re.sub(r"</?[a-zA-Z]+[^>]*>", "", t)
	t = re.sub(r"\n\s*\n+", "\n\n", t)
	return t.strip()

def aiDoDiplo(gu, argsList):
	if argsList[0] == getClaudePlayer():
		return True   # an agent's diplomacy is its own
	try:
		# what follows is this leader's diplomacy: every agent seat starts a new window for its own deals
		if seatsConfigured():
			forEachSeat(checkpoint, ("diplo", argsList[0]))
		else:
			checkpoint(("diplo", argsList[0]))
	except:
		log("deal checkpoint FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
	return gu._claudeOrigDoDiplo(argsList)

def aiDoWar(gu, argsList):
	iMe = getClaudePlayer()
	if iMe >= 0 and argsList[0] == gc.getPlayer(iMe).getTeam():
		return True   # wars are the agent's own decision
	return gu._claudeOrigDoWar(argsList)

def doDiploTrampoline(argsList):
	import CvGameInterfaceFile
	B = sys.modules["ClaudeBridge"]
	return B.asSeatOf(argsList[0], B.aiDoDiplo, CvGameInterfaceFile.GameUtils, argsList)

def doWarTrampoline(argsList):
	import CvGameInterfaceFile
	B = sys.modules["ClaudeBridge"]
	return B.asSeatOf(B.teamAgent(argsList[0]), B.aiDoWar, CvGameInterfaceFile.GameUtils, argsList)

# ------------------------------------------------------- orders: research, builds
#
# The player's own decisions, checked by the game's rules (canResearch, canTrain...)
# so an impossible order fails with a reason instead of silently doing nothing.
# Cities given an order are "claimed": the built-in AI won't change what they build
# while their queue has something in it (the AI_chooseProduction hook).

CITY_CLAIMS_FILE = OUT_DIR + "\\city_claims.json"

def findInfo(want, count, getter, prefix):
	# by type ("TECH_ARCHERY") or description ("Archery"), case-insensitive; then forgiving the way a
	# person is: a plural ("Warriors"), or the start of a name if only one name starts so ("Bronze")
	w = want.strip().lower().replace(" ", "_").replace("-", "_")
	if not w:
		return -1
	names = [(i, getter(i).getType().lower(), getter(i).getDescription().lower().replace(" ", "_").replace("-", "_"))
		for i in range(count)]
	for cand in (w, w.endswith("s") and w[:-1] or None, w.endswith("es") and w[:-2] or None):
		if not cand:
			continue
		for (i, t, d) in names:
			if t == cand or t == prefix + cand or d == cand:
				return i
	starts = [i for (i, t, d) in names if d.startswith(w)]
	if len(starts) == 1:
		return starts[0]
	return -1

def suggest(want, count, getter):
	# close names for a "did you mean" (difflib: the game's names against what was typed)
	import difflib
	descs = [getter(i).getDescription() for i in range(count)]
	low = dict([(d.lower(), d) for d in descs])
	hits = difflib.get_close_matches(want.strip().lower(), low.keys(), 3, 0.6)
	first = want.strip().lower().split(" ")[0]
	starts = [d for d in descs if first and (d.lower().startswith(first) or (" " + first) in d.lower())]
	out = []
	for h in [low[x] for x in hits] + starts:
		if h not in out:
			out.append(h)
	return out[:4] and " Did you mean: %s?" % ", ".join(out[:4]) or ""

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
			raise Exception("no tech called %s (one tech per command).%s" % (args["tech"],
				suggest(args["tech"], gc.getNumTechInfos(), gc.getTechInfo)))
		if gc.getTeam(p.getTeam()).isHasTech(i):
			raise Exception("we already know %s" % techName(i))
		if not args.get("queue"):
			# research it now: the game's pushResearch ignores a tech that is already somewhere in the queue,
			# so the queue is cleared first (the new tech and its missing prerequisites become the queue)
			p.clearResearchQueue()
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

def ownVersion(player, unit):
	# the unit this civilization builds for that unit's class (its unique unit, if it has one)
	civ = gc.getCivilizationInfo(gc.getPlayer(player).getCivilizationType())
	own = civ.getCivilizationUnits(gc.getUnitInfo(unit).getUnitClassType())
	return own >= 0 and own or unit

def buildableNow(c):
	units = [gc.getUnitInfo(i).getDescription() for i in range(gc.getNumUnitInfos()) if c.canTrain(i, False, False)]
	builds = [gc.getBuildingInfo(i).getDescription() for i in range(gc.getNumBuildingInfos()) if c.canConstruct(i, False, False, False)]
	projects = ["%s (project)" % gc.getProjectInfo(i).getDescription() for i in range(gc.getNumProjectInfos()) if c.canCreate(i, False, False)]
	processes = ["%s (process)" % gc.getProcessInfo(i).getDescription() for i in range(gc.getNumProcessInfos()) if c.canMaintain(i, False)]
	return units + builds + projects + processes

def whyCantBuild(c, order, i):
	# the game's reason, as the city screen would show it
	team = gc.getTeam(c.getTeam())
	# a civilization's unique unit or building replaces the standard one: say which, or that it has none
	civ = gc.getCivilizationInfo(gc.getPlayer(c.getOwner()).getCivilizationType())
	if order in (OrderTypes.ORDER_TRAIN, OrderTypes.ORDER_CONSTRUCT):
		if order == OrderTypes.ORDER_TRAIN:
			info = gc.getUnitInfo(i)
			own = civ.getCivilizationUnits(info.getUnitClassType())
			o = own >= 0 and gc.getUnitInfo(own)
		else:
			info = gc.getBuildingInfo(i)
			own = civ.getCivilizationBuildings(info.getBuildingClassType())
			o = own >= 0 and gc.getBuildingInfo(own)
		if own < 0:
			return "%s can't have one at all" % civ.getShortDescription(0)
		if own != i:
			return "%s builds its own %s instead (its unique version of the %s): civ build %s %s" % (
				civ.getShortDescription(0), o.getDescription(), info.getDescription(), c.getName(), o.getDescription())
	if order == OrderTypes.ORDER_TRAIN:
		info = gc.getUnitInfo(i)
	elif order == OrderTypes.ORDER_CONSTRUCT:
		info = gc.getBuildingInfo(i)
		if c.getNumRealBuilding(i) > 0:
			return "it already has one"
		if info.getPrereqReligion() >= 0 and not c.isHasReligion(info.getPrereqReligion()):
			return "it needs %s in the city" % gc.getReligionInfo(info.getPrereqReligion()).getDescription()
	else:
		return "the game's rules don't allow it here now"
	tech = info.getPrereqAndTech()
	if tech >= 0 and not team.isHasTech(tech):
		return "it needs the tech %s" % gc.getTechInfo(tech).getDescription()
	bonus = info.getPrereqAndBonus()
	if bonus >= 0 and not c.hasBonus(bonus):
		return "it needs %s connected to the city" % gc.getBonusInfo(bonus).getDescription()
	if order == OrderTypes.ORDER_TRAIN:
		own = ownVersion(c.getOwner(), i)
		if own != i:
			return "your civilization builds %s instead (its own version of this unit)" % gc.getUnitInfo(own).getDescription()
	return "a requirement of the game isn't met (coast, river, a building it needs first, or a limit)"

def findItem(want):
	# a unit, building, project or process for a city's queue. "<name> (process)", as the build list writes
	# it, means a process; an exact name of any kind wins over a close one ("Research" is the process, not
	# Research Institute)
	kinds = [(OrderTypes.ORDER_TRAIN, gc.getNumUnitInfos(), gc.getUnitInfo, "unit_"),
		(OrderTypes.ORDER_CONSTRUCT, gc.getNumBuildingInfos(), gc.getBuildingInfo, "building_"),
		(OrderTypes.ORDER_CREATE, gc.getNumProjectInfos(), gc.getProjectInfo, "project_"),
		(OrderTypes.ORDER_MAINTAIN, gc.getNumProcessInfos(), gc.getProcessInfo, "process_")]
	m = re.match(r"(?i)^(.*?)\s*\(process\)\s*$", want.strip())
	if m:
		want, kinds = m.group(1), kinds[3:]
	key = want.strip().lower().replace("_", " ")
	for (order, count, getter, prefix) in kinds:
		for i in range(count):
			if key in (getter(i).getDescription().lower(), getter(i).getType().lower().replace("_", " "),
					getter(i).getType().lower()[len(prefix):].replace("_", " ")):
				return order, i, getter(i).getDescription()
	for (order, count, getter, prefix) in kinds:
		i = findInfo(want, count, getter, prefix)
		if i >= 0:
			return order, i, getter(i).getDescription()
	near = suggest(want, gc.getNumUnitInfos(), gc.getUnitInfo) or suggest(want, gc.getNumBuildingInfos(), gc.getBuildingInfo)
	raise Exception("nothing called %s to build.%s" % (want, near))

def cityAndRest(words):
	# "Addis Ababa 12 7": the longest start of the words that names a known city is the city, the rest follows
	for k in range(len(words), 0, -1):
		try:
			return findCity({"name": " ".join(words[:k])}), words[k:]
		except:
			continue
	raise Exception("no known city named %s" % " ".join(words[:2]))

def workView(c):
	# the city screen's citizens: worked tiles and their yields, free tiles it could work, specialists
	Y = (YieldTypes.YIELD_FOOD, YieldTypes.YIELD_PRODUCTION, YieldTypes.YIELD_COMMERCE)
	fmt = lambda pl: "%d,%d %d/%d/%d" % (pl.getX(), pl.getY(), pl.getYield(Y[0]), pl.getYield(Y[1]), pl.getYield(Y[2]))
	worked, free = [], []
	for i in range(1, gc.getNUM_CITY_PLOTS()):
		pl = c.getCityIndexPlot(i)
		if pl is None or pl.isNone():
			continue
		if c.isWorkingPlotByIndex(i):
			worked.append(fmt(pl))
		elif c.canWork(pl):
			free.append((pl.getYield(Y[0]) * 3 + pl.getYield(Y[1]) * 2 + pl.getYield(Y[2]), fmt(pl)))
	free.sort()
	free.reverse()
	specs = ["%s %d" % (gc.getSpecialistInfo(s).getDescription(), c.getSpecialistCount(s))
		for s in range(gc.getNumSpecialistInfos()) if c.getSpecialistCount(s) > 0]
	return {"city": c.getName(), "per_turn": "food %d (needs %d), production %d, commerce %d" % (
			c.getYieldRate(Y[0]), c.foodConsumption(False, 0), c.getYieldRate(Y[1]), c.getYieldRate(Y[2])),
		"worked (x,y food/production/commerce)": ", ".join(worked) or "none",
		"could work instead": ", ".join([f for (v, f) in free[:8]]) or "none",
		"specialists": ", ".join(specs) or "none",
		"citizens": c.isCitizensAutomated() and "placed by the governor" or "placed by you"}

def cmdWork(args):
	# a human's clicks on the city screen: which tiles the citizens work, and specialists
	iMe, iTeam = myIds()
	c, rest = cityAndRest(args["words"])
	if c.getOwner() != iMe:
		raise Exception("%s is not our city" % c.getName())
	if not rest:
		return workView(c)
	if rest[0].lower() == "auto":
		# the governor places every citizen again. Clicking the city tile only switches it on: if it was on
		# already, the game re-places nobody, so it is switched off and on (on runs the placing)
		if c.isCitizensAutomated():
			c.setCitizensAutomated(False)
		c.setCitizensAutomated(True)
		return workView(c)
	if len(rest) >= 2 and rest[0].lstrip("-").isdigit() and rest[1].lstrip("-").isdigit():
		pl = CyMap().plot(int(rest[0]), int(rest[1]))
		i = c.getCityPlotIndex(pl)
		if i < 1 or i >= gc.getNUM_CITY_PLOTS():
			raise Exception("%s,%s is not one of %s's tiles" % (rest[0], rest[1], c.getName()))
		if not c.canWork(pl) and not c.isWorkingPlotByIndex(i):
			raise Exception("%s can't work %s,%s (another city works it, it's foreign, or not yet in its borders)" % (c.getName(), rest[0], rest[1]))
		c.alterWorkingPlot(i)   # worked -> freed (the citizen becomes a specialist); free -> worked
		return workView(c)
	s = findInfo(rest[0], gc.getNumSpecialistInfos(), gc.getSpecialistInfo, "specialist_")
	if s < 0:
		raise Exception("say X Y (a tile), a specialist (%s) with +N/-N, or auto" % ", ".join(
			[gc.getSpecialistInfo(k).getDescription() for k in range(gc.getNumSpecialistInfos())]))
	n = len(rest) > 1 and int(rest[1]) or 1
	if n > 0 and not c.isSpecialistValid(s, n):
		raise Exception("%s can't take %d more %s (needs a building that allows them, or a free citizen)" % (c.getName(), n, gc.getSpecialistInfo(s).getDescription()))
	c.alterSpecialistCount(s, n)
	return workView(c)

def victoryVotes(vs):
	# the resolutions of a diplomatic body that win the game, and the share of its votes each needs (Victory screen)
	g = gc.getGame()
	out = []
	for v in range(gc.getNumVoteInfos()):
		vi = gc.getVoteInfo(v)
		if vi.isVictory() and vi.isVoteSourceType(vs):
			line = "%s: needs %d%% of the votes" % (vi.getDescription(), vi.getPopulationThreshold())
			if g.isDiploVote(vs):
				line += " (%d of the %d votes there are now)" % (g.getVoteRequired(v, vs), g.countPossibleVote(v, vs))
			out.append(line)
	return out

def cmdSpaceship(args):
	# the Spaceship screen: our parts against what the game needs, the success chance, the flight time, every
	# ship already flying (launches are announced to all), and the Launch button (launch=true)
	iMe, iTeam = myIds()
	g = gc.getGame()
	team = gc.getTeam(iTeam)
	out = {}
	for v in range(gc.getNumVictoryInfos()):
		if not g.isVictoryValid(v):
			continue
		parts = [p for p in range(gc.getNumProjectInfos()) if gc.getProjectInfo(p).getVictoryThreshold(v) > 0]
		if not parts:
			continue
		rows = []
		for p in parts:
			k = gc.getProjectInfo(p)
			rows.append("%s: %d built of %d (at least %d to launch)" % (k.getDescription(), team.getProjectCount(p),
				k.getVictoryThreshold(v), k.getVictoryMinThreshold(v)))
		flying = []
		for t in range(gc.getMAX_CIV_TEAMS()):
			c = gc.getTeam(t).getVictoryCountdown(v)
			if gc.getTeam(t).isAlive() and c > 0:
				flying.append("%s: arrives in %d turns" % (t == iTeam and "ours" or teamName(t), c))
		r = {"parts": rows, "can_launch": team.canLaunch(v) and "yes" or "no",
			"success_chance": "%d%%" % team.getLaunchSuccessRate(v),
			"flight_turns": team.getVictoryDelay(v),
			"ships_flying": flying or ["none"],
			"how": "civ spaceship launch: the Launch button. Missing optional parts lower the success chance (a failed "
				"ship is lost) and engines shorten the flight; the game is won when a ship arrives"}
		if args.get("launch"):
			if not team.canLaunch(v):
				raise Exception("the ship can't be launched now: the game needs at least the parts marked above (or it is already flying)")
			if not hasattr(gc.getPlayer(iMe), "claudeLaunch"):
				raise Exception("launching needs the updated engine; tell the director")
			if not gc.getPlayer(iMe).claudeLaunch(v):
				raise Exception("the game refused the launch")
			writeEvent("spaceship_launched", {"arrives_in": team.getVictoryCountdown(v), "success_chance": team.getLaunchSuccessRate(v)})
			r["launched"] = "the ship is on its way: it arrives in %d turns" % team.getVictoryCountdown(v)
		out[gc.getVictoryInfo(v).getDescription()] = r
	return out or {"spaceship": "no space victory in this game"}

def cmdEspionage(args):
	# the Espionage screen: our points against each leader we know, and the weights that split new points
	iMe, iTeam = myIds()
	me, team = gc.getPlayer(iMe), gc.getTeam(iTeam)
	if args.get("leader"):
		other = findPlayer(args["leader"])
		w = int(args.get("weight", 0))
		if w < 0:
			raise Exception("a weight is 0 or more")
		me.setEspionageSpendingWeightAgainstTeam(gc.getPlayer(other).getTeam(), w)
	rows = []
	for i in range(gc.getMAX_CIV_PLAYERS()):
		p = gc.getPlayer(i)
		if i == iMe or not p.isAlive() or not team.isHasMet(p.getTeam()):
			continue
		rows.append("%s: %d points; weight %d; %d new points a turn" % (pname(i), team.getEspionagePointsAgainstTeam(p.getTeam()),
			me.getEspionageSpendingWeightAgainstTeam(p.getTeam()), me.getEspionageSpending(p.getTeam())))
	return {"points_against": rows or ["no leader met"],
		"espionage_share_of_budget": "%d%%" % me.getCommercePercent(CommerceTypes.COMMERCE_ESPIONAGE),
		"how": "new points each turn are split by the weights (civ espionage <leader> <weight>); a spy's missions "
			"(civ actions <spy>) spend points against the leader whose land it stands in"}

def cmdVotes(args):
	# the Voting screen: each diplomatic body (Apostolic Palace, United Nations), its Resident, members and votes
	iMe, iTeam = myIds()
	g = gc.getGame()
	out = {}
	for vs in range(gc.getNumVoteSourceInfos()):
		name = gc.getVoteSourceInfo(vs).getDescription()
		if not g.isDiploVote(vs):
			out[name] = "not founded yet (its wonder hasn't been built); a win here: %s" % (
				"; ".join(victoryVotes(vs)) or "none")
			continue
		sec = g.getSecretaryGeneral(vs)
		resident = [pname(i) for i in range(gc.getMAX_CIV_PLAYERS()) if gc.getPlayer(i).isAlive() and gc.getPlayer(i).getTeam() == sec]
		members = []
		for i in range(gc.getMAX_CIV_PLAYERS()):
			p = gc.getPlayer(i)
			if not p.isAlive() or p.isBarbarian() or not (i == iMe or gc.getTeam(iTeam).isHasMet(p.getTeam())):
				continue
			if p.isVotingMember(vs):
				try:
					v = p.getVotes(-1, vs)
				except:
					v = "?"
				kind = " (votes only, not a full member)"
				if p.isFullMember(vs):
					kind = " (full member)"
				members.append("%s%s: %s votes" % (pname(i), kind, v))
		rel = g.getVoteSourceReligion(vs)
		# the game (CvGame::doVoteSelection) holds a session when the vote timer runs out, then sets it again to
		# `every`; the Resident's timer counts sessions, not turns: at 0 the next session is an election
		every = gc.getVoteSourceInfo(vs).getVoteInterval() * gc.getGameSpeedInfo(g.getGameSpeedType()).getVictoryDelayPercent() / 100
		sessions = g.getSecretaryGeneralTimer(vs)
		out[name] = {"religion": rel >= 0 and gc.getReligionInfo(rel).getDescription() or "-",
			"resident": ", ".join(resident) or "none yet",
			"members (leaders you know)": members or ["none"],
			"next session in turns": g.getVoteTimer(vs),
			"next session holds": sessions == 0 and "the election of the Resident (no resolution that session)" or
				"a resolution the Resident chooses (the Resident gets it as a proposal when the session opens)",
			"next Resident election in turns": g.getVoteTimer(vs) + sessions * (every + 1),
			"diplomatic victory": victoryVotes(vs) or ["no resolution here wins the game"]}
	return out

def cmdBuild(args):
	# what a city of ours builds: replace the current item (default), queue=true to add at the end,
	# first=true to put it in front; check=true only tells whether it is possible
	iMe, iTeam = myIds()
	if args.get("words"):
		# "Addis Ababa Library": the longest start of the words that names a city is the city
		words = args["words"]
		for k in range(len(words) - 1, 0, -1):
			try:
				findCity({"name": " ".join(words[:k])})
			except:
				continue
			args["name"], args["item"] = " ".join(words[:k]), " ".join(words[k:])
			break
		else:
			args["name"], args["item"] = words[0], " ".join(words[1:])
	c = findCity(args)
	if c.getOwner() != iMe:
		raise Exception("%s is not our city" % c.getName())
	if args["item"].strip().lower() in ("", "list", "options", "?"):
		# no item: what the city builds now and what it could build (asking, not ordering)
		return {"city": c.getName(), "queue": [orderName(c.getOrderFromQueue(k)) for k in range(c.getOrderQueueLength())] or "nothing",
			"can_build": ", ".join(buildableNow(c)), "order": "civ build %s <item> [--queue|--first]" % c.getName()}
	if args["item"].strip().lower() == "auto":
		# hand the city to the game's automation: the built-in AI picks its builds
		d = loadCityClaims()
		if d.has_key(cityKey(c)):
			del d[cityKey(c)]
			saveCityClaims(d)
		if g_queueWaiting.has_key(cityKey(c)):
			del g_queueWaiting[cityKey(c)]
		return {"city": c.getName(), "builds": "chosen by the game's automation until you `civ build` here",
			"queue": [orderName(c.getOrderFromQueue(k)) for k in range(c.getOrderQueueLength())]}
	order, i, name = findItem(args["item"])
	# a building or project already in the queue can't be added twice (the game's rule): --queue says where it
	# is, --first moves it to the front, a plain build makes it the only item
	inQueue = [k for k in range(c.getOrderQueueLength()) if int(c.getOrderFromQueue(k).eOrderType) == int(order)
		and c.getOrderFromQueue(k).iData1 == i and order != OrderTypes.ORDER_TRAIN]
	if inQueue and not args.get("check"):
		k = inQueue[0]
		if args.get("queue") or (args.get("first") and k == 0):
			return {"city": c.getName(), "queue": [orderName(c.getOrderFromQueue(j)) for j in range(c.getOrderQueueLength())],
				"note": "%s is already in the queue (place %d of %d); nothing changed" % (name, k + 1, c.getOrderQueueLength()),
				"turns": c.getProductionTurnsLeft()}
		if args.get("first"):
			c.popOrder(k, False, False)   # the hammers stay with the building; it goes back in at the front below
	if order == OrderTypes.ORDER_TRAIN:
		possible = c.canTrain(i, False, False)
	elif order == OrderTypes.ORDER_CONSTRUCT:
		possible = c.canConstruct(i, bool(inQueue), False, False)
	elif order == OrderTypes.ORDER_CREATE:
		possible = c.canCreate(i, False, False)
	else:
		possible = c.canMaintain(i, False)
	if not possible:
		raise Exception("%s can't build %s now: %s. It can build now: %s" % (c.getName(), name, whyCantBuild(c, order, i),
			", ".join(buildableNow(c))))
	if g_queueWaiting.has_key(cityKey(c)):
		del g_queueWaiting[cityKey(c)]
	if args.get("check"):
		return {"city": c.getName(), "item": name, "possible": True}
	if args.get("queue"):
		c.pushOrder(order, i, -1, False, False, True, False)
	elif args.get("first"):
		c.pushOrder(order, i, -1, False, False, False, True)
	else:
		dropped = [orderName(c.getOrderFromQueue(k)) for k in range(c.getOrderQueueLength())]
		c.clearOrderQueue()
		c.pushOrder(order, i, -1, False, True, False, True)
	claimCity(c)
	if not args.get("check"):
		noteAct("build", (c.getX(), c.getY(), "%s in %s" % (name, c.getName())))
	r = {"city": c.getName(), "queue": [orderName(c.getOrderFromQueue(k)) for k in range(c.getOrderQueueLength())],
		"turns": c.getProductionTurnsLeft()}
	if not args.get("queue") and not args.get("first") and dropped and dropped != [name] and dropped != r["queue"]:
		# a plain build replaces the whole queue: say what went, so a meant "after that" is seen at once
		r["replaced"] = "%s (gone from the queue; the hammers already in go to the new item; to add after instead: civ build %s <item> --queue)" % (
			", ".join(dropped), c.getName())
	return r


def hurryCivics(have, c=None):
	# the hurry kinds we can't use now, and why: a civic we don't have, or the price, or the city's state
	out = []
	p = gc.getPlayer(getClaudePlayer())
	for h in range(gc.getNumHurryInfos()):
		if h in have:
			continue
		name = gc.getHurryInfo(h).getType()[len("HURRY_"):].lower()
		if not p.canHurry(h):
			civics = [gc.getCivicInfo(k).getDescription() for k in range(gc.getNumCivicInfos()) if gc.getCivicInfo(k).isHurry(h)]
			out.append("%s: %s" % (name, civics and "needs the civic " + " or ".join(civics) or "not possible"))
		elif c is not None and c.hurryGold(h) > p.getGold():
			out.append("%s: costs %d gold, we have %d" % (name, c.hurryGold(h), p.getGold()))
		elif c is not None and c.isDisorder():
			out.append("%s: not while the city is in disorder" % name)
		else:
			out.append("%s: our civics allow it, but not for this build or this turn (the game's rule)" % name)
	return out or ["-"]

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
				for (n, h, pop, gold, anger) in opts] or ["no"],
			"other_ways": hurryCivics([o[1] for o in opts], c)}
	want = args["how"].lower()
	m = [o for o in opts if o[0] == want or (want == "whip" and o[2] > 0) or (want in ("buy", "gold") and o[2] == 0 and o[3] > 0)]
	if not m:
		raise Exception("%s can't hurry by %s now. Options: %s" % (c.getName(), want, ", ".join([o[0] for o in opts]) or "none"))
	n, h, pop, gold, anger = m[0]
	c.hurry(HurryTypes(h))
	writeEvent("hurried", {"city": c.getName(), "item": building, "population": pop, "gold": gold})
	return {"city": c.getName(), "hurried": building, "paid_population": pop, "paid_gold": gold,
		"finishes": "at the start of our next turn"}

g_queueWaiting = {}

def aiChooseProduction(gu, argsList):
	# the game clears a city's queue before asking us, so we put Claude's remaining
	# items back; only when Claude's queue is used up does the built-in AI choose
	c = argsList[0]
	d = loadCityClaims()
	q = d.get(cityKey(c))
	if q:
		if c.getOrderQueueLength() == 0:
			for (order, data) in q:
				c.pushOrder(OrderTypes(order), data, -1, False, False, True, False)
		if c.getOrderQueueLength() > 0:
			return True
		if engineControl():
			# nothing on Claude's list can be built any more (a wonder finished elsewhere...): wait for him
			d[cityKey(c)] = []
			saveCityClaims(d)
			if not g_queueWaiting.has_key(cityKey(c)):
				g_queueWaiting[cityKey(c)] = True
				writeEvent("city_queue_done", {"city": c.getName(), "note": "nothing on your build list here can be built "
					"any more; the city builds nothing until you `civ build` (or `civ build %s auto`)" % c.getName()})
			return True
	elif q is not None and c.getOwner() == getClaudePlayer():
		if engineControl():
			# the list is done: the city waits for Claude (as a human's city waits for its owner)
			if not g_queueWaiting.has_key(cityKey(c)):
				g_queueWaiting[cityKey(c)] = True
				writeEvent("city_queue_done", {"city": c.getName(),
					"note": "your build list here is finished and the city builds nothing until you `civ build` "
					"(or `civ build %s auto` hands it to the game's automation)" % c.getName()})
			return True
		# Claude's list for this city is done: tell Claude once, the built-in AI fills in meanwhile
		del d[cityKey(c)]
		saveCityClaims(d)
		writeEvent("city_queue_done", {"city": c.getName(),
			"note": "your build list here is finished; the built-in AI picks until you `civ build` again"})
	return gu._claudeOrigChooseProduction(argsList)

def chooseProductionTrampoline(argsList):
	import CvGameInterfaceFile
	B = sys.modules["ClaudeBridge"]
	return B.asSeatOf(argsList[0].getOwner(), B.aiChooseProduction, CvGameInterfaceFile.GameUtils, argsList)

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

g_heldSince = {}

def readyButHeld():
	# an agent said ready but the engine still holds its turn (a unit left "ready to move" that the engine's
	# own unit update didn't reach). After a minute: log what holds it (to find the cause) and let the bridge's
	# unit hook answer for those units, as the engine should have
	if not seatsConfigured():
		return
	now = time.time()
	for i in agentPlayers():
		p = gc.getPlayer(i)
		if not (p.isAlive() and p.isTurnActive() and p.isClaudeReady()):
			g_heldSince.pop(i, None)
			continue
		since = g_heldSince.setdefault(i, now)
		if now - since < 60:
			continue
		g_heldSince[i] = now   # at most once a minute
		held, busy = [], []
		import CvGameInterfaceFile
		(u, it) = p.firstUnit(False)
		while u and not u.isNone():
			g = u.getGroup()
			if g.getHeadUnit().getID() == u.getID():
				if g.readyToMove(False):
					held.append(u)
				elif g.getLengthMissionQueue() > 0:
					busy.append("#%d %s" % (u.getID(), gc.getUnitInfo(u.getUnitType()).getType()))
			(u, it) = p.nextUnit(it, False)
		log("player %d ready but its turn is held: ready-to-move %s; with orders %s" % (i,
			["#%d %s at %d,%d" % (x.getID(), gc.getUnitInfo(x.getUnitType()).getType(), x.getX(), x.getY()) for x in held], busy))
		for u in held:
			asSeatOf(i, aiUnitUpdate, CvGameInterfaceFile.GameUtils, [u])

def ensureSimultaneousTurns():
	# several agents play each turn at once (like a simultaneous-turns multiplayer game): every civ's turn
	# is active together, so an agent's order runs when given, not after the civs before it are done
	g = gc.getGame()
	if seatsConfigured() and hasattr(g, "claudeSetSimultaneousTurns") and not g.claudeSimultaneousTurns():
		g.claudeSetSimultaneousTurns(True)
		log("simultaneous turns on")

def seatsOnLoad():
	# a loaded save does not remember which agents were done: hold every agent's civ and wake it for this turn,
	# or the game would play the turn without them
	g_camera["debug_tried"] = False   # a new map on screen: set the spectator's view up again
	try:
		if seatsConfigured():
			forEachSeat(seatTurnStart, gc.getGame().getGameTurn())
	except:
		log("seats on load FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))

def announceShips(arg=None):
	# a spaceship launch is announced to every leader by the game: this seat hears of each launch once
	p = gc.getPlayer(getClaudePlayer())
	g = readGate()
	heard = g.get("ships_heard") or []
	for t in range(gc.getMAX_CIV_TEAMS()):
		for v in range(gc.getNumVictoryInfos()):
			c = gc.getTeam(t).getVictoryCountdown(v)
			key = "%d:%d" % (t, v)
			if gc.getTeam(t).isAlive() and c > 0 and key not in heard:
				heard.append(key)
				writeEvent("spaceship_launched", {"by": t == p.getTeam() and "us" or teamName(t),
					"arrives_in_turns": c, "note": "the game is won when it arrives; taking its owner's capital destroys it"})
	g["ships_heard"] = heard
	writeGate(g)

def seatTurnStart(turn):
	# a game of several agents: every agent plays every turn; the engine holds its civ's turn until it is ready
	iMe = getClaudePlayer()
	p = gc.getPlayer(iMe)
	if not p.isAlive():
		return
	if hasattr(p, "setClaudeReady"):
		p.setClaudeReady(False)
	announceShips()
	g = readGate()
	reasons = list(g.get("attention") or []) + ["turn"]
	g["on"] = True
	g["ready_turn"] = -1
	writeGate(g)
	g_acts[iMe] = {"turn": turn, "t0": camClock(), "moves": [], "builds": [], "say": 0, "offer": 0}
	writeEvent("claude_wake", {"turn": turn, "reasons": reasons})

def setReady(byWhom):
	g = readGate()
	if seatsConfigured():
		g["ready_turn"] = gc.getGame().getGameTurn()
		g["attention"] = []
		writeGate(g)
		p = gc.getPlayer(getClaudePlayer())
		if hasattr(p, "setClaudeReady"):
			p.setClaudeReady(True)   # the engine lets this civ's turn end
		writeEvent("claude_ready", {"by": byWhom})
		if spectating():
			queueRecap(getClaudePlayer())
		return
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
	"great_person", "golden_age", "unit_arrived", "unit_done", "deal_done", "deal_declined", "deal_failed", "native_deal", "unit_disbanded", "proposal", "diplomacy", "treasury_empty", "order_failed",
	"unit_waiting", "city_queue_done", "deal_ended", "budget_suspended")

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
	if not g.get("on"):
		return
	if not g.get("auto"):
		# auto-ready off means "wake me every turn": the gate stays closed until Claude says ready
		reasons = list(g.get("attention") or []) + ["turn"]
		writeGate(g)
		writeEvent("claude_wake", {"turn": turn, "reasons": reasons})
		return
	reasons = list(g.get("attention") or [])
	enemies = enemiesNear()
	if enemies and sorted(enemies) != sorted(g.get("last_enemies") or []):
		# only when something changed: the same stack standing still is no news
		reasons.append("enemy_near: " + "; ".join(enemies[:5]))
	g["last_enemies"] = enemies
	me = gc.getPlayer(myIds()[0])
	if me.getCurrentResearch() < 0 and me.getNumCities() > 0:
		reasons.append("research_idle")
	every = int(g.get("review_every") or 5)
	if every > 0 and turn % every == 0:
		reasons.append("review")
	if reasons:
		writeGate(g)
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
			# the first press on each turn wakes Claude; after that, a reminder once in a while
			turn = gc.getGame().getGameTurn()
			first = g_gateNag[1:] != [turn]
			g_gateNag[1:] = [turn]
			g_gateNag[0] = first and 1 or g_gateNag[0] + 1
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
	if seatsConfigured():
		if not spectating():   # a filmed spectator's screen keeps its message panel for the leaders' words
			CyInterface().addImmediateMessage(u"%s is done with this turn." % gc.getPlayer(getClaudePlayer()).getName(), "")
		return {"ready_turn": readGate()["ready_turn"]}
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
	"notice": cmdNotice,
	"exec": cmdExec,
	"move": cmdMove,
	"research": cmdResearch,
	"area": cmdArea,
	"actions": cmdActions,
	"offer": cmdOffer,
	"offers": cmdOffers,
	"proposals": cmdProposals,
	"answer": cmdAnswer,
	"tradeable": cmdTradeable,
	"relations": cmdRelations,
	"victory": cmdVictory,
	"religion": cmdReligion,
	"civics": cmdCivics,
	"rules": cmdRules,
	"war": cmdWar,
	"deals": cmdDeals,
	"ratify": cmdRatify,
	"reject": cmdReject,
	"cancel": cmdCancel,
	"budget": cmdBudget,
	"raze": cmdRaze,
	"do": cmdDo,
	"build": cmdBuild,
	"work": cmdWork,
	"votes": cmdVotes,
	"espionage": cmdEspionage,
	"spaceship": cmdSpaceship,
	"hurry": cmdHurry,
	"ping": cmdPing,
	"status": cmdStatus,
	"map": cmdMap,
	"tile": cmdTile,
	"odds": cmdOdds,
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
			if int(req["player"]) != getClaudePlayer() and not multiAgent() and not seatsConfigured():
				writeEvent("fair_play_alert", {"what": "a request tried to act for player %s" % req["player"], "cmd": cmd})
				raise Exception("acting for another civ is only allowed in multi-agent games (config.txt: multi = yes)")
			if seatsConfigured() and int(req["player"]) not in agentPlayers():
				raise Exception("player %s is not one of this game's agents" % req["player"])
		elif seatsConfigured() and cmd not in ("ping", "exec"):
			raise Exception("this game has several agents: the request must name its player (CIV_PLAYER)")
		seat = None
		if req.get("player") is not None:
			seat = int(req["player"])   # player 0 is a seat too, so no "x and y or z" here
		prev = actAs(seat)
		if cmd == "exec":
			cmdExecGuard(req.get("args") or {}, req)
		try:
			reply = {"id": rid, "ok": True, "result": COMMANDS[cmd](req.get("args") or {})}
		finally:
			actAs(prev)
	except:
		reply = {"id": rid, "ok": False,
			"error": "".join(traceback.format_exception(*sys.exc_info()))}
	writeAtomic(REPLY_DIR + "\\" + str(rid) + ".json", toJson(reply))
	log("reply %s ok=%s" % (rid, reply["ok"]))

def seatUpkeep(pending):
	try:
		ensureEngineControl()
	except:
		log("engine control FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
	try:
		guardChoices(pending)   # answers always see the state with the AI's moves undone
	except:
		log("choices guard FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
	try:
		checkpointTick()
	except:
		log("native deal check FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))

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
		if gameReady():
			try:
				askModels()
			except:
				g_modelAsk["pending"] = -1
				log("model picker FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
			try:
				readyButHeld()
			except:
				log("ready-but-held check FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
			try:
				ensureSimultaneousTurns()
			except:
				log("simultaneous turns FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
			try:
				spectatorView()
			except:
				log("spectator view FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
			try:
				if spectating():
					chatPanel()
			except:
				g_chat["lines"] = []
				log("chat panel FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
			try:
				cameraman()
			except:
				g_camera["until"] = camClock() + 60   # a broken shot must not flood the log
				log("cameraman FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
			if seatsConfigured():
				forEachSeat(seatUpkeep, bool(names))
			else:
				seatUpkeep(bool(names))
		names = [n for n in os.listdir(IN_DIR) if n.endswith(".json")]
		names.sort()
		for n in names:
			handleRequest(n)
	except:
		log("poll FAILED:\n%s" % "".join(traceback.format_exception(*sys.exc_info())))
