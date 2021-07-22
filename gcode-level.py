import sys

if len(sys.argv) > 1:
	import leveling, logging, os, yaml

	with open(r'points.yaml') as file:
		yml = yaml.load(file, Loader=yaml.FullLoader)
		points = yml['points']

	logging.basicConfig(level=logging.INFO)
	coeffs = leveling.fit(points, (3, 2))

	for filePath in sys.argv[1:]:
		if filePath.endswith(".gcode"):
			logging.info(filePath)
			logging.info(leveling.level(coeffs, filePath, "test-file", (0.0, 400.0, True)))
