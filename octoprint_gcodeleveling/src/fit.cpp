#include <math.h>
#include <iostream>

// rref in place
double** rref(double **matrix, int rows, int cols)
{
    for (int rc = 0; rc < rows; rc++)
    {
        bool lead = false;

        for (int ind = rc; ind < rows && !lead; ind++)
        {
            if (matrix[ind][rc] != 0.0)
            {
                lead = true;
                // Divide the row by leading value to get a leading one
                double leadVal = matrix[ind][rc];
                for (int col = 0; col < cols; col++) {
                    matrix[ind][col] /= leadVal;
                }

                if (ind != rc)
                {
                    // swap rows around
                    double *temp = matrix[ind];
                    matrix[rc] = matrix[ind];
                    matrix[ind] = temp;
                }
            }
        }

        if (lead)
        {
            for (int ind = 0; ind < rows; ind++)
            {
                if (ind != rc)
                {
                    double cleanAway =  matrix[ind][rc];
                    for (int col = 0; col < cols; col++)
                    {
                        // subtract away any value in the rc column;
                        matrix[ind][col] -= matrix[rc][col] * cleanAway;
                    }
                }
            }
        }
    }

    return matrix;
}

// solves system of eqns and puts values in the y array
void solve(double **a, int rows, int cols, double *y)
{
    double **aug = new double*[rows];

    for (int row = 0; row < rows; row++)
    {
        double *eqn = new double[cols+1];
        for (int c = 0; c < cols; c++) {
            eqn[c] = a[row][c];
        }
        eqn[cols] = y[row];

        aug[row] = eqn;
    }

    rref(aug, rows, cols+1);

    for (int row = 0; row < rows; row++)
    {
        int leadingOne = -1;
        double *r = aug[row];
        for (int c = 0; c < cols; c++)
        {
            if (r[c] == 1.0 && leadingOne == -1) {
                leadingOne = c;
                y[c] = r[cols];
            } else if (r[c] != 0.0) {
                y[c] = 0;
            }
        }
    }
}

double sigma(double points[][3], int numPoints, int xDeg, int yDeg, int zDeg)
{
    double sum = 0;
    for (int point = 0; point < numPoints; point++)
    {
        sum += pow(points[point][0], xDeg)*pow(points[point][1], yDeg)*pow(points[point][2], zDeg);
    }
    return sum;
}

double sigma(double points[][3], int numPoints, int xDeg, int yDeg)
{
    double sum = 0;
    for (int point = 0; point < numPoints; point++)
    {
        sum += pow(points[point][0], xDeg)*pow(points[point][1], yDeg);
    }
    return sum;
}

// fit the polynomial model to the points
double** fit(double points[][3], int numPoints, int xDeg, int yDeg)
{
    int yCombo = yDeg + 1;
    int combo = (xDeg+1)*yCombo;
    double **a = new double*[combo];

    for (int row=0; row<combo; row++)
    {
        int xRow = row / yCombo;
        int yRow = row % yCombo;

        double *eqn = new double[combo];

        for (int col = 0; col < combo; col++)
        {
            int xCol = col / yCombo;
            int yCol = col % yCombo;

            eqn[col] = sigma(points, numPoints, xRow+xCol, yRow+yCol);
        }
        a[row] = eqn;
    }

    double *z = new double[combo];

    for (int t = 0; t < combo; t++)
    {
        int xTow = t / yCombo;
        int yTow = t % yCombo;

        z[t] = sigma(points, numPoints, xTow, yTow, 1);
    }

    solve(a, combo, combo, z);

    // Delete the square matrix
    for (int row=0; row < combo; row++) {
        delete[] a[row];
    }
    delete[] a;

    double **coeffs = new double*[xDeg+1];
    for (int i = 0; i < xDeg+1; i++)
    {
        double *column = new double[yCombo];
        for (int j = 0; j < yCombo; j++)
        {
            column[j] = z[i*(yCombo)+j];
        }
        coeffs[i] = column;
    }
    delete[] z;

    return coeffs;
}
