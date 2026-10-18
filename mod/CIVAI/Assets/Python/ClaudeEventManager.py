# ClaudeBridge: stock event manager + bridge to Claude.
#
# - Requests from the Mac-side `civ` tool are answered from the per-frame events.
# - The world is dumped at the start of Claude's turn, at game start and on load.
# - Game events Claude would know about are appended to events.jsonl.
#
# Two quirks of Civ IV's embedded Python shape this file:
# - time.time() is useless for short intervals: the graphics engine runs the FPU in
#   single precision, so the clock moves in 128-second steps. Use frame counters.
# - Python files are cached at game start, so reload() returns stale code. The bridge
#   is therefore loaded with imp.load_source straight from disk, and re-loaded when
#   the file on disk changes. (This file and the XML still need a game restart.)

from CvPythonExtensions import *
import CvEventManager
import imp
import os
import sys
import traceback

BRIDGE_SRC = "Mods\\CIVAI\\Assets\\Python\\ClaudeBridge.py"
POLL_EVERY_FRAMES = 4       # ~5 times a second at 20 fps
RELOAD_CHECK_FRAMES = 40    # ~every 2 seconds
HEARTBEAT_FRAMES = 1200     # ~every minute

def fileStamp(path):
	st = os.stat(path)
	return (st[6], st[8])  # size and integer mtime; float mtimes suffer the same FPU issue

def loadBridge():
	if os.path.exists(BRIDGE_SRC):
		return imp.load_source("ClaudeBridge", BRIDGE_SRC), fileStamp(BRIDGE_SRC)
	import ClaudeBridge
	return ClaudeBridge, None

B, g_stamp = loadBridge()
B.log("bridge loaded from %s" % (g_stamp and BRIDGE_SRC or "the game's Python cache (hot reload off)"))
g_frames = {"Update": 0, "gameUpdate": 0, "total": 0}

def maybeReload():
	global B, g_stamp
	if g_stamp is None:
		return
	try:
		stamp = fileStamp(BRIDGE_SRC)
	except:
		return  # file is being rewritten; try again later
	if stamp == g_stamp:
		return
	g_stamp = stamp
	try:
		B = imp.load_source("ClaudeBridge", BRIDGE_SRC)
		B.log("hot-reloaded bridge v%s" % B.BRIDGE_VERSION)
	except:
		B.log("hot reload FAILED:\n" + "".join(traceback.format_exception(*sys.exc_info())))

def tick(tag):
	g_frames[tag] = g_frames[tag] + 1
	g_frames["total"] = g_frames["total"] + 1
	n = g_frames["total"]
	if n % RELOAD_CHECK_FRAMES == 0:
		maybeReload()
	if tag == "gameUpdate" or n % POLL_EVERY_FRAMES == 0:
		B.poll()
	if n % HEARTBEAT_FRAMES == 0:
		B.log("heartbeat: Update=%d gameUpdate=%d" % (g_frames["Update"], g_frames["gameUpdate"]))
		g_frames["Update"] = 0
		g_frames["gameUpdate"] = 0


class ClaudeEventManager(CvEventManager.CvEventManager):

	def handleEvent(self, argsList):
		# one hook for every game event: run the stock handler, then log what Claude would know
		ret = CvEventManager.CvEventManager.handleEvent(self, argsList)
		tag = argsList[0]
		if tag not in ("Update", "gameUpdate", "mouseEvent", "kbdEvent"):
			B.safeRecordEvent(tag, argsList[1:len(argsList) - 6])
		return ret

	def onUpdate(self, argsList):
		CvEventManager.CvEventManager.onUpdate(self, argsList)
		tick("Update")

	def onGameUpdate(self, argsList):
		# fires on every game tick even without USE_ON_UPDATE_CALLBACK
		CvEventManager.CvEventManager.onGameUpdate(self, argsList)
		tick("gameUpdate")

	def onWindowActivation(self, argsList):
		CvEventManager.CvEventManager.onWindowActivation(self, argsList)
		B.log("window %s" % (argsList[0] and "activated" or "deactivated"))

	def onGameStart(self, argsList):
		CvEventManager.CvEventManager.onGameStart(self, argsList)
		B.safeDump("game_start")

	def onLoadGame(self, argsList):
		result = CvEventManager.CvEventManager.onLoadGame(self, argsList)
		B.safeDump("load_game")
		B.seatsOnLoad()
		return result

	def onBeginPlayerTurn(self, argsList):
		CvEventManager.CvEventManager.onBeginPlayerTurn(self, argsList)
		iGameTurn, iPlayer = argsList
		if iPlayer == B.getClaudePlayer():
			B.safeDump("begin_turn")
