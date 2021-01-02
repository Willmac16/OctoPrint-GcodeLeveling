# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import octoprint.filemanager
import octoprint.filemanager.util
import octoprint_gcodeleveling.twoDimFit

from octoprint.filemanager import FileDestinations

import re
import sys
import math
import numpy as np

from octoprint.util.comm import strip_comment

def rotate_vector(theta, vec):
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
		self.lineBreakDist = lineBreakDist
		self.arcSegDist = arcSegDist
		self.invertPosition = invertPosition

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

		self.spareParts = ""


		self.afterStart = False

		self.move_pattern = re.compile("^G[0-3]\s")
		self.feed_pattern = re.compile("^F")
		self.move_mode_pattern = re.compile("^G9[0-1]")
		self.extruder_mode_pattern = re.compile("^M8[2-3]")
		self.comment_pattern = re.compile(";.*$")

	def move_dist(self):
		return ((self.xCurr-self.xPrev)**2 + (self.yCurr-self.yPrev)**2)**0.5

	def get_z(self, x, y, zOffset):
		zNew = twoDimFit.twoDpolyEval(self.coeffs, x, y) + (zOffset * (-1 if self.invertPosition else 1))

		if (zNew < self.zMin or zNew > self.zMax):
			self._logger.info("Failed Leveling Point: {}, {}, {}".format(str(x),str(y),str(zNew)))
			raise GcodeLevelingError("Computed Z was outside of bounds", "Gcode Leveling config likely needs to be changed")
		return round(zNew, 3)

	def construct_line(self, basePos, dirVector, seg):
		outLine = self.moveCurr

		xNew = basePos[0] + dirVector[0]*seg
		yNew = basePos[1] + dirVector[1]*seg
		zOffset = basePos[2] + dirVector[2]*seg


		if xNew != self.xPrev:
			outLine += " X" + str(round(xNew, 3))
		if yNew != self.yPrev:
			outLine += " Y" + str(round(yNew, 3))
		outLine += " Z" + str(self.get_z(xNew, yNew, zOffset))

		if (self.eMode == "Absolute"):
			eNew = basePos[3] + dirVector[3]*seg
			outLine += " E" + str(round(eNew, 5))
		elif (self.eMode == "Relative"):
			eNew = dirVector[3]
			outLine += " E" + str(round(eNew, 5))



		outLine += " " + self.spareParts
		self.spareParts = ""

		outLine += "\n"

		return outLine

	def construct_arc(self, center, baseRadius, arcSegAngle, arcNum, eSeg, zSeg):
		outLine = self.moveCurr

		offsetNew = rotate_vector(arcSegAngle*arcNum, baseRadius)

		posNew = center + rotate_vector(arcSegAngle*(arcNum+1), baseRadius)

		zOffset = self.zPrev + zSeg*(arcNum+1)

		outLine += " X" + str(round(posNew[0], 3))
		outLine += " Y" + str(round(posNew[1], 3))
		outLine += " Z" + str(self.get_z(posNew[0], posNew[1], zOffset))

		outLine += " I" + str(round(-offsetNew[0], 3))
		outLine += " J" + str(round(-offsetNew[1], 3))



		if (self.eMode == "Absolute"):
			eNew = basePos[3] + dirVector[3]*seg
			outLine += " E" + str(round(eNew, 5))
		elif (self.eMode == "Relative"):
			eNew = dirVector[3]
			outLine += " E" + str(round(eNew, 5))

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

	def break_up_arc(self, center, radius, arcAngle, arcLength):
		numArcs = int(math.ceil(arcLength/self.arcSegDist))

		arcSegAngle = arcAngle/numArcs

		eSeg = (self.eCurr-self.ePrev)/numArcs

		zSeg = (self.zCurr-self.zPrev)/numArcs

		outLines = ""

		for arc in range(0, numArcs):
			outLines += self.construct_arc(center, radius, arcSegAngle, arc, eSeg, zSeg)

		return outLines

	def break_up_line(self):
		numSegments = int(math.ceil(self.moveDist/self.lineBreakDist))

		eSeg = (self.eCurr-self.ePrev)/numSegments

		xSeg = (self.xCurr-self.xPrev)/numSegments
		ySeg = (self.yCurr-self.yPrev)/numSegments
		zSeg = (self.zCurr-self.zPrev)/numSegments

		outLines = ""

		for seg in range(1, numSegments+1):
			outLines += self.construct_line((self.xPrev, self.yPrev, self.zPrev, self.ePrev), (xSeg, ySeg, zSeg, eSeg), seg)

		return outLines

	def process_line(self, origLine):

		if not len(origLine):
			return None

		if (self.python_version == 3):
			line = origLine.decode('utf-8').lstrip()
		else:
			line = origLine

		# Check for standard Movement commands
		if (re.match(self.move_pattern, line) is not None) and (self.moveMode != "Relative"):
			# Logic to seperate comments so they can be reattached after processing
			if line.find(";") != -1:
				comSplit = line.split(";")
				activeCode = comSplit[0]
				if len(comSplit) > 1:
					for part in comSplit[1:]:
						self.spareParts += ";" + part + " "
			else:
				activeCode = line

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

				# self.afterStart ensures that the first move isn't broken up and doesnt start at 0, 0, 0
				if (self.afterStart and self.moveDist > self.lineBreakDist and self.lineBreakDist != 0.0):
					line = self.break_up_line()
				else:
					self.afterStart = True
					line = self.reconstruct_line()
			else:
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

					if longPath:
						arcAngle = 2*math.pi-alpha
					else:
						arcAngle = alpha

					# compute the arc length
					arcLength = np.linalg.norm(radius) * arcAngle

					if self.moveCurr == "G2":
						arcAngle *= -1


					# slice up arc
					if self.arcSegDist != 0.0 and arcLength > self.arcSegDist:
						line = self.break_up_arc(center, radius, arcAngle, arcLength)
					else:
						line = self.reconstruct_arc(arcI, arcJ, arcR)
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

					# compute the arc length
					arcLength = arcAngle * arcR

					if self.moveCurr == "G2":
						arcAngle *= -1

					# slice up arc
					if self.arcSegDist != 0.0 and arcLength > self.arcSegDist:
						line = self.break_up_arc(center, pArm, arcAngle, arcLength)
					else:
						line = self.reconstruct_arc(arcI, arcJ, arcR)
				else:
					raise GcodeLevelingError("Arc values missing", "G2/G3 commands either need an R or an I or J")


		# Check for movement mode
		if re.match(self.move_mode_pattern, line) is not None:
			line = re.sub(self.comment_pattern, "", line)

			mode = re.split("\s", line)[0]

			if mode == "G90":
				self.moveMode = "Absolute"
			elif mode == "G91":
				self.moveMode = "Relative"

			return origLine

		# Check for extruder movement mode
		if re.match(self.extruder_mode_pattern, line) is not None:
			line = re.sub(self.comment_pattern, "", line)

			mode = re.split("\s", line)[0]

			if mode == "M82":
				self.eMode = "Absolute"
			elif mode == "M83":
				self.eMode = "Relative"

			return origLine

		if (self.python_version == 3):
			line = line.encode('utf-8')

		return line

class GcodeLevelingPlugin(octoprint.plugin.StartupPlugin,
						  octoprint.plugin.SettingsPlugin,
						  octoprint.plugin.AssetPlugin,
						  octoprint.plugin.TemplatePlugin):


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

	def update_from_settings(self):
		points = self._settings.get(['points'])

		allZeros = True
		for point in points:
			for coor in point:
				if coor != 0.0:
					allZeros = False

		self.pointsEntered = not allZeros

		if self.pointsEntered:
			self.zMin = float(self._settings.get(['zMin']))
			self.zMax = float(self._settings.get(['zMax']))
			self.lineBreakDist = float(self._settings.get(['lineBreakDist']))
			self.arcSegDist = float(self._settings.get(['arcSegDist']))
			self.modelDegree = self._settings.get(['modelDegree'])
			self.invertPosition = bool(self._settings.get(['invertPosition']))
			self.unmodifiedCopy = bool(self._settings.get(['unmodifiedCopy']))

			self.coeffs = twoDimFit.twoDpolyFit(points, int(self.modelDegree['x']), int(self.modelDegree['y']))
			self._logger.info("Leveling Model Computed")
		else:
			self._logger.info("Points have not been entered (or they are all zero). Enter points or disable this plugin if you do not need it.")


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
			"unmodifiedCopy": True
		}

	def on_settings_save(self, data):
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

		self.update_from_settings()

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

__plugin_name__ = "Gcode Leveling"

__plugin_pythoncompat__ = ">=2.7,<4" # python 2 and 3

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = GcodeLevelingPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
		"octoprint.filemanager.preprocessor": __plugin_implementation__.createFilePreProcessor
	}
