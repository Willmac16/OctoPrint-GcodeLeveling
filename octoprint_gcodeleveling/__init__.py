# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import octoprint.filemanager
import octoprint.filemanager.util
import octoprint_gcodeleveling.twoDimFit

import re
import sys

from octoprint.util.comm import strip_comment

class GcodeLevelingError(Exception):
	def __init__(self, expression, message):
		self.expression = expression
		self.message = message

class GcodePreProcessor(octoprint.filemanager.util.LineProcessorStream):
	def __init__(self, fileBufferedReader, python_version, logger, coeffs, zMin, zMax, lineBreakDist, invertPosition):
		super(GcodePreProcessor, self).__init__(fileBufferedReader)
		self.python_version = python_version
		self._logger = logger
		self.coeffs = coeffs
		self.zMin = zMin
		self.zMax = zMax
		self.lineBreakDist = lineBreakDist
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

		self.move_pattern = re.compile("^G[0-1]\s")
		self.feed_pattern = re.compile("^F")
		self.move_mode_pattern = re.compile("^G9[0-1]")
		self.extruder_mode_pattern = re.compile("^M8[2-3]")
		self.comment_pattern = re.compile(";")

	def move_dist(self):
		return ((self.xCurr-self.xPrev)**2 + (self.yCurr-self.yPrev)**2 + (self.zCurr-self.zPrev)**2)**0.5

	def get_z(self, x, y, zOffset):
		zNew = twoDimFit.twoDpolyEval(self.coeffs, x, y) + (zOffset * (-1 if self.invertPosition else 1))

		if (zNew < self.zMin or zNew > self.zMax):
			raise GcodeLevelingError("Computed Z was outside of bounds", "Gcode Leveling config likely needs to be changed")
		return round(zNew, 3)

	def construct_line(self, basePos, dirVector, seg):
		outLine = self.moveCurr

		xNew = basePos[0] + dirVector[0]*seg
		yNew = basePos[1] + dirVector[1]*seg
		zOffset = basePos[2] + dirVector[2]*seg



		outLine += " X" + str(round(xNew, 3))
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

	def reconstruct_line(self):
		outLine = self.moveCurr

		outLine += " X" + str(round(self.xCurr, 3))
		outLine += " Y" + str(round(self.yCurr, 3))
		outLine += " Z" + str(self.get_z(self.xCurr, self.yCurr, self.zCurr))

		if self.eMode != "None":
			outLine += " E" + str(round(self.eCurr, 5))

		outLine += " " + self.spareParts
		self.spareParts = ""

		outLine += "\n"

		return outLine

	def break_up_line(self):
		numSegments = int(self.moveDist//self.lineBreakDist)

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
				if len(comSplit) > 1:
					activeCode = comSplit[0]

					self.spareParts += ";"

					for part in comSplit[1:]:
						self.spareParts += part + " "
				else:
					return origLine
			else:
				activeCode = line


			gcodeParts = re.split("\s", activeCode)


			self.xPrev = self.xCurr
			self.yPrev = self.yCurr
			self.zPrev = self.zCurr

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
					else:
						self.spareParts = part + " " + self.spareParts
			self.moveDist = self.move_dist()



			# self.afterStart ensures that the first move isn't broken up and doesnt start at 0, 0, 0
			if (self.afterStart and self.moveDist > self.lineBreakDist and self.lineBreakDist != 0.0):
				line = self.break_up_line()
			else:
				self.afterStart = True
				line = self.reconstruct_line()

		# Check for movement mode
		if re.match(self.move_mode_pattern, line) is not None:
			line = re.sub(self.comment_pattern, "", line)

			mode = re.split("\s", line)[0]

			if mode == "G90":
				self.moveMode = "Absolute"
			elif mode == "G91":
				self.moveMode = "Relative"

			# self._logger.info("Line sets move mode " + self.moveMode)


			return origLine

		# Check for extruder movement mode
		if re.match(self.extruder_mode_pattern, line) is not None:
			line = re.sub(self.comment_pattern, "", line)

			mode = re.split("\s", line)[0]

			if mode == "M82":
				self.eMode = "Absolute"
			elif mode == "M83":
				self.eMode = "Relative"

			# self._logger.info("Line sets extruder mode " + self.eMode)


			return origLine


		if (self.python_version == 3):
			line = line.encode('utf-8')

		# self._logger.info(line)

		return line

class GcodeLevelingPlugin(octoprint.plugin.StartupPlugin,
						  octoprint.plugin.SettingsPlugin,
						  octoprint.plugin.AssetPlugin,
						  octoprint.plugin.TemplatePlugin):


	def createFilePreProcessor(self, path, file_object, blinks=None, printer_profile=None, allow_overwrite=True, *args, **kwargs):

		fileName = file_object.filename
		if not octoprint.filemanager.valid_file_type(fileName, type="gcode"):
			return file_object
		fileStream = file_object.stream()
		self._logger.info("Gcode PreProcessing started.")
		self.gcode_preprocessor = GcodePreProcessor(fileStream, self.python_version, self._logger, self.coeffs, self.zMin, self.zMax, self.lineBreakDist, self.invertPosition)
		return octoprint.filemanager.util.StreamWrapper(fileName, self.gcode_preprocessor)


	def update_from_settings(self):
		points = self._settings.get(['points'])
		self.zMin = float(self._settings.get(['zMin']))
		self.zMax = float(self._settings.get(['zMax']))
		self.lineBreakDist = float(self._settings.get(['lineBreakDist']))
		self.modelDegree = self._settings.get(['modelDegree'])
		self.invertPosition = bool(self._settings.get(['invertPosition']))

		self.coeffs = twoDimFit.twoDpolyFit(points, int(self.modelDegree['x']), int(self.modelDegree['y']))
		self._logger.info("Leveling Model Computed")

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
			"invertPosition": False
		}

	def on_settings_save(self, data):
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

		self.update_from_settings()

	def get_settings_version(self):
		return 0

	##~~ AssetPlugin mixin

	def get_assets(self):
		# Define your plugin's asset files to automatically include in the
		# core UI here.
		return dict(
			js=["js/GcodeLeveling.js"]
			# css=["css/GcodeLeveling.css"],
			# less=["less/GcodeLeveling.less"]
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
		# Define the configuration for your plugin to use with the Software Update
		# Plugin here. See https://docs.octoprint.org/en/master/bundledplugins/softwareupdate.html
		# for details.
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
