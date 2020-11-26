# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import octoprint.filemanager
import octoprint.filemanager.util
import octoprint_GcodeLeveling.twoDimFit

import re
import sys

from octoprint.util.comm import strip_comment

class GcodeLevelingError(Exception):
	def __init__(self, expression, message):
		self.expression = expression
		self.message = message

class GcodePreProcessor(octoprint.filemanager.util.LineProcessorStream):
	def __init__(self, fileBufferedReader, python_version, logger, coeffs, zMin, zMax):
		super(GcodePreProcessor, self).__init__(fileBufferedReader)
		self.python_version = python_version
		self._logger = logger
		self.coeffs = coeffs
		self.zMin = zMin
		self.zMax = zMax

		self.zWarned = False

		self.moveCurr = "G0"
		self.xCurr = 0.0
		self.yCurr = 0.0
		self.zCurr = 0.0
		self.fCurr = 0.0
		self.fChanged = False
		self.eCurr = 0.0
		self.eUsed = False

		self.move_pattern = re.compile("^G[0-1]\s")
		self.feed_pattern = re.compile("^F")
		self.comment_pattern = re.compile(";.*$[\n]*")

	def reconstruct_line(self, zNew):
		outLine = self.moveCurr

		outLine += " X" + str(self.xCurr)
		outLine += " Y" + str(self.yCurr)
		outLine += " Z" + str(zNew)

		if self.fChanged == True:
			outLine += " F" + str(self.fCurr)
			self.fChanged = False
		if self.eUsed == True:
			outLine += " E" + str(self.eCurr)

		outLine += "\n"

		return outLine


	def process_line(self, origLine):
		if not len(origLine):
			return None

		if (self.python_version == 3):
			line = origLine.decode('utf-8').lstrip()
		else:
			line = origLine

		if re.match(self.feed_pattern, line) is not None:
			line = re.sub(self.comment_pattern, "", line)

			fCommand = re.split("\s", line)[0]
			self.fCurr = float(fCommand[1:])

			return origLine

		if re.match(self.move_pattern, line) is not None:
			line = re.sub(self.comment_pattern, "", line)
			# print(line)
			gcodeParts = re.split("\s", line)[:]

			self.moveCurr = gcodeParts[0]

			for part in gcodeParts[1:]:
				if part != "":
					leadChar = part[0]
					if leadChar == "X":
						self.xCurr = float(part[1:])
					elif leadChar == 'Y':
						self.yCurr = float(part[1:])
					elif leadChar == 'Z':
						self.zCurr = float(part[1:])
					elif leadChar == 'F':
						fNew = float(part[1:])
						if (fNew != self.fCurr):
							self.fChanged = True
						self.fCurr = fNew

					elif leadChar == 'E':
						self.eUsed = True
						self.eCurr = float(part[1:])


			zNew = twoDimFit.twoDpolyEval(self.coeffs, self.xCurr, self.yCurr) - self.zCurr

			if (zNew < self.zMin or zNew > self.zMax):
				# self._logger.warn("Computed Z was outside of bounds")
				# TODO: communicate to the frontend the error
				raise GcodeLevelingError("Computed Z was outside of bounds", "Gcode Leveling config likely needs to be changed")

			# self._logger.info((self.xCurr, self.yCurr, zNew))

			line = self.reconstruct_line(zNew)

		if (self.python_version == 3):
			line = line.encode('utf-8')

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
		self._logger.info("GcodePreProcessor started processing.")
		self.gcode_preprocessor = GcodePreProcessor(fileStream, self.python_version, self._logger, self.coeffs, self.zMin, self.zMax)
		self._logger.info("GcodePreProcessor finished processing.")
		return octoprint.filemanager.util.StreamWrapper(fileName, self.gcode_preprocessor)


	# ~~ StartupPlugin mixin
	def on_after_startup(self):
		self.points = [[0.0, 0.0, 71.75], [0.0, 200.0, 71.75], [0.0, 400.0, 72.0], [200.0, 400.0, 71.25], [400.0, 400.0, 71.75], [400.0, 200.0, 71.75], [400.0, 0.0, 72.0], [200.0, 0.0, 71.25], [200.0, 200.0, 71.5], [100.0, 100.0, 71.0], [300.0, 100.0, 71.6], [100.0, 300.0, 71.75], [300.0, 300.0, 71.5], [100.0, 0.0, 71.25], [300.0, 0.0, 71.5], [0.0, 100.0, 71.25], [200.0, 100.0, 71.5], [400.0, 100.0, 71.75], [100.0, 200.0, 71.5], [300.0, 200.0, 71.6], [0.0, 300.0, 71.75], [200.0, 300.0, 71.5], [400.0, 300.0, 71.75], [100.0, 400.0, 71.0], [300.0, 400.0, 71.5]]

		self.zMin = 0.0
		self.zMax = 75.0
		self._logger.info("Gcode Leveling Plugin started")
		if (sys.version_info > (3, 5)): # Detect and set python version
			self.python_version = 3
		else:
			self.python_version = 2

		self.coeffs = twoDimFit.twoDpolyFit(self.points, 4, 4)
		self._logger.info("Leveling Model Computed")

	##~~ SettingsPlugin mixin

	def get_settings_defaults(self):
		return dict(
			# put your plugin's default settings here
		)

	##~~ AssetPlugin mixin

	# def get_assets(self):
	# 	# Define your plugin's asset files to automatically include in the
	# 	# core UI here.
	# 	return dict(
	# 		js=["js/GcodeLeveling.js"],
	# 		css=["css/GcodeLeveling.css"],
	# 		less=["less/GcodeLeveling.less"]
	# 	)

	##~~ Softwareupdate hook

	def get_update_information(self):
		# Define the configuration for your plugin to use with the Software Update
		# Plugin here. See https://docs.octoprint.org/en/master/bundledplugins/softwareupdate.html
		# for details.
		return dict(
			GcodeLeveling=dict(
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


# If you want your plugin to be registered within OctoPrint under a different name than what you defined in setup.py
# ("OctoPrint-PluginSkeleton"), you may define that here. Same goes for the other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties. See the documentation for that.
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
