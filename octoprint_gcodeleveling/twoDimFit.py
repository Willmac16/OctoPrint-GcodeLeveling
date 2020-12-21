import numpy as np

import sys


# simple rref algorithm
def rref(m):
	matrix = np.copy(m)
	for rc in range(len(matrix)):
		lead = False

		for ind in range(rc, len(matrix)):
			if not(lead) and matrix[ind,rc] != 0:

				lead = True
				matrix[ind] = matrix[ind] / matrix[ind,rc]

				temp = np.copy(matrix[rc])

				matrix[rc] = matrix[ind]

				matrix[ind] = temp
		if (lead):
			for ind in range(len(matrix)):
				if ind != rc:
					matrix[ind] = matrix[ind] - (matrix[ind,rc]*matrix[rc])

	return matrix

# linear system solution function (sets free variables to 0)
def solve(A, Y):
	aug = np.append(A, Y.reshape((Y.shape[0], 1)), axis=1)

	clean = rref(aug)

	coeffs = np.zeros(len(aug[0])-1)

	for row in clean:
		leadingOne = -1
		ind = 0
		if (row[-1] != 0):
			for el in row[:-1]:
				if (el == 1.0 and leadingOne == -1):
					leadingOne = ind
					coeffs[ind] = row[-1]
				elif (el != 0.0):
					coeffs[ind] = 0
				ind += 1

	return coeffs

def twoDpolyEval(coeffs, x, y):
	z = 0

	for r, row in enumerate(coeffs):
		for c, coeff in enumerate(row):
			z += coeff * x**r * y**c

	return z

def sigma(ps, xDeg, yDeg, zDeg=0):
	sum = 0
	for x, y, z in ps:
		sum += (x**xDeg)*(y**yDeg)*(z**zDeg)
	return sum

def twoDpolyFit(ps, xDeg, yDeg):
	A = np.zeros(((xDeg+1)*(yDeg+1), (xDeg+1)*(yDeg+1)))
	ps = np.array(ps, dtype="float")

	for r in range((xDeg+1)*(yDeg+1)):
		xRow = r // (yDeg+1)
		yRow = r % (yDeg+1)
		for c in range((xDeg+1)*(yDeg+1)):
			xCol = c // (yDeg+1)
			yCol = c % (yDeg+1)

			A[r, c] = sigma(ps, xRow+xCol, yRow+yCol)

	Z = np.zeros((xDeg+1)*(yDeg+1))

	for t in range((xDeg+1)*(yDeg+1)):
		xTow = t // (yDeg+1)
		yTow = t % (yDeg+1)

		Z[t] = sigma(ps, xTow, yTow, zDeg=1)

	cS = solve(A, Z)
	coeffs = cS.reshape((xDeg+1),(yDeg+1))
	return coeffs
