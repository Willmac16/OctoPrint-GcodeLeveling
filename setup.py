# coding=utf-8

from distutils.core import setup, Extension
module1 = Extension('leveling',
                    sources = ['octoprint_gcodeleveling/src/parse.cpp'])

setup(
    name = 'GcodeLeveling_Standalone',
	version = '1.0.0',
	description = 'GcodeLeveling Standalone Application',
	ext_modules = [module1],
	scripts=['octoprint_gcodeleveling/bin/gcode-level'],
	python_requires = ">=3,<4"
 )