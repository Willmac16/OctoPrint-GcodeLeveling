#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <regex>

#include <fstream>
#include <sstream>
#include <string>
#include <iostream>
#include <math.h>
#include <cmath>

#include "vector.cpp"
#include "fit.cpp"

// Logging Vars
static char module_name[] = "octoprint.plugins.gcodeleveling-C++";
static PyObject *logging_library = NULL;
static PyObject *logging_object= NULL;

// Thread State Var
// I use Py_UNBLOCK_THREADS and Py_BLOCK_THREADS instead of the begin/end pair
// so that the code can block threading only for logging and still compile
static PyThreadState *_save;

// logging wrappers
// self._logger.info
void info(std::string msg)
{
    Py_BLOCK_THREADS
    PyObject *logging_message = Py_BuildValue("s", msg.c_str());
    Py_XINCREF(logging_message);
    PyObject_CallMethod(logging_object, "info", "O", logging_message, NULL);

    Py_DECREF(logging_message);
    Py_UNBLOCK_THREADS
}

// self._logger.debug
void debug(std::string msg)
{
    Py_BLOCK_THREADS
    PyObject *logging_message = Py_BuildValue("s", msg.c_str());
    Py_XINCREF(logging_message);
    PyObject_CallMethod(logging_object, "debug", "O", logging_message, NULL);

    Py_DECREF(logging_message);
    Py_UNBLOCK_THREADS
}

class GcodeState {
public:
    friend void parseLine(std::string line, std::ostream *out, std::string lineEnd, GcodeState *current, GcodeState *next);
    friend void parseArgs(std::istream *iss, GcodeState *next);
    friend void interpolateState(GcodeState *current, GcodeState *next, std::ostream *out, std::string lineEnd, double **coeffs, int xDeg, int yDeg, float minZ, float maxZ, bool invertZ);
    friend float evalPoint(double **coeffs, int xDeg, int yDeg, GcodeState *current, GcodeState *next, float minZ, float maxZ, bool invertZ);
    void reset();
protected:
    bool interpNeeded = false;

    // We need to know what absolute position the machine is in to level
    // A single absolute command at the start will suffice
    unsigned short int absLock = 0;
    Vector pos, absPos, posOffset;
    // absolutely positioned and leveled Z value
    float absZ;

    float i, j, r, e;
    // Arc mode | -1: disabled | 0: R mode | 1: IJ mode
    short int arcMode = -1;

    std::string extraArgs;

    // Move Mode (e.g. G0/G1 or G2/G3)
    unsigned short int moveMode;
    // Workspace plane | 0: XY | 1: ZX | 2: YZ
    unsigned short int workspacePlane;
    // Positioning mode | 0: relative | 1: absolute
    unsigned short int positioningMode = 1;
    // Extruder mode | -1: disabled | 0: relative | 1: absolute
    short int extruderMode = -1;
};

void GcodeState::reset()
{
    this->extraArgs = "";
    this->arcMode = -1;
    if (this->positioningMode == 0) {
        this->pos = {0,0,0};
    }

    this->i = 0;
    this->j = 0;
    this->r = 0;

    if (this->extruderMode == 0)
        this->e = 0;
    this->interpNeeded = false;
}

float roundTo(int percision, float in)
{
    float out;
    for (int i = 0; i < percision; i++)
    {
        in *= 10;
    }

    out = round(in);
    for (int i = 0; i < percision; i++)
    {
        out /= 10;
    }
    return out;
}

float parseFloat(std::istream *stream)
{
    int n;
    bool point = false, negative = false;

    std::string val = "";
    while ((n = stream->peek()))
    {
        if (n > 47 && n <= 57)
        {
            val += stream->get();
        }
        else if (n == 46)
        {
            if (!point)
            {
                val += stream->get();
                point = true;
            }
            else
                break;
        }
        else if (n == '-')
        {
            if (!negative)
            {
                val += stream->get();
                negative = true;
            }
            else
                break;
        }
        else
            break;
    }

    if (val != "")
        return std::stof(val);
    else
        return NAN;
}

// runs through the rest of a line and loads neccesary args into the state object
void parseArgs(std::istream *iss, GcodeState *next)
{
    char arg;
    while ((*iss >> arg) && arg != ';')
    {
        if (arg == '(')
        {
            next->extraArgs += arg;
            do
            {
                *iss >> arg;
                next->extraArgs += arg;
            }
            while (arg != ')');
        }
        char upp = toupper(arg);
        float f;
        switch (upp)
        {
            case 'X':
            f = parseFloat(iss);
            if (isnormal(f)) {
                next->pos.x = f;
                next->absLock = next->absLock | 1;
            }
            break;
            case 'Y':
            f = parseFloat(iss);
            if (isnormal(f)) {
                next->pos.y = f;
                next->absLock = next->absLock | 2;
            }
            break;
            case 'Z':
            f = parseFloat(iss);
            if (isnormal(f)) {
                next->pos.z = f;
                next->absLock = next->absLock | 4;
            }
            break;
            case 'I':
            f = parseFloat(iss);
            if (isnormal(f)) {
                next->arcMode = 0;
                next->i = f;
            }
            break;
            case 'J':
            f = parseFloat(iss);
            if (isnormal(f)) {
                next->arcMode = 0;
                next->j = f;
            }
            break;
            case 'R':
            f = parseFloat(iss);
            if (isnormal(f)) {
                next->arcMode = 1;
                next->r = f;
            }
            break;
            case 'E':
            f = parseFloat(iss);
            if (isnormal(f)) {
                if (next->extruderMode == -1)
                    next->extruderMode = 1;
                next->e = f;
            }
            break;
            default:
            if (upp > 'A' && upp <= 'Z')
            {
                next->extraArgs += " ";
                next->extraArgs += arg;
            }
            else
            {
                next->extraArgs += arg;
            }
            break;
        }
    }

    std::string comment;
    std::getline(*iss, comment);

    if (comment != "")
    {
        next->extraArgs += ";" + comment;
    }

    if (next->positioningMode) {
        next->absPos = next->pos + next->posOffset;
    } else if (next->absLock == 7) {
        next->absPos.add(next->pos);
    }
}

// takes in a line and sets up the state object
void parseLine(std::string line, std::ostream *out, std::string lineEnd, GcodeState *current, GcodeState *next)
{
    std::istringstream iss(line);
    char cmd;
    int num;
    if ((iss >> cmd))
    {
        char upp = toupper(cmd);
        if (upp == 'G')
        {
            if ((iss >> num))
            {
                if (num < 5 && num >= 0)
                {
                    next->interpNeeded = true;
                    next->moveMode = num;

                    parseArgs(&iss, next);
                }
                else if (num == 92)
                {
                    parseArgs(&iss, next);
                    next->absPos = current->absPos;

                    next->posOffset = next->pos - next->absPos;

                    *out << line << lineEnd;
                }
                else if (num == 91)
                {
                    next->positioningMode = false;
                    *out << line << lineEnd;
                }
                else if (num == 90)
                {
                    next->positioningMode = true;
                    *out << line << lineEnd;
                }
                else if (num >= 17 && num < 20)
                {
                    next->workspacePlane = num - 17;
                }
                else
                {
                    *out << line << lineEnd;
                }
            }
        }
        else if (upp == 'M')
        {
            if ((iss >> num))
            {
                if (num == 83)
                {
                    next->extruderMode = false;
                    *out << line << lineEnd;
                }
                else if (num == 82)
                {
                    next->extruderMode = true;
                    *out << line << lineEnd;
                }
                else
                {
                    *out << line << lineEnd;
                }
            }
        }
        else if ((upp >= 'X' && upp <= 'Z') || (upp >= 'I' && upp <= 'J'))
        {
            next->interpNeeded = true;

            parseArgs(&iss, next);
        }
        else
        {
            *out << line << lineEnd;
        }
    }
}

// returns correctly relative and offset z value for a gcode state
float evalPoint(double **coeffs, int xDeg, int yDeg, GcodeState *current, GcodeState *next, float minZ, float maxZ, bool invertZ)
{
    float absZ = 0.0;
    for (int i=0; i<xDeg; i++)
    {
        for (int j=0; j<yDeg; j++)
        {
            absZ += coeffs[i][j]*pow(next->absPos.x, i)*pow(next->absPos.y, j);
        }
    }

    if (invertZ) {
        absZ -= next->absPos.z;
    } else {
        absZ += next->absPos.z;
    }

    next->absZ = absZ;

    if (next->positioningMode) {
        return absZ - next->posOffset.z;
    } else {
        return absZ - current->absZ;
    }
}

// Generates leveled gcode to go between states (possibly subdivided)
void interpolateState(GcodeState *current, GcodeState *next, std::ostream *out, std::string lineEnd, double **coeffs, int xDeg, int yDeg, float minZ, float maxZ, bool invertZ)
{
    if (next->interpNeeded)
    {
        // just write the out value without any leveling
        if (next->moveMode < 2)
        {
            *out << "G" << next->moveMode;
            if (next->pos.x != current->pos.x)
                *out << " X" << next->pos.x;

            if (next->pos.y != current->pos.y)
                *out << " Y" << next->pos.y;

            // only send an adjusted z value if we know where absolutely we are
            if (next->absLock == 7) {
                *out << " Z" << evalPoint(coeffs, xDeg, yDeg, current, next, minZ, maxZ, invertZ);
            }

            if (next->extruderMode == 0) {
                *out << " E" << next->e;
            } else if (next->extruderMode == 1 && next->e != current->e) {
                *out << " E" << next->e;
            }

            *out << next->extraArgs << lineEnd;
        }
    }
}

std::string levelFile(double **coeffs, int xDeg, int yDeg, std::string inPath, std::string version, float minZ, float maxZ, bool invertZ)
{
    std::ifstream infile(inPath);


    std::regex r("\\.g(co)*(de)*");
    std::string opath = std::regex_replace(inPath, r, "-GCL.gcode");

    // TODO: setup write back to original file
    std::ofstream out(opath);

    info("Working on file " + opath);

    std::string line;

    GcodeState *current = new GcodeState();
    GcodeState *next = new GcodeState();

    std::string lineEnd = "\n";

    // Begin Line Grab loop
    getline(infile, line);

    // determine line ending
    if (!line.empty() && line[line.size()-1] == '\r')
    {
        lineEnd = "\r\n";
    }

    out << "; Processed by OctoPrint-GcodeLeveling " << version << lineEnd << lineEnd;

    do
    {
        // Remove \r if file was CTLF
        if (!line.empty() && line[line.size()-1] == '\r')
        {
            line.erase(line.size()-1);
        }

        parseLine(line, &out, lineEnd, current, next);

        interpolateState(current, next, &out, lineEnd, coeffs, xDeg, yDeg, minZ, maxZ, invertZ);

        *current = *next;
        next->reset();
    }
    while (getline(infile, line));

    delete current;
    delete next;

    return opath;
}

static PyObject *
leveling_level(PyObject *self, PyObject *args)
{
    PyObject *coeffList;

    const char *path, *ver;

    float minZ, maxZ;
    bool invertZ;

    PyObject *logging_message = Py_BuildValue("s", "Before tuple parse");
    Py_XINCREF(logging_message);
    PyObject_CallMethod(logging_object, "debug", "O", logging_message, NULL);
    Py_DECREF(logging_message);

    // ADD THE 2 PARENTHESIS AFTER FINAL VAR (THIS HAS HAPPENED TWICE NOW)
    if (!PyArg_ParseTuple(args, "Oss(ffp)", &coeffList, &path, &ver, &minZ, &maxZ, &invertZ))
        return NULL;
    Py_INCREF(coeffList);

    logging_message = Py_BuildValue("s", "After tuple parse");
    Py_XINCREF(logging_message);
    PyObject_CallMethod(logging_object, "debug", "O", logging_message, NULL);
    Py_DECREF(logging_message);

    // parse through all the coeffs
    coeffList = PySequence_Fast(coeffList, "argument must be iterable");
    if(!coeffList)
        return 0;

    const int numRows = PySequence_Fast_GET_SIZE(coeffList);
    double **coeffs = new double*[numRows];

    PyObject *coeffRow = PySequence_Fast_GET_ITEM(coeffList, 0);
    coeffRow = PySequence_Fast(coeffRow, "argument must be iterable");
    const int numCols = PySequence_Fast_GET_SIZE(coeffRow);

    for (int i = 0; i < numRows; i++)
    {
        PyObject *coeffRow = PySequence_Fast_GET_ITEM(coeffList, i);
        coeffRow = PySequence_Fast(coeffRow, "argument must be iterable");
        coeffs[i] = new double[numCols];

        // Get the coords and convert to pyfloat then c double
        for (int j = 0; j < numCols; j++)
        {
            coeffs[i][j] = PyFloat_AS_DOUBLE(PyNumber_Float(PySequence_Fast_GET_ITEM(coeffRow, j)));
        }
    }

    for (int i = 0; i < numRows; i++)
    {
        for (int j = 0; j < numCols-1; j++)
        {
            std::cout << coeffs[i][j] << ", ";
        }
        std::cout << coeffs[i][numCols-1] << std::endl;
    }

    std::string opath;

    Py_DECREF(coeffList);

    Py_UNBLOCK_THREADS
    debug("Started leveling");

    opath = levelFile(coeffs, numRows, numCols, (std::string) path, (std::string) ver, minZ, maxZ, invertZ);
    debug("Done leveling");

    for (int i = 0; i < numRows; i++)
    {
        delete[] coeffs[i];
    }
    delete[] coeffs;

    Py_BLOCK_THREADS
    return Py_BuildValue("s", opath.c_str());
}

static PyObject *
leveling_fit(PyObject *self, PyObject *args)
{
    PyObject *pointList;

    int xDeg, yDeg;

    PyObject *logging_message = Py_BuildValue("s", "Before tuple parse");
    Py_XINCREF(logging_message);
    PyObject_CallMethod(logging_object, "debug", "O", logging_message, NULL);
    Py_DECREF(logging_message);

    // ADD THE 2 PARENTHESIS AFTER FINAL VAR (THIS HAS HAPPENED TWICE NOW)
    if (!PyArg_ParseTuple(args, "O(ii)", &pointList, &xDeg, &yDeg))
        return NULL;
    Py_INCREF(pointList);

    logging_message = Py_BuildValue("s", "After tuple parse");
    Py_XINCREF(logging_message);
    PyObject_CallMethod(logging_object, "debug", "O", logging_message, NULL);
    Py_DECREF(logging_message);

    // parse through all the shifts
    pointList = PySequence_Fast(pointList, "argument must be iterable");
    if(!pointList)
        return 0;

    const int numPoints = PySequence_Fast_GET_SIZE(pointList);
    double points[numPoints][3];

    for (int i = 0; i < numPoints; i++)
    {
        PyObject *pointSet = PySequence_Fast_GET_ITEM(pointList, i);
        pointSet = PySequence_Fast(pointSet, "argument must be iterable");

        // Get the x then y coord and convert to pyfloat then c double
        for (int j = 0; j < 3; j++)
        {
            points[i][j] = PyFloat_AS_DOUBLE(PyNumber_Float(PySequence_Fast_GET_ITEM(pointSet, j)));
        }
    }

    Py_DECREF(pointList);

    Py_UNBLOCK_THREADS

    debug("Started fitting");
    double **coeffs = fit(points, numPoints, xDeg, yDeg);
    debug("Done fitting");

    // create pylist 2d object
    PyObject *coeffList = PyList_New(xDeg+1);
    PyObject *coeffSet;
    for (int i=0; i<=xDeg; i++)
    {
        coeffSet = PyList_New(yDeg+1);
        for (int j=0; j<=yDeg; j++) {
            PyList_SET_ITEM(coeffSet, j, PyFloat_FromDouble(coeffs[i][j]));
        }
        PyList_SET_ITEM(coeffList, i, coeffSet);
    }

    // delete c double array
    for (int i=0; i<=xDeg; i++) {
        delete[] coeffs[i];
    }
    delete[] coeffs;

    Py_BLOCK_THREADS
    return Py_BuildValue("O", coeffList);
}

static PyObject *
leveling_test(PyObject *self, PyObject *args)
{
    Py_UNBLOCK_THREADS
    char *msg;

    if (!PyArg_ParseTuple(args, "s", &msg))
    {
        return NULL;
    }

    std::string out = "Hello ";

    out += msg;


    debug(out);

    Py_BLOCK_THREADS
    Py_RETURN_NONE;
}

static PyMethodDef LevelingMethods[] = {
    {"level",  leveling_level, METH_VARARGS,
     "Level a gcode file"},
    {"fit",  leveling_fit, METH_VARARGS,
    "fit the poly-model to points"},
    {"test",  leveling_test, METH_VARARGS,
    "Just a test method"},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static struct PyModuleDef levelingmodule = {
    PyModuleDef_HEAD_INIT,
    "leveling",   /* name of module */
    NULL, /* module documentation, may be NULL */
    -1,       /* size of per-interpreter state of the module,
                 or -1 if the module keeps state in global variables. */
    LevelingMethods
};

PyMODINIT_FUNC
PyInit_leveling(void)
{
    logging_library = PyImport_ImportModuleNoBlock("logging");
    logging_object = PyObject_CallMethod(logging_library, "getLogger", "O", Py_BuildValue("s", module_name));
    Py_XINCREF(logging_object);

    return PyModule_Create(&levelingmodule);
}
