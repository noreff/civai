# Sid Meier's Civilization 4
# Copyright Firaxis Games 2005
#
# CvEventInterface.py -- ClaudeBridge version
#
# Same as the stock file, but routes events through ClaudeEventManager,
# which adds a world-state dump on top of the normal game behaviour.
#
import CvUtil
import ClaudeEventManager
from CvPythonExtensions import *

normalEventManager = ClaudeEventManager.ClaudeEventManager()

def getEventManager():
	return normalEventManager

def onEvent(argsList):
	'Called when a game event happens - return 1 if the event was consumed'
	return getEventManager().handleEvent(argsList)

def applyEvent(argsList):
	context, playerID, netUserData, popupReturn = argsList
	return getEventManager().applyEvent(argsList)

def beginEvent(context, argsList=-1):
	return getEventManager().beginEvent(context, argsList)
