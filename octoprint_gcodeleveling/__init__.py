# coding=utf-8
from __future__ import absolute_import

import re, sys, math, numpy as np, threading, time

import octoprint.plugin
import octoprint.filemanager
import octoprint.filemanager.util
from octoprint.filemanager import FileDestinations

from octoprint.access.permissions import Permissions

import leveling

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

			if fileName.contains("-GCL"):
				self._logger.debug("skipping a GCL file")
				return file_object
			else:
				origPath = self._file_manager.path_on_disk(FileDestinations.LOCAL, path)

				startTime = time.time()
				# runs the c++ file processing
				longPath = leveling.level(self.coeffs, origPath, self._plugin_version, (self.zMin, self.zMax, self.invertPosition, self.lineBreakDist, self.arcSegDist))

				endTime = time.time()
				procTime = endTime-startTime

				self._logger.debug(longPath)

				# work out the different forms of the path
				shortPath = self._file_manager.path_in_storage(FileDestinations.LOCAL, longPath)
				path, name = self._file_manager.canonicalize(FileDestinations.LOCAL, longPath)

				# takes the file from c++ and adds it into octoprint
				newFO = octoprint.filemanager.util.DiskFileWrapper(name, longPath, move=True)
				self._file_manager.add_file(FileDestinations.LOCAL, longPath, newFO, allow_overwrite=True)
			return file_object
		else:
			self._logger.info("Points have not been entered (or they are all zero). Enter points or disable this plugin if you do not need it.")

			return file_object

	# ~~ StartupPlugin mixin

	def on_after_startup(self):
		self._logger.info("Gcode Leveling Plugin started")

		self.update_from_settings()

	##~~ SettingsPlugin mixin

	def get_settings_defaults(self):
		return {
			"points": [
				[0,0,0]
			],
			"coeffs": [
				[[0]]
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

		# normal settings loading

		# TODO: Hash the points and check before updating the coeffs
		points = self._settings.get(['points'])

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

			self._logger.info("Starting Leveling Model")
			self.coeffs = leveling.fit(points, (int(self.modelDegree['x']), int(self.modelDegree['y'])))
			self._logger.info("Leveling Model Computed")
			self._logger.debug(self.coeffs)
		else:
			# Add Pnotify
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

	## AutoProbing Code
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

	def send_BLV(self):
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
			if count % self.yCount == 0:
				forward = not forward

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
		self._logger.info("mesh sent to BLV")

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
						thread = threading.Thread(target=self.send_BLV)
						thread.daemon = True
						thread.start()
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
