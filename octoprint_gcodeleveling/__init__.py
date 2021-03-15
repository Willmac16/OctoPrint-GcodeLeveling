# coding=utf-8
from __future__ import absolute_import

import re, sys, math, numpy as np, threading

import octoprint.plugin
import octoprint.filemanager
import octoprint.filemanager.util
from octoprint.filemanager import FileDestinations

from octoprint.access.permissions import Permissions

import octoprint_gcodeleveling.twoDimFit
import octoprint_gcodeleveling.maxima

def rotateVector(theta, vec):
	rotArray = np.array(((math.cos(theta),-math.sin(theta)),(math.sin(theta),math.cos(theta))))
	return np.matmul(rotArray, vec)

class GcodeLevelingError(Exception):
	def __init__(self, expression, message):
		self.expression = expression
		self.message = message

class GcodePreProcessor(octoprint.filemanager.util.LineProcessorStream):
	def __init__(self, fileBufferedReader, python_version, logger, coeffs, zMin, zMax, lineBreakDist, arcSegDist, invertPosition):
		super(GcodePreProcessor, self).__init__(fileBufferedReader)
		self.python_version = python_version
		self._logger = logger
		self.coeffs = coeffs
		self.zMin = zMin
		self.zMax = zMax
		self.lineBreakDist = lineBreakDist**2
		self.arcSegDist = arcSegDist
		self.invertPosition = invertPosition

		self.pwm = maxima.SingleGradientAscent()

		self.moveCurr = "G0"

		self.xPrev = 0.0
		self.yPrev = 0.0
		self.zPrev = 0.0
		self.ePrev = 0.0

		self.xCurr = 0.0
		self.yCurr = 0.0
		self.zCurr = 0.0

		self.eCurr = 0.0

		self.eMode = "None"
		self.moveMode = "Absolute"
		self.workspacePlane = 0

		self.workspacePlanes = ["G17", "G18", "G19"]

		self.spareParts = ""


		self.afterStart = False
		self.positionFloating = False

		self.move_pattern = re.compile("^G[0-3]\s")
		self.move_mode_pattern = re.compile("^G9[0-1]")
		self.pos_reset_pattern = re.compile("^G92")
		self.set_workspace_plane = re.compile("^G1[7-9]")
		self.extruder_mode_pattern = re.compile("^M8[2-3]")
		self.comment_pattern = re.compile(";.*$")

	def comment_split(self, line):
		# Logic to seperate comments so they can be reattached after processing
		if line.find(";") != -1:
			comSplit = line.split(";")
			activeCode = comSplit[0]
			if len(comSplit) > 1:
				for part in comSplit[1:]:
						self.spareParts += ";" + part + " "

			return activeCode
		else:
			return line

	def move_dist(self):
		return (self.xCurr-self.xPrev)**2 + (self.yCurr-self.yPrev)**2

	def get_z(self, x, y, zOffset):
		zNew = twoDimFit.twoDpolyEval(self.coeffs, x, y) + (zOffset * (-1 if self.invertPosition else 1))

		if (zNew < self.zMin or zNew > self.zMax):
			self._logger.info("Failed Leveling Point: {}, {}, {}".format(str(x),str(y),str(zNew)))
			raise GcodeLevelingError("Computed Z was outside of bounds", "Gcode Leveling config likely needs to be changed")
		return round(zNew, 3)

	def createLine(self, prev, pos, zVal, eVal):
		outLine = self.moveCurr

		if pos[0] != prev[0]:
				outLine += " X" + str(round(pos[0], 3))
		if pos[1] != prev[1]:
				outLine += " Y" + str(round(pos[1], 3))
		outLine += " Z" + str(self.get_z(pos[0], pos[1], zVal))

		if self.eMode != "None":
				outLine += " E" + str(round(eVal, 5))

		outLine += " " + self.spareParts
		self.spareParts = ""

		outLine += "\n"

		return outLine

	def createArc(self, start, center, angle, eVal, zVal):
		outLine = self.moveCurr

		radius = start - center

		end = center + rotateVector(angle, radius)

		if end[0] != start[0]:
			outLine += " X" + str(round(end[0], 3))
		if end[1] != start[1]:
			outLine += " Y" + str(round(end[1], 3))
		outLine += " Z" + str(self.get_z(end[0], end[1], zVal))

		outLine += " I" + str(round(-radius[0], 3))
		outLine += " J" + str(round(-radius[1], 3))
		if self.eMode != "None":
			outLine += " E" + str(round(eVal, 5))
		outLine += " " + self.spareParts
		self.spareParts = ""

		outLine += "\n"

		return outLine

	def reconstruct_line(self):
		outLine = self.moveCurr

		if self.xCurr != self.xPrev:
			outLine += " X" + str(round(self.xCurr, 3))
		if self.yCurr != self.yPrev:
			outLine += " Y" + str(round(self.yCurr, 3))
		outLine += " Z" + str(self.get_z(self.xCurr, self.yCurr, self.zCurr))

		if self.eMode != "None":
			outLine += " E" + str(round(self.eCurr, 5))

		outLine += " " + self.spareParts
		self.spareParts = ""

		outLine += "\n"

		return outLine

	def reconstruct_arc(self, arcI, arcJ, arcR):
		outLine = self.moveCurr

		outLine += " X" + str(round(self.xCurr, 3))
		outLine += " Y" + str(round(self.yCurr, 3))
		outLine += " Z" + str(self.get_z(self.xCurr, self.yCurr, self.zCurr))

		if arcI != 0.0:
			outLine += " I" + str(round(arcI, 3))
		if arcJ != 0.0:
			outLine += " J" + str(round(arcJ, 3))
		if arcR != 0.0:
			outLine += " R" + str(round(arcR, 3))

		if self.eMode != "None":
			outLine += " E" + str(round(self.eCurr, 5))

		outLine += " " + self.spareParts
		self.spareParts = ""

		outLine += "\n"

		return outLine

	def process_line(self, origLine):
		if not len(origLine):
			return None

		if (self.python_version == 3):
			line = origLine.decode('utf-8').lstrip()
		else:
			line = origLine

		# Check for standard Movement commands
		if self.move_pattern.match(line) is not None and self.moveMode != "Relative" and not self.positionFloating:
			activeCode = self.comment_split(line)
			gcodeParts = re.split("\s", activeCode)

			self.xPrev = self.xCurr
			self.yPrev = self.yCurr
			self.zPrev = self.zCurr

			arcI = 0.0
			arcJ = 0.0
			arcR = 0.0

			self.moveCurr = gcodeParts[0]

			for part in gcodeParts[1:]:
				if len(part) > 1:
					leadChar = part[0]
					if leadChar == "X":
						self.xCurr = float(part[1:])
					elif leadChar == 'Y':
						self.yCurr = float(part[1:])
					elif leadChar == 'Z':
						self.zCurr = float(part[1:])
					elif leadChar == 'E':
						# Extrusion Mode Stuff
						if (self.eMode == "Relative"):
							self.ePrev = 0
						elif (self.eMode == "Absolute"):
							self.ePrev = self.eCurr
						else:
							self.eMode = "Absolute"
							self.ePrev = self.eCurr

						self.eCurr = float(part[1:])
					elif leadChar == 'I':
						arcI = float(part[1:])
					elif leadChar == 'J':
						arcJ = float(part[1:])
					elif leadChar == 'R':
						arcR = float(part[1:])
					else:
						self.spareParts = part + " " + self.spareParts

			if self.moveCurr == "G0" or self.moveCurr == "G1":
				self.moveDist = self.move_dist()

				if (self.moveDist > self.lineBreakDist and self.lineBreakDist != 0.0 and self.afterStart):
					line = ""
					start = np.array([self.xPrev, self.yPrev])
					end = np.array([self.xCurr, self.yCurr])

					for s, e in maxima.lineWiseMaxima(self.coeffs, start, end, self.pwm):
						eVal = 0.0
						if (self.eMode == "Absolute"):
								eVal = self.ePrev + (self.eCurr-self.ePrev) * np.linalg.norm(e - start) / np.linalg.norm(end - start)
						elif (self.eMode == "Relative"):
								eVal = self.eCurr * np.linalg.norm(e - s) / np.linalg.norm(end - start)
						zVal = self.zPrev + (self.zCurr - self.zPrev)*np.linalg.norm(e - start) / np.linalg.norm(end - start)

						line += self.createLine(s, e, zVal, eVal)
				else:
					self.afterStart = True
					line = self.reconstruct_line()
			elif self.workspacePlane == 0:
				# Handling for Gcode files that do not give a pos before the arc
				if not self.afterStart:
					self.zPrev = self.get_z(self.xPrev, self.yPrev, 0.0)*(self.invertPosition*2 - 1)

				if (arcI or arcJ) and arcR:
					raise GcodeLevelingError("Arc format mixing error", "G2/G3 commands cannot use R with I or J")
				elif arcI or arcJ:
					# figure out the center point
					radius = np.array((-arcI, -arcJ))
					prev = np.array((self.xPrev, self.yPrev))
					current = np.array((self.xCurr, self.yCurr))
					center = prev - radius
					endArm = current - center

					r = np.array((radius[0], radius[1], 0.0))
					eA = np.array((endArm[0], endArm[1], 0.0))


					# figure out exit angle
					normalizedCross = np.cross(r, eA)/(np.linalg.norm(radius)*np.linalg.norm(endArm))
					# alpha = math.asin(normalizedCross[2])
					alpha = math.acos(np.dot(radius, endArm)/(np.linalg.norm(radius)*np.linalg.norm(endArm)))


					longPath = (self.moveCurr == "G3") != (normalizedCross[2] > 0)

					arcAngle = 0.0
					if longPath:
						arcAngle = 2*math.pi-alpha
					else:
						arcAngle = alpha

					if self.moveCurr == "G2":
						arcAngle *= -1

					# self._logger.info("Arc Angle {}".format(arcAngle))
					arcLength = np.linalg.norm(radius) * arcAngle

					if (self.arcSegDist != 0.0 and arcLength >= self.arcSegDist):
						line = ""

						for s, c, a, qin, qend in maxima.flatArcWiseMaxima(self.coeffs, center, radius, arcAngle, 0, 1, self.pwm):
							if (self.eMode == "Absolute"):
								eVal = self.ePrev + (self.eCurr-self.ePrev) * qend
							elif (self.eMode == "Relative"):
								eVal = self.eCurr * (qend-qin)
							zVal = qend*(self.zCurr - self.zPrev) + self.zPrev

							line += self.createArc(s, c, a, eVal, zVal)
					else:
						self.reconstruct_arc(arcI, arcJ, arcR)

				elif arcR:
					# figure out the center point
					prev = np.array((self.xPrev, self.yPrev))
					current = np.array((self.xCurr, self.yCurr))

					directConnect = current-prev

					if np.linalg.norm(directConnect) > 2*arcR:
						raise GcodeLevelingError("Invalid Arc Radius", "An arc cannot be formed with too small of a radius")
					elif np.linalg.norm(directConnect) == 0.0:
						raise GcodeLevelingError("Invalid Arc Endpoints", "An radius defined arc cannot be formed with identital endpoints")
					rotModify = -1 if self.moveCurr == "G2" else 1

					q = np.array((directConnect[1]*-1*rotModify, directConnect[0]*rotModify))
					q /= np.linalg.norm(q)
					q *= math.sqrt(arcR**2 - (np.linalg.norm(directConnect)/2)**2)

					center = prev + directConnect/2 + q

					pArm = prev - center
					cArm = current - center

					# figure out exit angle
					arcAngle = math.acos(np.dot(pArm, cArm)/(np.linalg.norm(pArm)*np.linalg.norm(cArm)))

					arcLength = arcR * arcAngle

					if self.moveCurr == "G2":
						arcAngle *= -1

					if (self.arcSegDist != 0.0 and arcLength >= self.arcSegDist):
						line = ""

						for s, c, a, qin, qend in maxima.flatArcWiseMaxima(self.coeffs, center, radius, arcAngle, 0, 1, self.pwm):
							if (self.eMode == "Absolute"):
								eVal = self.ePrev + (self.eCurr-self.ePrev) * qend
							elif (self.eMode == "Relative"):
								eVal = self.eCurr * (qend-qin)
							zVal = qend*(self.zCurr - self.zPrev) + self.zPrev

							line += self.createArc(s, c, a, eVal, zVal)
					else:
						self.reconstruct_arc(arcI, arcJ, arcR)

				else:
						raise GcodeLevelingError("Arc values missing", "G2/G3 commands either need an R or an I or J")

		# # TODO: Add in proper support for relative movements
		elif (self.pos_reset_pattern.match(line) is not None):
			activeCode = self.comment_split(line)
			gcodeParts = re.split("\s", activeCode)

			self.xPrev = self.xCurr
			self.yPrev = self.yCurr
			self.zPrev = self.zCurr

			for part in gcodeParts[1:]:
				if len(part) > 1:
					leadChar = part[0]
					if leadChar == "X" or leadChar == 'Y' or leadChar == 'Z':
						self.posFloating = True
					elif leadChar == 'E':
						self.eCurr = float(part[1:])

			return origLine
		# Check for movement mode
		elif self.move_mode_pattern.match(line) is not None:
			line = re.sub(self.comment_pattern, "", line)
			mode = re.split("\s", line)[0]

			if mode == "G90":
				self.moveMode = "Absolute"
			elif mode == "G91":
				self.moveMode = "Relative"

			# self._logger.info("Line sets move mode " + self.moveMode)
			return origLine

		# Check for extruder movement mode
		elif self.extruder_mode_pattern.match(line) is not None:
			line = re.sub(self.comment_pattern, "", line)
			mode = re.split("\s", line)[0]

			if mode == "M82":
				self.eMode = "Absolute"
			elif mode == "M83":
				self.eMode = "Relative"

			# self._logger.info("Line sets extruder mode " + self.eMode)
			return origLine

		# Check for workspace switches
		elif self.set_workspace_plane.match(line) is not None:
			line = re.sub(self.comment_pattern, "", line)
			mode = re.split("\s", line)[0]

			self.workspacePlane = workspacePlanes.index(mode)
			return origLine

		if (self.python_version == 3):
			line = line.encode('utf-8')

		return line

class GcodeLevelingPlugin(octoprint.plugin.StartupPlugin,
						  octoprint.plugin.SettingsPlugin,
						  octoprint.plugin.AssetPlugin,
						  octoprint.plugin.TemplatePlugin,
						  octoprint.plugin.SimpleApiPlugin):

	checkForProbe = 0

	def createFilePreProcessor(self, path, file_object, blinks=None, printer_profile=None, allow_overwrite=True, *args, **kwargs):
		if self.pointsEntered:
			fileName = file_object.filename
			if not octoprint.filemanager.valid_file_type(fileName, type="gcode"):
				return file_object

			if fileName.endswith("_NO-GCL.gcode"):
				return file_object
			else:
				if self.unmodifiedCopy:
					import os

					gclFileName = re.sub(".gcode", "_NO-GCL.gcode", fileName)
					gclShortPath = re.sub(".gcode", "_NO-GCL.gcode", path)

					gclPath = self._file_manager.path_on_disk(FileDestinations.LOCAL, gclShortPath)

					# Unprocessed file stream is directed to a different file
					unprocessed = octoprint.filemanager.util.StreamWrapper(gclFileName, file_object.stream())
					unprocessed.save(gclPath)

					cleanFO = octoprint.filemanager.util.DiskFileWrapper(gclFileName, gclPath)
					self._file_manager.add_file(FileDestinations.LOCAL, gclPath, cleanFO, allow_overwrite=True, display=gclFileName)

				fileStream = file_object.stream()
				self._logger.info("Gcode PreProcessing started.")
				self.gcode_preprocessor = GcodePreProcessor(fileStream, self.python_version, self._logger, self.coeffs, self.zMin, self.zMax, self.lineBreakDist, self.arcSegDist, self.invertPosition)
			return octoprint.filemanager.util.StreamWrapper(fileName, self.gcode_preprocessor)
		else:
			self._logger.info("Points have not been entered (or they are all zero). Enter points or disable this plugin if you do not need it.")

			return file_object

	# ~~ StartupPlugin mixin

	def on_after_startup(self):
		self._logger.info("Gcode Leveling Plugin started")

		if (sys.version_info > (3, 5)): # Detect and set python version
			self.python_version = 3
		else:
			self.python_version = 2

		self.update_from_settings()

	##~~ SettingsPlugin mixin

	def get_settings_defaults(self):
		return {
			"points": [
				[0,0,0]
			],
			"modelDegree": {"x":2,"y":2},
			"zMin": 0.0,
			"zMax": 100.0,
			"lineBreakDist": 10.0,
			"arcSegDist": 15.0,
			"invertPosition": False,
			"unmodifiedCopy": True,
			'x': 5,
			'y': 5,
			'xMin': 0.0,
			'yMin': 0.0,
			'xMax': 200.0,
			'yMax': 200.0,
			'clearZ': 10.0,
			'probeZ': -2.5,
			"probeRegex": "^ok X:(?P<x>[0-9]+\.[0-9]+) Y:(?P<y>[0-9]+\.[0-9]+) Z:(?P<z>[0-9]+\.[0-9]+)",
			"probePosCmd": "M114",
			"homeCmd": "$H",
			"probeFeedrate": 200.0,
			'xOffset': 0.0,
			'yOffset': 0.0,
			'zOffset': 0.0,
			'finalZ': 100.0,
			'sendBedLevelVisualizer': False
		}

	def on_settings_save(self, data):
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

		self.update_from_settings()

	def update_from_settings(self):
		# auto-probing settings loading
		self.probeRegex = re.compile(self._settings.get(['probeRegex']))
		self.probePosCmd = self._settings.get(['probePosCmd'])
		self.sendBedLevelVisualizer = self._settings.get_boolean(['sendBedLevelVisualizer'])

		self.probeFeedrate = self._settings.get(['probeFeedrate'])
		self.homeCmd = self._settings.get(['homeCmd'])

		self.clearZ = self._settings.get_float(['clearZ'])
		self.probeZ = self._settings.get_float(['probeZ'])
		self.finalZ = self._settings.get_float(['finalZ'])


		self.xMin = self._settings.get_float(['xMin'])
		self.yMin = self._settings.get_float(['yMin'])
		self.xMax = self._settings.get_float(['xMax'])
		self.yMax = self._settings.get_float(['yMax'])

		self.xCount = self._settings.get_int(['x'])
		self.yCount = self._settings.get_int(['y'])

		self.offset = (self._settings.get_float(['xOffset']), self._settings.get_float(['yOffset']), self._settings.get_float(['zOffset']))

		# normal settigns loading
		points = self._settings.get(['points'])
		self._logger.debug(points)

		allZeros = True
		for point in points:
			for coor in point:
				if coor != 0.0:
					allZeros = False

		self.pointsEntered = not allZeros

		if self.pointsEntered:
			self.zMin = self._settings.get_float(['zMin'])
			self.zMax = self._settings.get_float(['zMax'])
			self.lineBreakDist = self._settings.get_float(['lineBreakDist'])
			self.arcSegDist = self._settings.get_float(['arcSegDist'])
			self.modelDegree = self._settings.get(['modelDegree'])
			self.invertPosition = self._settings.get_boolean(['invertPosition'])
			self.unmodifiedCopy = self._settings.get_boolean(['unmodifiedCopy'])

			self.coeffs = twoDimFit.twoDpolyFit(points, int(self.modelDegree['x']), int(self.modelDegree['y']))
			self._logger.info("Leveling Model Computed")
			self._logger.debug(self.coeffs)
		else:
			self._logger.info("Points have not been entered (or they are all zero). Enter points or disable this plugin if you do not need it.")


	def get_settings_version(self):
		return 0

	##~~ AssetPlugin mixin

	def get_assets(self):
		return dict(
			js=["js/GcodeLeveling.js"]
		)

	def get_template_configs(self):
		return [
			{
				"type": "settings",
				"template": "gcodeleveling_settings.jinja2",
				"custom_bindings": True
			}
		]

	##~~ Softwareupdate hook

	def get_update_information(self):
		return dict(
			gcodeleveling=dict(
				displayName="GcodeLeveling Plugin",
				displayVersion=self._plugin_version,

				# version check: github repository
				type="github_release",
				user="willmac16",
				repo="OctoPrint-GcodeLeveling",
				current=self._plugin_version,

				# update method: pip
				pip="https://github.com/willmac16/OctoPrint-GcodeLeveling/archive/{target_version}.zip"
			)
		)

	##~~ SimpleAPIPlugin mixin
	def get_api_commands(self):
		return dict(
			probe=['x', 'y', 'xMin', 'yMin', 'xMax', 'yMax', 'clearZ', 'probeZ', 'probeRegex', 'probePosCmd', 'homeCmd', 'probeFeedrate', 'xOffset', 'yOffset', 'zOffset', 'finalZ', 'sendBedLevelVisualizer'],
			test=[]
		)

	def on_api_command(self, command, data):
		if command == "test":
			self._logger.info("test called")
		elif command == "probe":
			if Permissions.CONTROL.can() and self._printer.is_ready():
				self.probeRegex = re.compile(data['probeRegex'])
				self.probePosCmd = data['probePosCmd']
				self.sendBedLevelVisualizer = bool(data['sendBedLevelVisualizer'])

				self.probeFeedrate = data['probeFeedrate']
				self.homeCmd = data['homeCmd']

				self.clearZ = float(data['clearZ'])
				self.probeZ = float(data['probeZ'])
				self.finalZ = float(data['finalZ'])


				self.xMin = float(data['xMin'])
				self.yMin = float(data['yMin'])
				self.xMax = float(data['xMax'])
				self.yMax = float(data['yMax'])

				self.xCount = int(data['x'])
				self.yCount = int(data['y'])

				self.offset = (float(data['xOffset']), float(data['yOffset']), float(data['zOffset']))

				thread = threading.Thread(target=self.auto_probe)
				thread.daemon = True
				thread.start()
			else:
				self._logger.info("cannot probe since permission is missing or printer is printing")

	def auto_probe(self):
		self._logger.info("Probing Matrix")
		# self._printer.home(("x", "y"))
		self._printer.commands("G0 F{}".format(self.probeFeedrate))
		self._printer.commands(self.homeCmd)


		self.points = []

		self.checkForProbe = 0
		self.probePoints = self.xCount*self.yCount

		self._plugin_manager.send_plugin_message("gcodeleveling", dict(state='startProbing', totalPoints=self.probePoints))

		xDiff = self.xMax-self.xMin
		yDiff = self.yMax-self.yMin

		forward = True
		for xProbe in range(self.xCount):
			x = self.xMin + xProbe * xDiff / (self.xCount-1)

			for yProbe in range(self.yCount):
				if forward:
					y = self.yMin + yProbe * yDiff / (self.yCount-1)
				else:
					y = self.yMax - yProbe * yDiff / (self.yCount-1)
				self._printer.commands("G0 X{} Y{} Z{}".format(round(x, 3), round(y, 3), self.clearZ))
				self._printer.commands("G38.2 Z{}".format(self.probeZ))
				if self.probePosCmd != "":
					self._printer.commands(self.probePosCmd)
				self._printer.commands("G0 X{} Y{} Z{}".format(round(x, 3), round(y, 3), self.clearZ))

				self.checkForProbe += 1

			forward = not forward

		self._printer.commands("G0 X0 Y0 Z{}".format(self.finalZ))

	##~~ Received Gcode Hook
	def parseReceived(self, comm_instance, line):
		if self.checkForProbe > 0:
			mat = self.probeRegex.match(line)
			if mat:
				self.checkForProbe -= 1
				self._logger.debug("{} ({}, {}, {})".format(self.checkForProbe, mat.group('x'), mat.group('y'), mat.group('z')))
				self.points.append((float(mat.group('x'))+self.offset[0], float(mat.group('y'))+self.offset[1], float(mat.group('z'))+self.offset[2]))
				self._plugin_manager.send_plugin_message("gcodeleveling", dict(state='updateProbing', currentPoint=self.probePoints-self.checkForProbe, totalPoints=self.probePoints))
				if self.checkForProbe == 0:
					self._logger.debug(self.points)
					self._logger.info("Saving auto-probed points")
					self._settings.set(['points'], self.points)
					self.update_from_settings()
					self._plugin_manager.send_plugin_message("gcodeleveling", dict(state='finishedProbing'))
					if self.sendBedLevelVisualizer:
						mesh = []

						forward = True
						first = True
						count = 0
						for point in self.points:
							if first:
								if count < self.yCount:
									mesh.append([point[2]])
								else:
									first = False
									forward = False

									mesh[self.yCount-1].append(point[2])
							else:

								if forward:
									index = count % self.yCount
								else:
									index = (self.yCount - 1) - (count % self.yCount)

								mesh[index].append(point[2])
							count += 1

						bed = dict(
							type="rectangular",
			                x_min=self.xMin+self.offset[0],
			                x_max=self.xMax+self.offset[0],
			                y_min=self.yMin+self.offset[1],
			                y_max=self.yMax+self.offset[1],
			                z_min=min(self.clearZ, self.probeZ)+self.offset[2],
			                z_max=max(self.clearZ, self.probeZ)+self.offset[2]
						)
						self._plugin_manager.send_plugin_message("bedlevelvisualizer", dict(mesh=mesh, bed=bed))
		return line


	##~~ @ Command Gcode Hook
	def custom_atcommand_handler(self, comm, phase, command, parameters, tags=None):
		if command != "GCODELEVELING-AUTOPROBE":
		    return
		if Permissions.CONTROL.can() and self._printer.is_ready():
			thread = threading.Thread(target=self.auto_probe)
			thread.daemon = True
			thread.start()
		else:
			self._logger.info("cannot probe since permission is missing or printer is printing")
		return

__plugin_name__ = "Gcode Leveling"

__plugin_pythoncompat__ = ">=2.7,<4" # python 2 and 3

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = GcodeLevelingPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
		"octoprint.filemanager.preprocessor": __plugin_implementation__.createFilePreProcessor,
		"octoprint.comm.protocol.gcode.received": __plugin_implementation__.parseReceived,
		"octoprint.comm.protocol.atcommand.queuing": __plugin_implementation__.custom_atcommand_handler
	}
