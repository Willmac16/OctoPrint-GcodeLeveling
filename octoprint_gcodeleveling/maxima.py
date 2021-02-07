import math, random, time
import numpy as np
from octoprint_gcodeleveling.twoDimFit import twoDpolyEval


from abc import ABC, abstractmethod

threshold = 0.005

class PathWiseMaximizer(ABC):

	def optimize(self, value, first, second):
		pass

	def testPoint(self, value, q):
		v = value(q)
		if (v >= threshold):
			return (q, v)
		else:
			return (False, False)

class Spaceshot(PathWiseMaximizer):
	def __init__(self, shots):
		self.shots = shots
		self.max = None
		self.maxQ = None

	def optimize(self, value, first, second):
		self.maxQ = None
		self.max = 0
		for shot in range(self.shots):
			q = shot/self.shots
			tp, tv = self.testPoint(value, q)
			if (tp and tv > self.max):
				self.maxQ = tp
				self.max = tv
		return self.maxQ

class Scatershot(PathWiseMaximizer):
	def __init__(self, shots):
		self.shots = shots
		self.max = None
		self.maxQ = None

	def optimize(self, value, first, second):
		self.maxQ = None
		self.max = 0
		for shot in range(self.shots):
			q = random.random()
			tp, tv = self.testPoint(value, q)
			if (tp and tv > self.max):
				self.maxQ = tp
				self.max = tv
		return self.maxQ

class SinglePointNewton(PathWiseMaximizer):
	def __init__(self, height=0.00001, telos=0.1, point=0.5):
		self.hMin = height
		self.telos = telos
		self.point = point

	def optimize(self, value, first, second):
				q = self.point

				lvl = 1
				height = 10
				while (abs(height) > self.hMin):
					slope = second(q)
					if (slope != 0.0):
						height = first(q)
						q = -height/slope + q
						lvl += 1
					else:
						break

				if (q > self.telos and q < 1-self.telos):
					tp, _ = self.testPoint(value, q)
					if tp:
						return tp
					else:
						return None

class SingleGradientAscent(PathWiseMaximizer):
	def __init__(self, ds=0.00001, step=10.0, telos=0.01, point=0.5, lvl=200):
		self.sMin = ds
		self.step = step
		self.telos = telos
		self.point = point
		self.lvl = lvl

	def optimize(self, value, first, second):
		q = self.point

		lvl = 0
		slope = 10
		while (abs(slope) > self.sMin and q > self.telos and q < 1-self.telos and lvl < self.lvl):
			slope = first(q)
			# print(lvl, q, slope)
			q += slope*self.step
			lvl += 1

		if (q > self.telos and q < 1-self.telos):
			tp, tv = self.testPoint(value, q)
			if (tp):
				return tp
			else:
				return None
		else:
			return None

class DynastepSingleGradientAscent(PathWiseMaximizer):
	def __init__(self, ds=0.00001, step=10.0, telos=0.01, point=0.5, lvl=500):
		self.sMin = ds
		self.step = step
		self.telos = telos
		self.point = point
		self.lvl = lvl

	def optimize(self, value, first, second):
		q = self.point

		lvl = 0
		slope = 10
		while (abs(slope) > self.sMin and q > self.telos and q < 1-self.telos and lvl < self.lvl):
			slope = first(q)
			q += slope*self.step*math.exp(-lvl)
			lvl += 1

		if (q > self.telos and q < 1-self.telos):
			tp, tv = self.testPoint(value, q)
			if (tp):
				return tp
			else:
				return None
		else:
			return None

def der(coeffs):
	xPartial = []
	yPartial = []

	for r, row in enumerate(coeffs):
		xRow = []
		yRow = []

		for c, coeff in enumerate(row):
			xRow.append(coeff * r)

			if (c != 0):
				yRow.append(coeff * c)

		if (r != 0):
			xPartial.append(xRow)
		yPartial.append(yRow)

	return dict(x = xPartial, y = yPartial)

def polySqrGradient(coeffs, x, y):
	return np.array((2*twoDpolyEval(coeffs, x, y)*twoDpolyEval(der(coeffs)['x'], x, y),
			2*twoDpolyEval(coeffs, x, y)*twoDpolyEval(der(coeffs)['y'], x, y)))

def polySqr2ndDerivative(coeffs, x, y):
	return np.array((
	# xx
	2*twoDpolyEval(der(coeffs)['x'], x, y)*twoDpolyEval(der(coeffs)['x'], x, y)
	+ 2*twoDpolyEval(coeffs, x, y)*twoDpolyEval(der(der(coeffs)['x'])['x'], x, y),
	# yy
	2*twoDpolyEval(der(coeffs)['y'], x, y)*twoDpolyEval(der(coeffs)['y'], x, y)
	+ 2*twoDpolyEval(coeffs, x, y)*twoDpolyEval(der(der(coeffs)['y'])['y'], x, y),
	# xy
	2*twoDpolyEval(der(coeffs)['y'], x, y)*twoDpolyEval(der(coeffs)['x'], x, y)
	+ 2*twoDpolyEval(coeffs, x, y)*twoDpolyEval(der(der(coeffs)['x'])['y'], x, y)
	))

def newtonHeight(coeffs, lmbd, start, heading, off):
	h = heading(lmbd)
	x, y = start + off(lmbd)

	return np.dot(polySqrGradient(coeffs, x, y), h)

def newtonSlope(coeffs, lmbd, start, heading, off):
	h = heading(lmbd)
	x, y = start + off(lmbd)

	return np.dot(polySqr2ndDerivative(coeffs, x, y), np.array((h[0]**2, h[1]**2, 2*h[0]*h[1])))

# segments a line into the minimum set required
def lineWiseMaxima(coeffs, start, end, pwm):
	# print("LWM ({}) ({})".format(start, end))
	outLines = []

	c = coeffs.copy()

	endZ = twoDpolyEval(c, end[0], end[1])
	startZ = twoDpolyEval(c, start[0], start[1])

	line = np.array((end[0]-start[0], end[1]-start[1]))
	magLine = np.linalg.norm(line)
	normLine = line/magLine

	# compute height delta properly remove it from coeffs
	c[1, 0] -= normLine[0] * (endZ-startZ) / magLine
	c[0, 1] -= normLine[1] *  (endZ-startZ) / magLine

	# compute height at start and subtract it from (0,0) coeff
	c[0, 0] -= twoDpolyEval(c, start[0], start[1])

	lineHeading = lambda lmd : np.array((end[0]-start[0], end[1]-start[1]))
	lineOffset = lambda lmd : lmd * lineHeading(lmd)

	lineSqr = lambda lmd : twoDpolyEval(c, lineOffset(lmd)[0]+start[0], lineOffset(lmd)[1]+start[1])**2
	first = lambda lmd : newtonHeight(c, lmd, start, lineHeading, lineOffset)
	second = lambda lmd : newtonSlope(c, lmd, start, lineHeading, lineOffset)

	q = pwm.optimize(lineSqr, first, second)

	if (q is not None):
		x, y = start + lineOffset(q)
		middle = np.array((x, y))

		outLines.extend(lineWiseMaxima(coeffs, start, middle, pwm))
		outLines.extend(lineWiseMaxima(coeffs, middle, end, pwm))
	else:
		outLines.append([start, end])

	return outLines

def rotateVector(theta, vec):
	rotArray = np.array(((math.cos(theta),-math.sin(theta)),(math.sin(theta),math.cos(theta))))
	return np.matmul(rotArray, vec)

# D(x,y)/Dtheta
def radiusGradient(arcAngle, radius):
	mag = np.linalg.norm(radius)
	normRadius = radius / mag

	theta = math.atan2(normRadius[1], normRadius[0]) + arcAngle

	return np.array((-mag*math.sin(theta), mag*math.cos(theta)))

def radius2ndDer(arcAngle, radius):
	mag = np.linalg.norm(radius)
	normRadius = radius / mag

	theta = math.atan2(normRadius[1], normRadius[0]) + arcAngle

	return np.array((-mag*math.cos(theta), -mag*math.sin(theta)))

def arcDistSqr(coeffs, center, radius, arcAngle, zDelta, q):
	point = rotateVector(arcAngle*q, radius) + center
	# print(point, "q", q, twoDpolyEval(coeffs, point[0], point[1]))
	return (twoDpolyEval(coeffs, point[0], point[1]) - zDelta*q)**2

def adsDer(coeffs, center, radius, arcAngle, zDelta, q):
	point = rotateVector(arcAngle*q, radius) + center
	gradient = np.array((twoDpolyEval(der(coeffs)['x'], point[0], point[1]),
	 					twoDpolyEval(der(coeffs)['y'], point[0], point[1])))
	heading = radiusGradient(q*arcAngle, radius)
	# print(point, gradient)

	# return np.dot(polySqrGradient(coeffs, point[0], point[1]), heading)
	return 2*(twoDpolyEval(coeffs, point[0], point[1]) - zDelta*q)*(np.dot(gradient, heading) - zDelta)

def ads2ndDer(coeffs, center, radius, arcAngle, zDelta, q):
	point = rotateVector(arcAngle*q, radius) + center
	gradient = np.array((twoDpolyEval(der(coeffs)['x'], point[0], point[1]),
	 					twoDpolyEval(der(coeffs)['y'], point[0], point[1])))
	heading = radiusGradient(q*arcAngle, radius)

	grad2 = np.array((twoDpolyEval(der(der(coeffs)['x'])['x'], point[0], point[1]),
					  twoDpolyEval(der(der(coeffs)['y'])['y'], point[0], point[1]),
					  twoDpolyEval(der(der(coeffs)['x'])['y'], point[0], point[1])*2))
	head2 = np.array((heading[0], heading[1], heading[0]*heading[1]))

	prodA = (np.dot(gradient, heading) - zDelta)**2
	# np.dot(gradient, heading)
	pordBee = np.dot(grad2, head2) + np.dot(gradient, radius2ndDer(arcAngle*q, radius))
	prodB = (twoDpolyEval(coeffs, point[0], point[1]) - zDelta*q)*pordBee

	return (2*prodA+2*prodB)

# segments an arc into the minimum set required
def flatArcWiseMaxima(coeffs, center, radius, arcAngle, qin, qend, pwm):
	# print(center+radius, center, arcAngle)
	center = np.array(center)
	radius = np.array(radius)
	c = coeffs.copy()
	outArcs = []

	start = center + radius
	end = center + rotateVector(arcAngle, radius)

	endZ = twoDpolyEval(c, end[0], end[1])
	startZ = twoDpolyEval(c, start[0], start[1])
	deltaZ = endZ-startZ

	c[0, 0] -= twoDpolyEval(c, start[0], start[1])

	value = lambda lmd : arcDistSqr(c, center, radius, arcAngle, deltaZ, lmd)
	first = lambda lmd : adsDer(c, center, radius, arcAngle, deltaZ, lmd)
	second = lambda lmd : ads2ndDer(c, center, radius, arcAngle, deltaZ, lmd)


	q = pwm.optimize(value, first, second)

	if (q is not None):
		middle = arcAngle * q
		# print("breaking at {}".format(q))
		outArcs.extend(flatArcWiseMaxima(coeffs, center, radius, middle-0, qin, qin+(qend-qin)*q, pwm))
		outArcs.extend(flatArcWiseMaxima(coeffs, center, rotateVector(middle, radius),
										arcAngle-middle, qin+(qend-qin)*q, qend, pwm))
	else:
		outArcs.append([start, center, arcAngle, qin, qend])
	return outArcs
