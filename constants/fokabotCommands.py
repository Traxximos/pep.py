import json
import random
import re
import threading

import requests
import time

from common import generalUtils
from common.constants import mods
from common.log import logUtils as log
from common.ripple import userUtils
from constants import exceptions, slotStatuses, matchModModes, matchTeams, matchTeamTypes
from common.constants import gameModes
from common.constants import privileges
from constants import serverPackets
from helpers import systemHelper
from objects import fokabot
from objects import glob
from helpers import chatHelper as chat
from common.web import cheesegull

"""
Commands callbacks

Must have fro, chan and messages as arguments
:param fro: username of who triggered the command
:param chan: channel"(or username, if PM) where the message was sent
:param message: list containing arguments passed from the message
				[0] = first argument
				[1] = second argument
				. . .

return the message or **False** if there's no response by the bot
TODO: Change False to None, because False doesn't make any sense
"""
def instantRestart(fro, chan, message):
	glob.streams.broadcast("main", serverPackets.notification("Bancho is restarting, it will be back online momentarily.."))
	systemHelper.scheduleShutdown(0, True, delay=5)
	return False

def faq(fro, chan, message):
	if message[0] in glob.conf.extra["faq"]:
		return glob.conf.extra["faq"][message[0]]
	return False

def roll(fro, chan, message):
	maxPoints = 100
	if len(message) >= 1:
		if message[0].isdigit() == True and int(message[0]) > 0:
			maxPoints = int(message[0])

	points = random.randrange(0,maxPoints)
	return "{} rolls {} points!".format(fro, str(points))

#def ask(fro, chan, message):
#	return random.choice(["yes", "no", "maybe"])

def alert(fro, chan, message):
	msg = ' '.join(message[:])
	if not msg.strip():
		return False
	glob.streams.broadcast("main", serverPackets.notification(msg))
	return False

def alertUser(fro, chan, message):
	target = message[0].lower()
	targetToken = glob.tokens.getTokenFromUsername(userUtils.safeUsername(target), safe=True)
	if targetToken is not None:
		msg = ' '.join(message[1:])
		if not msg.strip():
			return False
		targetToken.enqueue(serverPackets.notification(msg))
		return False
	else:
		return "User offline."

def moderated(fro, chan, message):
	try:
		# Make sure we are in a channel and not PM
		if not chan.startswith("#"):
			raise exceptions.moderatedPMException

		# Get on/off
		enable = True
		if len(message) >= 1:
			if message[0] == "off":
				enable = False

		# Turn on/off moderated mode
		glob.channels.channels[chan].moderated = enable
		return "This channel is {} in moderated mode!".format("now" if enable else "no longer")
	except exceptions.moderatedPMException:
		return "You cannot put a private chat in moderated mode.. Duh"

def kickAll(fro, chan, message):
	# Kick everyone but mods/admins
	toKick = []
	with glob.tokens:
		for key, value in glob.tokens.tokens.items():
			if not value.admin:
				toKick.append(key)

	# Loop though users to kick (we can't change dictionary size while iterating)
	for i in toKick:
		if i in glob.tokens.tokens:
			glob.tokens.tokens[i].kick()

	return "Whoops! Rip everyone."

def kick(fro, chan, message):
	# Get parameters
	target = message[0].lower()
	if target == glob.BOT_NAME.lower():
		return "Nope."

	# Get target token and make sure is connected
	tokens = glob.tokens.getTokenFromUsername(userUtils.safeUsername(target), safe=True, _all=True)
	if len(tokens) == 0:
		return "{} is not online".format(target)

	# Kick users
	for i in tokens:
		i.kick()

	# Bot response
	return "{} has been kicked from the server.".format(target)

def fokabotReconnect(fro, chan, message):
	# Check if fokabot is already connected
	if glob.tokens.getTokenFromUserID(999) is not None:
		return "{} is already connected to Bancho".format(glob.BOT_NAME)

	# Fokabot is not connected, connect it
	fokabot.connect()
	return False

def silence(fro, chan, message):
	for i in message:
		i = i.lower()
	target = message[0]
	amount = message[1]
	unit = message[2]
	reason = ' '.join(message[3:])

	# Get target user ID
	targetUserID = userUtils.getIDSafe(target)
	userID = userUtils.getID(fro)

	# Make sure the user exists
	if not targetUserID:
		return "{}: user not found".format(target)

	# Calculate silence seconds
	if unit == 's':
		silenceTime = int(amount)
	elif unit == 'm':
		silenceTime = int(amount) * 60
	elif unit == 'h':
		silenceTime = int(amount) * 3600
	elif unit == 'd':
		silenceTime = int(amount) * 86400
	else:
		return "Invalid time unit (s/m/h/d)."

	# Max silence time is 7 days
	if silenceTime > 604800:
		return "Invalid silence time. The maximum silence time is 7 days."

	# Send silence packet to target if he's connected
	targetToken = glob.tokens.getTokenFromUsername(userUtils.safeUsername(target), safe=True)
	if targetToken is not None:
		# user online, silence both in db and with packet
		targetToken.silence(silenceTime, reason, userID)
	else:
		# User offline, silence user only in db
		userUtils.silence(targetUserID, silenceTime, reason, userID)

	# Log message
	msg = "{} has been silenced for the following reason: {}".format(target, reason)
	return msg

def removeSilence(fro, chan, message):
	# Get parameters
	for i in message:
		i = i.lower()
	target = message[0]

	# Make sure the user exists
	targetUserID = userUtils.getIDSafe(target)
	userID = userUtils.getID(fro)
	if not targetUserID:
		return "{}: user not found".format(target)

	# Send new silence end packet to user if he's online
	targetToken = glob.tokens.getTokenFromUsername(userUtils.safeUsername(target), safe=True)
	if targetToken is not None:
		# User online, remove silence both in db and with packet
		targetToken.silence(0, "", userID)
	else:
		# user offline, remove islene ofnlt from db
		userUtils.silence(targetUserID, 0, "", userID)

	return "{}'s silence reset".format(target)

def ban(fro, chan, message):
	# Get parameters
	for i in message:
		i = i.lower()
	target = message[0]

	# Make sure the user exists
	targetUserID = userUtils.getIDSafe(target)
	userID = userUtils.getID(fro)
	if not targetUserID:
		return "{}: user not found".format(target)

	# Set allowed to 0
	userUtils.ban(targetUserID)

	# Send ban packet to the user if he's online
	targetToken = glob.tokens.getTokenFromUsername(userUtils.safeUsername(target), safe=True)
	if targetToken is not None:
		targetToken.enqueue(serverPackets.loginBanned())

	log.rap(userID, "has banned {}".format(target), True)
	return "{} has been banned.".format(target)

def unban(fro, chan, message):
	# Get parameters
	for i in message:
		i = i.lower()
	target = message[0]

	# Make sure the user exists
	targetUserID = userUtils.getIDSafe(target)
	userID = userUtils.getID(fro)
	if not targetUserID:
		return "{}: user not found".format(target)

	# Set allowed to 1
	userUtils.unban(targetUserID)

	log.rap(userID, "has unbanned {}".format(target), True)
	return "{} has been unbanned.".format(target)

def restrict(fro, chan, message):
	# Get parameters
	for i in message:
		i = i.lower()
	target = message[0]

	# Make sure the user exists
	targetUserID = userUtils.getIDSafe(target)
	userID = userUtils.getID(fro)
	if not targetUserID:
		return "{}: user not found".format(target)

	# Put this user in restricted mode
	userUtils.restrict(targetUserID)

	# Send restricted mode packet to this user if he's online
	targetToken = glob.tokens.getTokenFromUsername(userUtils.safeUsername(target), safe=True)
	if targetToken is not None:
		targetToken.setRestricted()

	log.rap(userID, "has put {} in restricted mode".format(target), True)
	return "{} has been restricted.".format(target)

def unrestrict(fro, chan, message):
	# Get parameters
	for i in message:
		i = i.lower()
	target = message[0]

	# Make sure the user exists
	targetUserID = userUtils.getIDSafe(target)
	userID = userUtils.getID(fro)
	if not targetUserID:
		return "{}: user not found".format(target)

	# Set allowed to 1
	userUtils.unrestrict(targetUserID)

	log.rap(userID, "has removed restricted mode from {}".format(target), True)
	return "{} has been unrestricted.".format(target)

def restartShutdown(restart):
	"""Restart (if restart = True) or shutdown (if restart = False) pep.py safely"""
	msg = "We are performing some maintenance. Bancho will {} in 5 seconds. Thank you for your patience.".format("restart" if restart else "shutdown")
	systemHelper.scheduleShutdown(5, restart, msg)
	return msg

def systemRestart(fro, chan, message):
	return restartShutdown(True)

def systemShutdown(fro, chan, message):
	return restartShutdown(False)

def systemReload(fro, chan, message):
	glob.banchoConf.reload()
	return "Bancho settings reloaded!"

def systemMaintenance(fro, chan, message):
	# Turn on/off bancho maintenance
	maintenance = True

	# Get on/off
	if len(message) >= 2:
		if message[1] == "off":
			maintenance = False

	# Set new maintenance value in bancho_settings table
	glob.banchoConf.setMaintenance(maintenance)

	if maintenance:
		# We have turned on maintenance mode
		# Users that will be disconnected
		who = []

		# Disconnect everyone but mod/admins
		with glob.tokens:
			for _, value in glob.tokens.tokens.items():
				if not value.admin:
					who.append(value.userID)

		glob.streams.broadcast("main", serverPackets.notification("Our bancho server is in maintenance mode. Please try to login again later."))
		glob.tokens.multipleEnqueue(serverPackets.loginError(), who)
		msg = "The server is now in maintenance mode!"
	else:
		# We have turned off maintenance mode
		# Send message if we have turned off maintenance mode
		msg = "The server is no longer in maintenance mode!"

	# Chat output
	return msg


def systemStatus(fro, chan, message):
	# Print some server info
	data = systemHelper.getSystemInfo()

	# Final message
	letsVersion = glob.redis.get("lets:version")
	if letsVersion is None:
		letsVersion = "\_(xd)_/"
	else:
		letsVersion = letsVersion.decode("utf-8")
	msg = "pep.py bancho server v{}\n".format(glob.VERSION)
	msg += "LETS scores server v{}\n".format(letsVersion)
	msg += "made by the Ripple & Akatsuki teams\n"
	msg += "\n"
	msg += "=== BANCHO STATS ===\n"
	msg += "Connected users: {}\n".format(data["connectedUsers"])
	msg += "Multiplayer matches: {}\n".format(data["matches"])
	msg += "Uptime: {}\n".format(data["uptime"])
	msg += "\n"
	msg += "=== SYSTEM STATS ===\n"
	msg += "CPU: {}%\n".format(data["cpuUsage"])
	msg += "RAM: {}GB/{}GB\n".format(data["usedMemory"], data["totalMemory"])
	if data["unix"]:
		msg += "Load average: {}/{}/{}\n".format(data["loadAverage"][0], data["loadAverage"][1], data["loadAverage"][2])

	return msg


def getPPMessage(userID, just_data = False):
	try:
		# Get user token
		token = glob.tokens.getTokenFromUserID(userID)
		if token is None:
			return False

		currentMap = token.tillerino[0]
		currentMods = token.tillerino[1]
		currentAcc = token.tillerino[2]

		# Send request to LETS api
		resp = requests.get("http://127.0.0.1:5002/api/v1/pp?b={}&m={}".format(currentMap, currentMods), timeout=10).text
		data = json.loads(resp)

		# Make sure status is in response data
		if "status" not in data:
			raise exceptions.apiException

		# Make sure status is 200
		if data["status"] != 200:
			if "message" in data:
				return "Error in LETS API call ({}).".format(data["message"])
			else:
				raise exceptions.apiException

		if just_data:
			return data

		# Return response in chat
		# Song name and mods
		msg = "{song}{plus}{mods}  ".format(song=data["song_name"], plus="+" if currentMods > 0 else "", mods=generalUtils.readableMods(currentMods))

		# PP values
		if currentAcc == -1:
			msg += "95%: {pp95}pp | 98%: {pp98}pp | 99% {pp99}pp | 100%: {pp100}pp".format(pp100=data["pp"][0], pp99=data["pp"][1], pp98=data["pp"][2], pp95=data["pp"][3])
		else:
			msg += "{acc:.2f}%: {pp}pp".format(acc=token.tillerino[2], pp=data["pp"][0])
		
		originalAR = data["ar"]
		# calc new AR if HR/EZ is on
		if (currentMods & mods.EASY) > 0:
			data["ar"] = max(0, data["ar"] / 2)
		if (currentMods & mods.HARDROCK) > 0:
			data["ar"] = min(10, data["ar"] * 1.4)
		
		arstr = " ({})".format(originalAR) if originalAR != data["ar"] else ""
		
		# Beatmap info
		msg += " | {bpm} BPM | AR {ar}{arstr} | {stars:.2f} stars".format(bpm=data["bpm"], stars=data["stars"], ar=data["ar"], arstr=arstr)

		# Return final message
		return msg
	except requests.exceptions.RequestException:
		# RequestException
		return "API Timeout. Please try again in a few seconds."
	except exceptions.apiException:
		# API error
		return "Unknown error in LETS API call."
	#except:
		# Unknown exception
		# TODO: print exception
	#	return False

def tillerinoNp(fro, chan, message):
	try:
		# Run the command in PM only
		if chan.startswith("#"):
			return False

		playWatch = message[1] == "playing" or message[1] == "watching"
		# Get URL from message
		if message[1] == "listening":
			beatmapURL = str(message[3][1:])
		elif playWatch:
			beatmapURL = str(message[2][1:])
		else:
			return False

		modsEnum = 0
		mapping = {
			"-Easy": mods.EASY,
			"-NoFail": mods.NOFAIL,
			"+Hidden": mods.HIDDEN,
			"+HardRock": mods.HARDROCK,
			"+Nightcore": mods.NIGHTCORE,
			"+DoubleTime": mods.DOUBLETIME,
			"-HalfTime": mods.HALFTIME,
			"+Flashlight": mods.FLASHLIGHT,
			"-SpunOut": mods.SPUNOUT
		}

		if playWatch:
			for part in message:
				part = part.replace("\x01", "")
				if part in mapping.keys():
					modsEnum += mapping[part]

		# Get beatmap id from URL
		beatmapID = fokabot.npRegex.search(beatmapURL).groups(0)[0]

		# Update latest tillerino song for current token
		token = glob.tokens.getTokenFromUsername(fro)
		if token is not None:
			token.tillerino = [int(beatmapID), modsEnum, -1.0]
		userID = token.userID

		# Return tillerino message
		return getPPMessage(userID)
	except:
		return False


def tillerinoMods(fro, chan, message):
	try:
		# Run the command in PM only
		if chan.startswith("#"):
			return False

		# Get token and user ID
		token = glob.tokens.getTokenFromUsername(fro)
		if token is None:
			return False
		userID = token.userID

		# Make sure the user has triggered the bot with /np command
		if token.tillerino[0] == 0:
			return "Please give me a beatmap first with /np command."

		# Check passed mods and convert to enum
		modsList = [message[0][i:i+2].upper() for i in range(0, len(message[0]), 2)]
		modsEnum = 0
		for i in modsList:
			if i not in ["NO", "NF", "EZ", "HD", "HR", "DT", "HT", "NC", "FL", "SO"]:
				return "Invalid mods. Allowed mods: NO, NF, EZ, HD, HR, DT, HT, NC, FL, SO. Do not use spaces for multiple mods."
			if i == "NO":
				modsEnum = 0
				break
			elif i == "NF":
				modsEnum += mods.NOFAIL
			elif i == "EZ":
				modsEnum += mods.EASY
			elif i == "HD":
				modsEnum += mods.HIDDEN
			elif i == "HR":
				modsEnum += mods.HARDROCK
			elif i == "DT":
				modsEnum += mods.DOUBLETIME
			elif i == "HT":
				modsEnum += mods.HALFTIME
			elif i == "NC":
				modsEnum += mods.NIGHTCORE
			elif i == "FL":
				modsEnum += mods.FLASHLIGHT
			elif i == "SO":
				modsEnum += mods.SPUNOUT

		# Set mods
		token.tillerino[1] = modsEnum

		# Return tillerino message for that beatmap with mods
		return getPPMessage(userID)
	except:
		return False

def tillerinoAcc(fro, chan, message):
	try:
		# Run the command in PM only
		if chan.startswith("#"):
			return False

		# Get token and user ID
		token = glob.tokens.getTokenFromUsername(fro)
		if token is None:
			return False
		userID = token.userID

		# Make sure the user has triggered the bot with /np command
		if token.tillerino[0] == 0:
			return "Please give me a beatmap first with /np command."

		# Convert acc to float
		acc = float(message[0])

		# Set new tillerino list acc value
		token.tillerino[2] = acc

		# Return tillerino message for that beatmap with mods
		return getPPMessage(userID)
	except ValueError:
		return "Invalid acc value"
	except:
		return False

def tillerinoLast(fro, chan, message):
	try:
		# Run the command in PM only
		if chan.startswith("#"):
			return False
		data = glob.db.fetch("""SELECT beatmaps.song_name as sn, scores.*,
			beatmaps.beatmap_id as bid, beatmaps.difficulty_std, beatmaps.difficulty_taiko, beatmaps.difficulty_ctb, beatmaps.difficulty_mania, beatmaps.max_combo as fc
		FROM scores
		LEFT JOIN beatmaps ON beatmaps.beatmap_md5=scores.beatmap_md5
		LEFT JOIN users ON users.id = scores.userid
		WHERE users.username = %s
		ORDER BY scores.time DESC
		LIMIT 1""", [fro])
		if data is None:
			return False

		diffString = "difficulty_{}".format(gameModes.getGameModeForDB(data["play_mode"]))
		rank = generalUtils.getRank(data["play_mode"], data["mods"], data["accuracy"],
									data["300_count"], data["100_count"], data["50_count"], data["misses_count"])

		ifPlayer = "{0} | ".format(fro) if chan != glob.BOT_NAME else ""
		ifFc = " (FC)" if data["max_combo"] == data["fc"] else " {0}x/{1}x".format(data["max_combo"], data["fc"])
		beatmapLink = "[http://osu.ppy.sh/b/{1} {0}]".format(data["sn"], data["bid"])

		hasPP = data["play_mode"] != gameModes.CTB

		msg = ifPlayer
		msg += beatmapLink
		if data["play_mode"] != gameModes.STD:
			msg += " <{0}>".format(gameModes.getGameModeForPrinting(data["play_mode"]))

		if data["mods"]:
			msg += ' +' + generalUtils.readableMods(data["mods"])

		if not hasPP:
			msg += " | {0:,}".format(data["score"])
			msg += ifFc
			msg += " | {0:.2f}%, {1}".format(data["accuracy"], rank.upper())
			msg += " {{ {0} / {1} / {2} / {3} }}".format(data["300_count"], data["100_count"], data["50_count"], data["misses_count"])
			msg += " | {0:.2f} stars".format(data[diffString])
			return msg

		msg += " ({0:.2f}%, {1})".format(data["accuracy"], rank.upper())
		msg += ifFc
		msg += " | {0:.2f}pp".format(data["pp"])

		stars = data[diffString]
		if data["mods"]:
			token = glob.tokens.getTokenFromUsername(fro)
			if token is None:
				return False
			userID = token.userID
			token.tillerino[0] = data["bid"]
			token.tillerino[1] = data["mods"]
			token.tillerino[2] = data["accuracy"]
			oppaiData = getPPMessage(userID, just_data=True)
			if "stars" in oppaiData:
				stars = oppaiData["stars"]

		msg += " | {0:.2f} stars".format(stars)
		return msg
	except Exception as a:
		log.error(a)
		return False

def pp(fro, chan, message):
	if chan.startswith("#"):
		return False

	gameMode = None
	if len(message) >= 1:
		gm = {
			"standard": 0,
			"std": 0,
			"taiko": 1,
			"ctb": 2,
			"mania": 3
		}
		if message[0].lower() not in gm:
			return "What's that game mode? I've never heard of it :/"
		else:
			gameMode = gm[message[0].lower()]

	token = glob.tokens.getTokenFromUsername(fro)
	if token is None:
		return False
	if gameMode is None:
		gameMode = token.gameMode
	if gameMode == gameModes.TAIKO or gameMode == gameModes.CTB:
		return "PP for your current game mode is not supported yet."
	pp = userUtils.getPP(token.userID, gameMode)
	return "You have {:,} pp".format(pp)

def updateBeatmap(fro, chan, message):
	try:
		# Run the command in PM only
		if chan.startswith("#"):
			return False

		# Get token and user ID
		token = glob.tokens.getTokenFromUsername(fro)
		if token is None:
			return False

		# Make sure the user has triggered the bot with /np command
		if token.tillerino[0] == 0:
			return "Please give me a beatmap first with /np command."

		# Send the request to cheesegull
		ok, message = cheesegull.updateBeatmap(token.tillerino[0])
		if ok:
			return "An update request for that beatmap has been queued. Check back in a few minutes and the beatmap should be updated!"
		else:
			return "Error in beatmap mirror API request: {}".format(message)
	except:
		return False


	# cmyui section that cmyui coded and cmyui did it no matter what any other retard says >:((((((((((

def report(fro, chan, message):
	msg = ""
	try:
		for i in message:
			i = i.lower()
		target = message[0]
		reason = ' '.join(message[1:])
		# TODO: Rate limit
		# Regex on message

		# Make sure the message matches the regex
		if reason is None:
			raise exceptions.invalidArgumentsException()

		# Get username, report reason and report info
		target = chat.fixUsernameForBancho(target)
		name = chat.fixUsernameForBancho(fro)

		# Make sure the target is not foka
		if target.lower() == glob.BOT_NAME.lower():
			raise exceptions.invalidUserException()

		# Make sure the user exists
		targetID = userUtils.getID(target)
		if targetID == 0:
			raise exceptions.userNotFoundException()

		# Get the token if possible
		chatlog = ""
		token = glob.tokens.getTokenFromUsername(userUtils.safeUsername(target), safe=True)
		if token is not None:
			chatlog = token.getMessagesBufferString()

		# Everything is fine, submit report
		glob.db.execute("INSERT INTO reports (id, from_username, name, from_uid, to_uid, content, chatlog, open_time) VALUES (NULL, %s, %s, %s, %s, %s, %s, %s)", [target, name, userUtils.getID(fro), targetID, reason, chatlog, int(time.time())])
		msg = "You've reported {target} for {reason}. Thank you for reporting! Your report will be checked by the admins of Akatsuki soon!".format(target=target, reason=reason)
		adminMsg = "{user} has reported {target} for {reason}".format(user=fro, target=target, reason=reason)

		# Log report in #admin and on discord
		chat.sendMessage(glob.BOT_NAME, "#admin", adminMsg)
		log.warning(adminMsg, discord="cm")
	except exceptions.invalidUserException:
		msg = "Hello, {} here! You can't report me. I won't forget what you've tried to do. Watch out.".format(glob.BOT_NAME)
	except exceptions.invalidArgumentsException:
		msg = "Please specify a reason for the report."
	except exceptions.userNotFoundException:
		msg = "The user you've tried to report doesn't exist. If their username contains a space, use an underscore instead."
	except:
		raise
	finally:
		if msg != "":
			token = glob.tokens.getTokenFromUsername(fro)
			if token is not None:
				if token.irc:
					chat.sendMessage(glob.BOT_NAME, fro, msg)
				else:
					token.enqueue(serverPackets.notification(msg))
	return False

def changeUsername(fro, chan, message): # Change a users username, ingame.
	messages = [m.lower() for m in message]
	target = message[0]
	newUsername = message[1]

	if target == glob.BOT_NAME.lower():
		return "Nope."

	# Grab userID & Token
	userID = userUtils.getIDSafe(target)
	tokens = glob.tokens.getTokenFromUsername(userUtils.safeUsername(target), safe=True, _all=True)
	idkWhyICantUseThePreviousOne = glob.tokens.getTokenFromUsername(userUtils.safeUsername(target), safe=True)

	# Change their username
	userUtils.changeUsername(userID, target, newUsername)

	# Ensure they are online (since it's only nescessary to kick/alert them if they're online), then do so if they are.
	if len(tokens) == 0:
		return "{} is not online".format(target)
	idkWhyICantUseThePreviousOne.enqueue(serverPackets.notification("Your name has been changed to {}. Please relogin using that name.".format(newUsername)))

	# Kick users
	for i in tokens:
		i.kick()

	log.rap(userID, "has changed {}'s username to {}.".format(target, newUsername))
	return "Name successfully changed. It might take a while to change the username if the user is online on Bancho."

def editMap(fro, chan, message): # Edit maps ranking status ingame.
	messages = [m.lower() for m in message]
	rankType = message[0]
	mapType = message[1]
	mapID = message[2]

	# Get persons username & ID
	name = chat.fixUsernameForBancho(fro)
	userID = userUtils.getID(fro)

	# Figure out what to do
	if rankType == 'rank':
		rankTypeID = 2
		freezeStatus = 1
	elif rankType == 'love':
		rankTypeID = 5
		freezeStatus = 1
	elif rankType == 'unrank':
		rankTypeID = 0
		freezeStatus = 0

	# Grab beatmapData from db
	beatmapData = glob.db.fetch("SELECT * FROM beatmaps WHERE beatmap_id = {} LIMIT 1".format(mapID))

	if mapType == 'set':
		glob.db.execute("UPDATE beatmaps SET ranked = {}, ranked_status_freezed = {} WHERE beatmapset_id = {} LIMIT 100".format(rankTypeID, freezeStatus, beatmapData["beatmapset_id"]))
		if freezeStatus == 1:
				glob.db.execute("""UPDATE scores s JOIN (SELECT userid, MAX(score) maxscore FROM scores JOIN beatmaps ON scores.beatmap_md5 = beatmaps.beatmap_md5 WHERE beatmaps.beatmap_md5 = (SELECT beatmap_md5 FROM beatmaps
					WHERE beatmapset_id = {} LIMIT 1) GROUP BY userid) s2 ON s.score = s2.maxscore AND s.userid = s2.userid SET completed = 3""".format(beatmapData["beatmapset_id"]))
	elif mapType == 'map':
		glob.db.execute("UPDATE beatmaps SET ranked = {}, ranked_status_freezed = {} WHERE beatmap_id = {} LIMIT 1".format(rankTypeID, freezeStatus, mapID))
		if freezeStatus == 1:
				glob.db.execute("""UPDATE scores s JOIN (SELECT userid, MAX(score) maxscore FROM scores JOIN beatmaps ON scores.beatmap_md5 = beatmaps.beatmap_md5 WHERE beatmaps.beatmap_md5 = (SELECT beatmap_md5 FROM beatmaps
					WHERE beatmap_id = {} LIMIT 1) GROUP BY userid) s2 ON s.score = s2.maxscore AND s.userid = s2.userid SET completed = 3""".format(beatmapData["beatmap_id"]))
	else:
		return "Please specify whether it is a set/map. eg: '!map unrank/rank/love set/map 123456'"

	# Announce / Log to AP logs when ranked status is changed
	if rankType == "love":
		log.rap(userID, "has {}d beatmap ({}): {} ({}).".format(rankType, mapType, beatmapData["song_name"], mapID), True)
		if mapType == 'set':
			msg = "{} has loved beatmap set: [https://osu.ppy.sh/s/{} {}]".format(name, beatmapData["beatmapset_id"], beatmapData["song_name"])
		else:
			msg = "{} has loved beatmap: [https://osu.akatsuki.pw/b/{} {}]".format(name, mapID, beatmapData["song_name"])
	else:
		log.rap(userID, "has {}ed beatmap ({}): {} ({}).".format(rankType, mapType, beatmapData["song_name"], mapID), True)
		if mapType == 'set':
			msg = "{} has {}ed beatmap set: [https://osu.ppy.sh/s/{} {}]".format(name, rankType, beatmapData["beatmapset_id"], beatmapData["song_name"])
		else:
			msg = "{} has {}ed beatmap: [https://osu.akatsuki.pw/b/{} {}]".format(name, rankType, mapID, beatmapData["song_name"])
	chat.sendMessage(glob.BOT_NAME, "#nowranked", msg)
	return msg

def runSQL(fro, chan, message): # Obviously not the safest command.. Run SQL queries ingame!
	messages = [m.lower() for m in message]
	command = ' '.join(message[0:])

	userID = userUtils.getID(fro)

	if userID == 1001: # Just cmyui owo
		if len(command) < 10: # Catch this so it doesnt say it failed when it kinda didnt even though it did what the fuck am i typing anymore
			return "Query length too short.. You're probably doing something wrong."
		try:
			glob.db.execute(command)
		except:
			return "Could not successfully execute query"
	else:
		return "You lack sufficient permissions to execute this query"
	return "Query executed successfully"

def postAnnouncement(fro, chan, message): # Post to #announce ingame
	messgaes = [m.lower() for m in message]
	announcement = ' '.join(message[0:])
	chat.sendMessage(glob.BOT_NAME, "#announce", announcement)
	return "Announcement successfully sent."

def promoteUser(fro, chan, message): # Set a users privileges ingame
	messages = [m.lower() for m in message]
	target = message[0]
	privilege = message[1]

	targetUserID = userUtils.getIDSafe(target)
	userID = userUtils.getID(fro)

	if not targetUserID:
		return "{}: user not found".format(target)

	if privilege == 'user':
		priv = 3
	elif privilege == 'bat':
		priv = 267
	elif privilege == 'mod':
		priv = 786763
	elif privilege == 'tournamentstaff':
		priv = 2097159
	elif privilege == 'admin':
		priv = 3047935
	elif privilege == 'developer':
		priv = 3145727
	elif privilege == 'owner':
		priv = 7340031
	else:
		return "Invalid rankname (bat/mod/tournamentstaff/admin/developer/owner)"

	try:
		glob.db.execute("UPDATE users SET privileges = %s WHERE id = %s LIMIT 1", [priv, targetUserID])
	except:
		return "An unknown error has occured while trying to set role."

	# Log message
	log.rap(userID, "set {} to {}.".format(target, privilege), True)
	msg = "{}'s rank has been set to: {}".format(target, privilege)
	chat.sendMessage(glob.BOT_NAME, "#announce", msg)
	return msg

def rtxMurder(fro, chan, message):
	target = message[0]
	number = message[1]
	message = " ".join(message[2:])

	userID = userUtils.getID(fro)

	if userID != 1001: # Just cmyui owo
		return "Sorry but only cmyui himself may use this command.."

	if not number.isdigit():
		return "Please specify a count, I.E !imsosorry 100 cmyui xd"

	targetUserID = userUtils.getIDSafe(target)
	if not targetUserID:
		return "{}: user not found".format(target)
	userToken = glob.tokens.getTokenFromUserID(targetUserID, ignoreIRC=True, _all=False)
	base = 1
	while base < number:
		base = base + 1
		userToken.enqueue(serverPackets.rtx(message))
	return "their poor souls will remember this for eternity.."

def recommendMap(fro, chan, message):
	messages = [m.lower() for m in message]
	try:
		diffmode = message[0]
		if chan.startswith("#"):
			return False
		# Probably the hardest thing I've ever attempted to code (made by cmyui winky face emoji :cowboy:)
		# Currently only works on nomod because idk how to code
		userID = userUtils.getIDSafe(fro)

		# Specify gamemode. recommend PP to the User
		if not diffmode.isdigit():
			if diffmode == "std":
				modeName = "std"
				modeID = 0
			elif diffmode == "taiko":
				modeName = "taiko"
				modeID = 1
			elif diffmode == "ctb":
				modeName = "ctb"
				modeID = 2
			elif diffmode == "mania":
				modeName = "mania"
				modeID = 3
			else:
				return "Please enter a valid gamemode."

			# Calculate what sort of PP amounts we should be recommending based on the average of their top 10 plays
			userPPData = glob.db.fetch("SELECT AVG(pp) FROM (SELECT pp FROM scores WHERE userid = {} AND play_mode = {} ORDER BY pp DESC LIMIT 10) AS topplays".format(userID, modeID))

			"""
			if not pp in userPPData:
				return "You do not have enough scores in this gamemode to have any recommendations."
			"""

			#Determine what amount of PP we should recommend them
			rawrecommendedPP = userPPData.values()
			recommendedPP = 0
			for val in rawrecommendedPP:
				recommendedPP += val

			# Determine the amount of variance
			ppVariance = recommendedPP / 15
			ppBelow = recommendedPP - ppVariance
			ppAbove = recommendedPP + ppVariance

			recommendedMaps = glob.db.fetch("SELECT beatmap_id, song_name, ar, od, bpm, difficulty_{}, max_combo, pp_100, pp_99, pp_98, pp_95 FROM beatmaps WHERE ranked = 2 AND ((pp_95 > {} AND pp_95 < {}) OR (pp_98 > {} AND pp_98 < {}) OR (pp_99 > {} AND pp_99 < {}) OR (pp_100 > {} AND pp_100 < {})) AND mode = {} ORDER BY RAND() LIMIT 1".format(modeName, ppBelow, ppAbove, ppBelow, ppAbove, ppBelow, ppAbove, ppBelow, ppAbove, modeID))
			return "{} | [https://osu.ppy.sh/b/{} {}]: OD{} | AR{} | {}BPM | {}* | Max Combo: {} | Current recommendations: {}pp | 95%: {}pp | 98%: {}pp | 99%: {}pp | 100%: {}pp. Good luck owo!".format(modeName, recommendedMaps["beatmap_id"], recommendedMaps["song_name"], recommendedMaps["od"], recommendedMaps["ar"], recommendedMaps["bpm"], recommendedMaps["difficulty_{}".format(modeName)], recommendedMaps["max_combo"], recommendedPP, recommendedMaps["pp_95"], recommendedMaps["pp_98"], recommendedMaps["pp_99"], recommendedMaps["pp_100"])


		else: # Do not specify gamemode. Do not recommend PP as they are picking a star rating
			"""
			if int(diffmode) > 10:
				return "Maps over 10* will not be calculated."
			"""
			findMode = glob.db.fetch("SELECT favourite_mode FROM users_stats where id = {}".format(userID))
			if findMode["favourite_mode"] == 0:
				modeName = "std"
				modeID = 0
			elif findMode["favourite_mode"] == 1:
				modeName = "taiko"
				modeID = 1
			elif findMode["favourite_mode"] == 2:
				modeName = "ctb"
				modeID = 2
			elif findMode["favourite_mode"] == 3:
				modeName = "mania"
				modeID = 3

			diffmodeplus = int(diffmode) + 1
			recommendedMaps = glob.db.fetch("SELECT beatmap_id, song_name, ar, od, bpm, difficulty_{}, max_combo, pp_100, pp_99, pp_98, pp_95 FROM beatmaps WHERE ranked = 2 AND difficulty_{} > {} AND difficulty_{} < {} AND mode = {} ORDER BY RAND() LIMIT 1".format(modeName, modeName, diffmode, modeName, diffmodeplus, modeID))
			return "{} | [https://osu.ppy.sh/b/{} {}]: OD{} | AR{} | {}BPM | {}* | Max Combo: {} | 95%: {}pp | 98%: {}pp | 99%: {}pp | 100%: {}pp. Good luck owo!".format(modeName, recommendedMaps["beatmap_id"], recommendedMaps["song_name"], recommendedMaps["od"], recommendedMaps["ar"], recommendedMaps["bpm"], recommendedMaps["difficulty_{}".format(modeName)], recommendedMaps["max_combo"], recommendedMaps["pp_95"], recommendedMaps["pp_98"], recommendedMaps["pp_99"], recommendedMaps["pp_100"])		
	except:
		return "Please use the correct syntax: !r <mode or * rating (will predict your main mode)>"

def multiplayer(fro, chan, message):
	def getMatchIDFromChannel(chan):
		if not chan.lower().startswith("#multi_"):
			raise exceptions.wrongChannelException()
		parts = chan.lower().split("_")
		if len(parts) < 2 or not parts[1].isdigit():
			raise exceptions.wrongChannelException()
		matchID = int(parts[1])
		if matchID not in glob.matches.matches:
			raise exceptions.matchNotFoundException()
		return matchID

	def mpMake():
		if len(message) < 2:
			raise exceptions.invalidArgumentsException("Wrong syntax: !mp make <name>")
		matchID = glob.matches.createMatch(" ".join(message[1:]), generalUtils.stringMd5(generalUtils.randomString(32)), 0, "Tournament", "", 0, -1, isTourney=True)
		glob.matches.matches[matchID].sendUpdates()
		return "Tourney match #{} created!".format(matchID)

	def mpJoin():
		if len(message) < 2 or not message[1].isdigit():
			raise exceptions.invalidArgumentsException("Wrong syntax: !mp join <id>")
		matchID = int(message[1])
		userToken = glob.tokens.getTokenFromUsername(fro, ignoreIRC=True)
		userToken.joinMatch(matchID)
		return "Attempting to join match #{}!".format(matchID)

	def mpForce():
		username = message[1]
		matchID = int(message[2])

		userToken = glob.tokens.getTokenFromUsername(username, ignoreIRC=True)
		if userToken is None:
			return "No such user"

		try:
			userToken.joinMatch(matchID)
		except:
			return "Could not find multiplayer match {}".format(matchID)

		return "Attempting to force user {} into match #{}!".format(username, matchID)

	def mpClose():
		matchID = getMatchIDFromChannel(chan)
		glob.matches.disposeMatch(matchID)
		return "Multiplayer match #{} disposed successfully".format(matchID)

	def mpLock():
		matchID = getMatchIDFromChannel(chan)
		glob.matches.matches[matchID].isLocked = True
		return "This match has been locked"

	def mpUnlock():
		matchID = getMatchIDFromChannel(chan)
		glob.matches.matches[matchID].isLocked = False
		return "This match has been unlocked"

	def mpSize():
		if len(message) < 2 or not message[1].isdigit() or int(message[1]) < 2 or int(message[1]) > 16:
			raise exceptions.invalidArgumentsException("Wrong syntax: !mp size <slots(2-16)>")
		matchSize = int(message[1])
		_match = glob.matches.matches[getMatchIDFromChannel(chan)]
		_match.forceSize(matchSize)
		return "Match size changed to {}".format(matchSize)

	def mpMove():
		if len(message) < 3 or not message[2].isdigit() or int(message[2]) < 0 or int(message[2]) > 16:
			raise exceptions.invalidArgumentsException("Wrong syntax: !mp move <username> <slot>")
		username = message[1]
		newSlotID = int(message[2])
		userID = userUtils.getIDSafe(username)
		if userID is None:
			raise exceptions.userNotFoundException("No such user")
		_match = glob.matches.matches[getMatchIDFromChannel(chan)]
		success = _match.userChangeSlot(userID, newSlotID)
		if success:
			result = "Player {} moved to slot {}".format(username, newSlotID)
		else:
			result = "You can't use that slot: it's either already occupied by someone else or locked"
		return result

	def mpHost():
		if len(message) < 2:
			raise exceptions.invalidArgumentsException("Wrong syntax: !mp host <username>")
		username = message[1]
		userID = userUtils.getIDSafe(username)
		if userID is None:
			raise exceptions.userNotFoundException("No such user")
		_match = glob.matches.matches[getMatchIDFromChannel(chan)]
		success = _match.setHost(userID)
		return "{} is now the host".format(username) if success else "Couldn't give host to {}".format(username)

	def mpClearHost():
		matchID = getMatchIDFromChannel(chan)
		glob.matches.matches[matchID].removeHost()
		return "Host has been removed from this match"

	def mpStart():
		def _start():
			matchID = getMatchIDFromChannel(chan)
			success = glob.matches.matches[matchID].start()
			if not success:
				chat.sendMessage(glob.BOT_NAME, chan, "Couldn't start match. Make sure there are enough players and "
												  "teams are valid. The match has been unlocked.")
			else:
				chat.sendMessage(glob.BOT_NAME, chan, "Have fun!")


		def _decreaseTimer(t):
			if t <= 0:
				_start()
			else:
				if t % 10 == 0 or t <= 5:
					chat.sendMessage(glob.BOT_NAME, chan, "Match starts in {} seconds.".format(t))
				threading.Timer(1.00, _decreaseTimer, [t - 1]).start()

		if len(message) < 2 or not message[1].isdigit():
			startTime = 0
		else:
			startTime = int(message[1])

		force = False if len(message) < 3 else message[2].lower() == "force"
		_match = glob.matches.matches[getMatchIDFromChannel(chan)]

		# Force everyone to ready
		someoneNotReady = False
		for i, slot in enumerate(_match.slots):
			if slot.status != slotStatuses.READY and slot.user is not None:
				someoneNotReady = True
				if force:
					_match.toggleSlotReady(i)

		if someoneNotReady and not force:
			return "Some users aren't ready yet. Use '!mp start force' if you want to start the match, " \
				   "even with non-ready players."

		if startTime == 0:
			_start()
			return "Starting match"
		else:
			_match.isStarting = True
			threading.Timer(1.00, _decreaseTimer, [startTime - 1]).start()
			return "Match starts in {} seconds. The match has been locked. " \
				   "Please don't leave the match during the countdown " \
				   "or you might receive a penalty.".format(startTime)

	def mpInvite():
		if len(message) < 2:
			raise exceptions.invalidArgumentsException("Wrong syntax: !mp invite <username>")
		username = message[1]
		userID = userUtils.getIDSafe(username)
		if userID is None:
			raise exceptions.userNotFoundException("No such user")
		token = glob.tokens.getTokenFromUserID(userID, ignoreIRC=True)
		if token is None:
			raise exceptions.invalidUserException("That user is not connected to bancho right now.")
		_match = glob.matches.matches[getMatchIDFromChannel(chan)]
		_match.invite(999, userID)
		token.enqueue(serverPackets.notification("Please accept the invite you've just received from {} to "
												 "enter your tourney match.".format(glob.BOT_NAME)))
		return "An invite to this match has been sent to {}".format(username)

	def mpMap():
		if len(message) < 2 or not message[1].isdigit() or (len(message) == 3 and not message[2].isdigit()):
			raise exceptions.invalidArgumentsException("Wrong syntax: !mp map <beatmapid> [<gamemode>]")
		beatmapID = int(message[1])
		gameMode = int(message[2]) if len(message) == 3 else 0
		if gameMode < 0 or gameMode > 3:
			raise exceptions.invalidArgumentsException("Gamemode must be 0, 1, 2 or 3")
		beatmapData = glob.db.fetch("SELECT * FROM beatmaps WHERE beatmap_id = %s LIMIT 1", [beatmapID])
		if beatmapData is None:
			raise exceptions.invalidArgumentsException("The beatmap you've selected couldn't be found in the database."
													   "If the beatmap id is valid, please load the scoreboard first in "
													   "order to cache it, then try again.")
		_match = glob.matches.matches[getMatchIDFromChannel(chan)]
		_match.beatmapID = beatmapID
		_match.beatmapName = beatmapData["song_name"]
		_match.beatmapMD5 = beatmapData["beatmap_md5"]
		_match.gameMode = gameMode
		_match.resetReady()
		_match.sendUpdates()
		return "Match map has been updated"

	def mpSet():
		if len(message) < 2 or not message[1].isdigit() or \
				(len(message) >= 3 and not message[2].isdigit()) or \
				(len(message) >= 4 and not message[3].isdigit()):
			raise exceptions.invalidArgumentsException("Wrong syntax: !mp set <teammode> [<scoremode>] [<size>]")
		_match = glob.matches.matches[getMatchIDFromChannel(chan)]
		matchTeamType = int(message[1])
		matchScoringType = int(message[2]) if len(message) >= 3 else _match.matchScoringType
		if not 0 <= matchTeamType <= 3:
			raise exceptions.invalidArgumentsException("Match team type must be between 0 and 3")
		if not 0 <= matchScoringType <= 3:
			raise exceptions.invalidArgumentsException("Match scoring type must be between 0 and 3")
		oldMatchTeamType = _match.matchTeamType
		_match.matchTeamType = matchTeamType
		_match.matchScoringType = matchScoringType
		if len(message) >= 4:
			_match.forceSize(int(message[3]))
		if _match.matchTeamType != oldMatchTeamType:
			_match.initializeTeams()
		if _match.matchTeamType == matchTeamTypes.TAG_COOP or _match.matchTeamType == matchTeamTypes.TAG_TEAM_VS:
			_match.matchModMode = matchModModes.NORMAL

		_match.sendUpdates()
		return "Match settings have been updated!"

	def mpAbort():
		_match = glob.matches.matches[getMatchIDFromChannel(chan)]
		_match.abort()
		return "Match aborted!"

	def mpKick():
		if len(message) < 2:
			raise exceptions.invalidArgumentsException("Wrong syntax: !mp kick <username>")
		username = message[1]
		userID = userUtils.getIDSafe(username)
		if userID is None:
			raise exceptions.userNotFoundException("No such user")
		_match = glob.matches.matches[getMatchIDFromChannel(chan)]
		slotID = _match.getUserSlotID(userID)
		if slotID is None:
			raise exceptions.userNotFoundException("The specified user is not in this match")
		for i in range(0, 2):
			_match.toggleSlotLocked(slotID)
		return "{} has been kicked from the match.".format(username)

	def mpPassword():
		password = "" if len(message) < 2 else message[1]
		_match = glob.matches.matches[getMatchIDFromChannel(chan)]
		_match.changePassword(password)
		return "Match password has been changed!"

	def mpRandomPassword():
		password = generalUtils.stringMd5(generalUtils.randomString(32))
		_match = glob.matches.matches[getMatchIDFromChannel(chan)]
		_match.changePassword(password)
		return "Match password has been changed to a random one"

	def mpMods():
		if len(message) < 2:
			raise exceptions.invalidArgumentsException("Wrong syntax: !mp <mod1> [<mod2>] ...")
		_match = glob.matches.matches[getMatchIDFromChannel(chan)]
		newMods = 0
		freeMod = False
		for _mod in message[1:]:
			if _mod.lower().strip() == "hd":
				newMods |= mods.HIDDEN
			elif _mod.lower().strip() == "hr":
				newMods |= mods.HARDROCK
			elif _mod.lower().strip() == "dt":
				newMods |= mods.DOUBLETIME
			elif _mod.lower().strip() == "fl":
				newMods |= mods.FLASHLIGHT
			elif _mod.lower().strip() == "fi":
				newMods |= mods.FADEIN
			if _mod.lower().strip() == "none":
				newMods = 0

			if _mod.lower().strip() == "freemod":
				freeMod = True

		_match.matchModMode = matchModModes.FREE_MOD if freeMod else matchModModes.NORMAL
		_match.resetReady()
		if _match.matchModMode == matchModModes.FREE_MOD:
			_match.resetMods()
		_match.changeMods(newMods)
		return "Match mods have been updated!"

	def mpTeam():
		if len(message) < 3:
			raise exceptions.invalidArgumentsException("Wrong syntax: !mp team <username> <colour>")
		username = message[1]
		colour = message[2].lower().strip()
		if colour not in ["red", "blue"]:
			raise exceptions.invalidArgumentsException("Team colour must be red or blue")
		userID = userUtils.getIDSafe(username)
		if userID is None:
			raise exceptions.userNotFoundException("No such user")
		_match = glob.matches.matches[getMatchIDFromChannel(chan)]
		_match.changeTeam(userID, matchTeams.BLUE if colour == "blue" else matchTeams.RED)
		return "{} is now in {} team".format(username, colour)

	def mpSettings():
		_match = glob.matches.matches[getMatchIDFromChannel(chan)]
		msg = "PLAYERS IN THIS MATCH:\n"
		empty = True
		for slot in _match.slots:
			if slot.user is None:
				continue
			readableStatuses = {
				slotStatuses.READY: "ready",
				slotStatuses.NOT_READY: "not ready",
				slotStatuses.NO_MAP: "no map",
				slotStatuses.PLAYING: "playing",
			}
			if slot.status not in readableStatuses:
				readableStatus = "???"
			else:
				readableStatus = readableStatuses[slot.status]
			empty = False
			msg += "* [{team}] <{status}> ~ {username}{mods}\n".format(
				team="red" if slot.team == matchTeams.RED else "blue" if slot.team == matchTeams.BLUE else "!! no team !!",
				status=readableStatus,
				username=glob.tokens.tokens[slot.user].username,
				mods=" (+ {})".format(generalUtils.readableMods(slot.mods)) if slot.mods > 0 else ""
			)
		if empty:
			msg += "Nobody.\n"
		return msg


	try:
		subcommands = {
			"make": mpMake,
			"close": mpClose,
			"join": mpJoin,
			"force": mpForce,
			"lock": mpLock,
			"unlock": mpUnlock,
			"size": mpSize,
			"move": mpMove,
			"host": mpHost,
			"clearhost": mpClearHost,
			"start": mpStart,
			"invite": mpInvite,
			"map": mpMap,
			"set": mpSet,
			"abort": mpAbort,
			"kick": mpKick,
			"password": mpPassword,
			"randompassword": mpRandomPassword,
			"mods": mpMods,
			"team": mpTeam,
			"settings": mpSettings,
		}
		requestedSubcommand = message[0].lower().strip()
		if requestedSubcommand not in subcommands:
			raise exceptions.invalidArgumentsException("Invalid subcommand")
		return subcommands[requestedSubcommand]()
	except (exceptions.invalidArgumentsException, exceptions.userNotFoundException) as e:
		return str(e)
	except exceptions.wrongChannelException:
		return "This command only works in multiplayer chat channels"
	except exceptions.matchNotFoundException:
		return "Match not found"
	except:
		raise

def switchServer(fro, chan, message):
	# Get target user ID
	target = message[0]
	newServer = message[1]
	targetUserID = userUtils.getIDSafe(target)
	userID = userUtils.getID(fro)

	# Make sure the user exists
	if not targetUserID:
		return "{}: user not found".format(target)

	# Connect the user to the end server
	userToken = glob.tokens.getTokenFromUserID(userID, ignoreIRC=True, _all=False)
	userToken.enqueue(serverPackets.switchServer(newServer))

	# Disconnect the user from the origin server
	# userToken.kick()
	return "{} has been connected to {}".format(target, newServer)

def rtx(fro, chan, message):
	target = message[0]
	message = " ".join(message[1:])
	targetUserID = userUtils.getIDSafe(target)
	if not targetUserID:
		return "{}: user not found".format(target)
	userToken = glob.tokens.getTokenFromUserID(targetUserID, ignoreIRC=True, _all=False)
	userToken.enqueue(serverPackets.rtx(message))
	return ":ok_hand:"

"""
Commands list

trigger: message that triggers the command
callback: function to call when the command is triggered. Optional.
response: text to return when the command is triggered. Optional.
syntax: command syntax. Arguments must be separated by spaces (eg: <arg1> <arg2>)
privileges: privileges needed to execute the command. Optional.
"""
commands = [
	{
		"trigger": "!roll",
		"callback": roll
	}, {
		"trigger": "!faq",
		"syntax": "<name>",
		"callback": faq
	}, {
		"trigger": "!report",
		"callback": report
	}, {
		"trigger": "!help",
		"response": "Click (here)[https://osu.akatsuki.pw/doc/3] for the full command list"
	}, {
		"trigger": "!r",
		"callback": recommendMap
	},
	{
		"trigger": "!map",
		"syntax": "<rank/unrank/love> <set/map> <ID>",
		"privileges": privileges.ADMIN_MANAGE_BEATMAPS,
		"callback": editMap
	},
	{
		"trigger": "!priv",
		"syntax": "<userID> <rank>",
		"privileges": privileges.ADMIN_MANAGE_USERS,
		"callback": promoteUser
	}, {
		"trigger": "!announce",
		"syntax": "<announcement>",
		"privileges": privileges.ADMIN_SEND_ALERTS,
		"callback": postAnnouncement
	}, {
		"trigger": "!alert",
		"syntax": "<message>",
		"privileges": privileges.ADMIN_SEND_ALERTS,
		"callback": alert
	}, {
		"trigger": "!alertuser",
		"syntax": "<username> <message>",
		"privileges": privileges.ADMIN_SEND_ALERTS,
		"callback": alertUser,
	}, {
		"trigger": "!moderated",
		"privileges": privileges.ADMIN_CHAT_MOD,
		"callback": moderated
	}, {
		"trigger": "!kickall",
		"privileges": privileges.ADMIN_MANAGE_SERVERS,
		"callback": kickAll
	}, {
		"trigger": "!query",
		"privileges": privileges.ADMIN_MANAGE_SERVERS,
		"callback": runSQL
	}, {
		"trigger": "!kick",
		"syntax": "<target>",
		"privileges": privileges.ADMIN_KICK_USERS,
		"callback": kick
	}, {
		"trigger": "!bot reconnect",
		"privileges": privileges.ADMIN_MANAGE_SERVERS,
		"callback": fokabotReconnect
	}, {
		"trigger": "!silence",
		"syntax": "<target> <amount> <unit(s/m/h/d)> <reason>",
		"privileges": privileges.ADMIN_SILENCE_USERS,
		"callback": silence
	}, {
		"trigger": "!unsilence",
		"syntax": "<target>",
		"privileges": privileges.ADMIN_SILENCE_USERS,
		"callback": removeSilence
	}, {
		"trigger": "!system restart",
		"privileges": privileges.ADMIN_MANAGE_SERVERS,
		"callback": systemRestart
	}, {
		"trigger": "!system shutdown",
		"privileges": privileges.ADMIN_MANAGE_SERVERS,
		"callback": systemShutdown
	}, {
		"trigger": "!system reload",
		"privileges": privileges.ADMIN_MANAGE_SETTINGS,
		"callback": systemReload
	}, {
		"trigger": "!system maintenance",
		"privileges": privileges.ADMIN_MANAGE_SERVERS,
		"callback": systemMaintenance
	}, {
		"trigger": "!system status",
		"privileges": privileges.ADMIN_MANAGE_SERVERS,
		"callback": systemStatus
	}, {
		"trigger": "!ban",
		"syntax": "<target>",
		"privileges": privileges.ADMIN_BAN_USERS,
		"callback": ban
	}, {
		"trigger": "!unban",
		"syntax": "<target>",
		"privileges": privileges.ADMIN_BAN_USERS,
		"callback": unban
	}, {
		"trigger": "!restrict",
		"syntax": "<target>",
		"privileges": privileges.ADMIN_BAN_USERS,
		"callback": restrict
	}, {
		"trigger": "!unrestrict",
		"syntax": "<target>",
		"privileges": privileges.ADMIN_BAN_USERS,
		"callback": unrestrict
	}, {
		"trigger": "\x01ACTION is listening to",
		"callback": tillerinoNp
	}, {
		"trigger": "\x01ACTION is playing",
		"callback": tillerinoNp
	}, {
		"trigger": "\x01ACTION is watching",
		"callback": tillerinoNp
	}, {
		"trigger": "!with",
		"callback": tillerinoMods,
		"syntax": "<mods>"
	}, {
		"trigger": "!last",
		"callback": tillerinoLast
	}, {
		"trigger": "!ir",
		"privileges": privileges.ADMIN_MANAGE_SERVERS,
		"callback": instantRestart
	}, {
		"trigger": "!pp",
		"callback": pp
	}, {
		"trigger": "!update",
		"callback": updateBeatmap
	}, {
		"trigger": "!mp",
		"privileges": privileges.USER_TOURNAMENT_STAFF,
		"syntax": "<subcommand>",
		"callback": multiplayer
	}, {
		"trigger": "!switchserver",
		"privileges": privileges.ADMIN_MANAGE_SERVERS,
		"syntax": "<username> <server_address>",
		"callback": switchServer
	}, {
		"trigger": "!rtx",
		"privileges": privileges.ADMIN_MANAGE_USERS,
		"syntax": "<username> <message>",
		"callback": rtx
	}, {
		"trigger": "!imsosorry",
		"privileges": privileges.ADMIN_MANAGE_SERVERS,
		"syntax": "<count> <username> <message>",
		"callback": rtxMurder
	}, {
		"trigger": "!changeusername",
		"privileges": privileges.ADMIN_MANAGE_USERS,
		"syntax": "<username> <newUsername>",
		"callback": changeUsername
	}
	#
	#	"trigger": "!acc",
	#	"callback": tillerinoAcc,
	#	"syntax": "<accuarcy>"
	#}
]

# Commands list default values
for cmd in commands:
	cmd.setdefault("syntax", "")
	cmd.setdefault("privileges", None)
	cmd.setdefault("callback", None)
	cmd.setdefault("response", "u w0t m8?")
