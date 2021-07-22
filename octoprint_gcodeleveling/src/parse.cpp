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

struct ParseObject {
    std::ostream *out;
    std::string lineEnd;
    double **coeffs;
    int xDeg, yDeg;
    float minZ, maxZ;
    bool invertZ;
    float maxLine, maxArc;
};

class GcodeState {
public:
    void reset();
    void computeModelHeight(ParseObject *parseOpts);
    bool interpNeeded;

    // We need to know what absolute position the machine is in to level
    // A single absolute command at the start will suffice
    unsigned short int absLock;
    Vector pos, absPos, posOffset, arcCenter;
    // absolutely positioned and leveled Z value
    float absZ;

    float i, j, r, e;
    // Arc mode | -1: disabled | 0: R mode | 1: IJ mode
    short int arcMode;

    double arcAngle;

    std::string extraArgs;

    // Move Mode (e.g. G0/G1 or G2/G3)
    unsigned short int moveMode;
    // Workspace plane | 0: XY | 1: ZX | 2: YZ
    unsigned short int workspacePlane;
    // Positioning mode | 0: relative | 1: absolute
    unsigned short int positioningMode;
    // Extruder mode | -1: disabled | 0: relative | 1: absolute
    short int extruderMode;

    // used for optimization endpoint adjustment
    float modelHeight;

    GcodeState()
    {
        interpNeeded = false;
        absLock = 0;
        arcMode = -1;
        positioningMode = 1;
        extruderMode = -1;
    };
};

void GcodeState::reset()
{
    this->extraArgs = "";
    this->arcMode = -1;
    if (this->positioningMode == 0) {
        this->pos.reset();
    }

    this->i = 0;
    this->j = 0;
    this->r = 0;

    this->arcAngle = 0.0;
    this->arcCenter.reset();

    if (this->extruderMode == 0)
        this->e = 0;
    this->interpNeeded = false;
}

float polyEval(float x, float y, ParseObject *parseOpts)
{
    float z = 0.0;
    for (int i=0; i<parseOpts->xDeg; i++)
    {
        for (int j=0; j<parseOpts->yDeg; j++)
        {
            z += parseOpts->coeffs[i][j]*pow(x, i)*pow(y, j);
        }
    }

    return z;
}

// run when GcodeState is updated to prep for interpolations
void GcodeState::computeModelHeight(ParseObject *parseOpts)
{
    this->modelHeight = polyEval(this->absPos.x, this->absPos.y, parseOpts);
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
                // std::cout << "Z " << next->pos.z << std::endl;
            } else {
                std::cout << f << std::endl;
            }
            break;
            case 'I':
            f = parseFloat(iss);
            if (isnormal(f)) {
                next->arcMode = 1;
                next->i = f;
            }
            break;
            case 'J':
            f = parseFloat(iss);
            if (isnormal(f)) {
                next->arcMode = 1;
                next->j = f;
            }
            break;
            case 'R':
            f = parseFloat(iss);
            if (isnormal(f)) {
                next->arcMode = 0;
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
void parseLine(std::string line, struct ParseObject *parseOpts, GcodeState *current, GcodeState *next)
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

                    *(parseOpts->out) << line << parseOpts->lineEnd;
                }
                else if (num == 91)
                {
                    next->positioningMode = false;
                    *(parseOpts->out) << line << parseOpts->lineEnd;
                }
                else if (num == 90)
                {
                    next->positioningMode = true;
                    *(parseOpts->out) << line << parseOpts->lineEnd;
                }
                else if (num >= 17 && num < 20)
                {
                    next->workspacePlane = num - 17;
                }
                else
                {
                    *(parseOpts->out) << line << parseOpts->lineEnd;
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
                    *(parseOpts->out) << line << parseOpts->lineEnd;
                }
                else if (num == 82)
                {
                    next->extruderMode = true;
                    *(parseOpts->out) << line << parseOpts->lineEnd;
                }
                else
                {
                    *(parseOpts->out) << line << parseOpts->lineEnd;
                }
            }
        }
        else if ((upp >= 'X' && upp <= 'Z') || (upp >= 'I' && upp <= 'J'))
        {
            next->interpNeeded = true;

            iss.clear();
            iss.seekg(0, std::ios::beg);

            parseArgs(&iss, next);
        }
        else
        {
            *(parseOpts->out) << line << parseOpts->lineEnd;
        }
    }
}

// returns correctly relative and offset z value for a gcode state
float evalPoint(GcodeState *current, GcodeState *next, ParseObject *parseOpts)
{
    float absZ = 0.0;
    for (int i=0; i<parseOpts->xDeg; i++)
    {
        for (int j=0; j<parseOpts->yDeg; j++)
        {
            absZ += parseOpts->coeffs[i][j]*pow(next->absPos.x, i)*pow(next->absPos.y, j);
        }
    }

    if (parseOpts->invertZ) {
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

// distance between two gcode states
float dist(GcodeState *current, GcodeState *next)
{
    return distBetweenPoints(&(current->absPos), &(next->absPos));
}

float arc(GcodeState *current, GcodeState *next)
{
    if (next->arcMode == 1)
    {
        next->arcCenter = Vector(current->absPos.x + next->i, current->absPos.y + next->j, (current->absPos.z + next->absPos.z)/2);

        Vector radius(-next->i, -next->j, 0);
        Vector arm(next->absPos.x-next->arcCenter.x, next->absPos.y-next->arcCenter.y, 0);

        double alpha = cross(&radius, &arm).z;
        bool dir = alpha >= 0;

        double beta = acos(dot(&radius, &arm)/radius.magnitude()/arm.magnitude());

        // Determine if the arc takes the long path around
        if (dir ^ (next->moveMode == 3))
        {
            beta = 2*M_PI - beta;
        }

        // Put angle into anti-clockwise degrees
        if (next->moveMode == 2)
        {
            beta *= -1;
        }

        next->arcAngle = beta;

        return beta * radius.magnitude();
    }
    else
    {
        Vector directConnect = next->absPos - current->absPos;

        if (directConnect.magnitude() > 2*next->r)
        {
            // TODO: Send Excessive Radius Error to front end
        }
        else if (directConnect.magnitude() == 0.0)
        {
            // TODO: Send No Radius Error to front end
        }
        else
        {
            int rotModify = 1;
            if (next->moveMode == 2) {
                rotModify = -1;
            }

            Vector q = rotModify*directConnect;
            q.recip();
            q.normalize();
            q.mult(sqrt(next->r*next->r - directConnect.magSqr()/4));

            next->arcCenter = current->absPos + directConnect*0.5 + q;

            Vector radius = current->absPos - next->arcCenter, arm = next->absPos - next->arcCenter;

            next->arcAngle = acos(dot(&radius, &arm)/radius.magnitude()/arm.magnitude()) * rotModify;
            return next->arcAngle * radius.magnitude();
        }
    }
}

// Consider making some of these settings for performance purposes
// or tune to execution time
const float MIN_DER = 0.0001;
const float MIN_DEV = 0.25;
const float TELO = 0.01;
const int STEP_BAIL = 1000;
const float STEP_SCALER = 0.1;
const int NUM_PROBES = 10;

Vector gradient(ParseObject *parseOpts, float x, float y)
{
    Vector grad(0.0, 0.0, 0.0);
    double **coeffs = parseOpts->coeffs;

    for (int i = 0; i < parseOpts->xDeg; i++)
    {
        for (int j = 0; j < parseOpts->yDeg; j++)
        {
            // x comp pass
            if (i > 0)
                grad.x += coeffs[i][j] * i * pow(x, i-1);

            // y comp pass
            if (j > 0)
                grad.y += coeffs[i][j] * j * pow(y, j-1);
        }
    }

    return grad;
}


float lineSqrDistance(float progress, GcodeState *current, GcodeState *next, ParseObject *parseOpts)
{
    Vector heading = next->absPos - current->absPos;
    heading.z = 0.0;
    Vector pos = current->absPos;
    pos.z = 0.0;
    pos.add(heading*progress);

    return pow(polyEval(pos.x, pos.y, parseOpts) - current->modelHeight - (next->modelHeight-current->modelHeight)*progress, 2.0);
}

float lineSqrDerivative(float progress, GcodeState *current, GcodeState *next, ParseObject *parseOpts)
{
    float deltaHeight = next->modelHeight-current->modelHeight;

    Vector heading = next->absPos - current->absPos;
    heading.z = 0.0;
    Vector pos = current->absPos;
    pos.z = 0.0;
    pos.add(heading*progress);

    return 2.0 * (polyEval(pos.x, pos.y, parseOpts) - current->modelHeight - (deltaHeight)*progress) * (dot(gradient(parseOpts, pos.x, pos.y), heading) - deltaHeight);
}

GcodeState * worstLineOffender(GcodeState *current, GcodeState *next, ParseObject *parseOpts)
{
    float maxDev = 0.0, dev, p, maxP;
    for (int probePoint = 0; probePoint < NUM_PROBES; probePoint++)
    {
        p = probePoint / 10.0;
        dev = lineSqrDistance(p, current, next, parseOpts);
        if (dev > maxDev)
        {
            maxDev = dev;
            maxP = p;
        }
    }

    int steps = 0;
    float der, progress = maxP;
    do
    {
        der = lineSqrDerivative(progress, current, next, parseOpts);

        progress += der * STEP_SCALER;
        steps++;
    }
    while (der == MIN_DER && steps < STEP_BAIL && progress > TELO && progress < 1.0 - TELO);

    // Check worst point is far enough from ends AND deviates enough to warrant correction
    if (progress > TELO && progress < 1.0 - TELO && lineSqrDistance(progress, current, next, parseOpts) > MIN_DEV)
    {
        GcodeState *worst = new GcodeState;
        *worst = *next;


        if (next->extruderMode == 0) {
            worst->e = next->e * progress;
            next->e *= (1.0 - progress);
        } else if (next->extruderMode == 1 && next->e != current->e) {
            worst->e = current->e + (next->e - current->e)*progress;
        }

        worst->absPos = current->absPos + (next->absPos - current->absPos)*progress;
        if (next->moveMode == 0) {
            worst->pos = next->pos * progress;
            next->pos.mult(1.0-progress);
        } else {
            worst->pos = worst->absPos - worst->posOffset;
        }

        next->extraArgs = "";

        return worst;
    }
    else
        return NULL;
}

float arcSqrDistance(float progress, GcodeState *current, GcodeState *next, ParseObject *parseOpts)
{
    Vector radius = current->absPos - next->arcCenter;
    // TODO: Check that rotate is going the right direction
    radius.rotate(next->arcAngle);
    Vector pos = next->arcCenter + radius;

    return pow(polyEval(pos.x, pos.y, parseOpts) - current->modelHeight - (next->modelHeight-current->modelHeight)*progress, 2.0);
}

float arcSqrDerivative(float progress, GcodeState *current, GcodeState *next, ParseObject *parseOpts)
{
    float deltaHeight = next->modelHeight-current->modelHeight;

    Vector radius = current->absPos - next->arcCenter;
    // TODO: Check that rotate is going the right direction
    radius.rotate(next->arcAngle);
    Vector pos = next->arcCenter + radius;

    if (next->moveMode == 3)
        radius.rotate(M_PI_4);
    else
        radius.rotate(-M_PI_4);

    Vector heading = radius;

    return 2.0 * (polyEval(pos.x, pos.y, parseOpts) - current->modelHeight - (deltaHeight)*progress) * (dot(gradient(parseOpts, pos.x, pos.y), heading) - deltaHeight);
}

GcodeState * worstArcOffender(GcodeState *current, GcodeState *next, ParseObject *parseOpts)
{
    float maxDev = 0.0, dev, p, maxP;
    for (int probePoint = 0; probePoint < NUM_PROBES; probePoint++)
    {
        p = probePoint / 10.0;
        dev = arcSqrDistance(p, current, next, parseOpts);
        if (dev > maxDev)
        {
            maxDev = dev;
            maxP = p;
        }
    }

    int steps = 0;
    float der, progress = maxP;
    do
    {
        der = arcSqrDerivative(progress, current, next, parseOpts);

        progress += der * STEP_SCALER;
        steps++;
    }
    while (der == MIN_DER && steps < STEP_BAIL && progress > TELO && progress < 1.0 - TELO);

    // Check worst point is far enough from ends AND deviates enough to warrant correction
    if (progress > TELO && progress < 1.0 - TELO && arcSqrDistance(progress, current, next, parseOpts) > MIN_DEV)
    {
        GcodeState *worst = new GcodeState;
        *worst = *next;


        if (next->extruderMode == 0) {
            worst->e = next->e * progress;
            next->e *= (1.0 - progress);
        } else if (next->extruderMode == 1 && next->e != current->e) {
            worst->e = current->e + (next->e - current->e)*progress;
        }

        Vector radius = current->absPos - next->arcCenter;
        radius.rotate(next->arcAngle * progress);
        Vector pos = next->arcCenter + radius;

        worst->absPos = pos;
        if (next->moveMode == 0) {
            worst->pos = pos - current->absPos;
            next->pos = next->absPos - pos;
        } else {
            worst->pos = worst->absPos - worst->posOffset;
        }

        if (next->arcMode == 1)
        {
            next->i = next->arcCenter.x - worst->absPos.x;
            next->j = next->arcCenter.y - worst->absPos.y;
        }

        worst->arcAngle = progress*next->arcAngle;
        next->arcAngle *= (1-progress);

        next->extraArgs = "";

        return worst;
    }
    else
        return NULL;
}

void constructLine(GcodeState *current, GcodeState *next, ParseObject *parseOpts)
{
    *(parseOpts->out) << "G" << next->moveMode;
    if (next->pos.x != current->pos.x)
    *(parseOpts->out) << " X" << next->pos.x;

    if (next->pos.y != current->pos.y)
    *(parseOpts->out) << " Y" << next->pos.y;

    // only send an adjusted z value if we know where absolutely we are
    if (next->absLock == 7) {
        *(parseOpts->out) << " Z" << evalPoint(current, next, parseOpts);
    }

    if (next->extruderMode == 0) {
        *(parseOpts->out) << " E" << next->e;
    } else if (next->extruderMode == 1 && next->e != current->e) {
        *(parseOpts->out) << " E" << next->e;
    }

    *(parseOpts->out) << next->extraArgs << parseOpts->lineEnd;
}

void constructArc(GcodeState *current, GcodeState *next, ParseObject *parseOpts)
{
    *(parseOpts->out) << "G" << next->moveMode;
    if (next->pos.x != current->pos.x)
        *(parseOpts->out) << " X" << next->pos.x;

    if (next->pos.y != current->pos.y)
        *(parseOpts->out) << " Y" << next->pos.y;

    // only send an adjusted z value if we know where absolutely we are
    if (next->absLock == 7) {
        *(parseOpts->out) << " Z" << evalPoint(current, next, parseOpts);
    }

    if (next->arcMode == 0) {
        *(parseOpts->out) << " R" << next->r;
    } else if (next->arcMode == 1) {
        *(parseOpts->out) << " I" << next->i;
        *(parseOpts->out) << " J" << next->j;
    }

    if (next->extruderMode == 0) {
        *(parseOpts->out) << " E" << next->e;
    } else if (next->extruderMode == 1 && next->e != current->e) {
        *(parseOpts->out) << " E" << next->e;
    }

    *(parseOpts->out) << next->extraArgs << parseOpts->lineEnd;
}

// Generates leveled gcode to go between states (possibly subdivided)
void interpolateState(GcodeState *current, GcodeState *next, ParseObject *parseOpts)
{
    if (next->interpNeeded)
    {
        // just write the out value without any movement slicing
        if (next->moveMode < 2)
        {
            if (current->absLock == 7 && next->absLock == 7 && parseOpts->maxLine > 0.0 && dist(current, next) > parseOpts->maxLine)
            {
                // Slice and Dice
                GcodeState *worst = worstLineOffender(current, next, parseOpts);

                if (worst != NULL)
                {
                    worst->computeModelHeight(parseOpts);
                    interpolateState(current, worst, parseOpts);
                    interpolateState(worst, next, parseOpts);

                    delete worst;
                }
                else
                {
                    constructLine(current, next, parseOpts);
                }
            }
            else
            {
                constructLine(current, next, parseOpts);
            }
        }
        else
        {
            if (current->absLock == 7 && next->absLock == 7 && parseOpts->maxArc > 0.0 && arc(current, next) > parseOpts->maxArc)
            {
                // Slice and Dice
                GcodeState *worst = worstArcOffender(current, next, parseOpts);

                if (worst != NULL)
                {
                    worst->computeModelHeight(parseOpts);
                    interpolateState(current, worst, parseOpts);
                    interpolateState(worst, next, parseOpts);

                    delete worst;
                }
                else
                {
                    constructArc(current, next, parseOpts);
                }
            }
            else
            {
                constructArc(current, next, parseOpts);
            }
        }
    }
}

std::string levelFile(std::string inPath, std::string version, struct ParseObject *parseOpts)
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

    parseOpts->lineEnd = "\n";

    // Begin Line Grab loop
    getline(infile, line);

    // determine line ending
    if (!line.empty() && line[line.size()-1] == '\r')
    {
        parseOpts->lineEnd = "\r\n";
    }

    out << "; Processed by OctoPrint-GcodeLeveling " << version << parseOpts->lineEnd << parseOpts->lineEnd;
    parseOpts->out = &out;

    do
    {
        // Remove \r if file was CTLF
        if (!line.empty() && line[line.size()-1] == '\r')
        {
            line.erase(line.size()-1);
        }

        parseLine(line, parseOpts, current, next);

        next->computeModelHeight(parseOpts);

        interpolateState(current, next, parseOpts);

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
    struct ParseObject configOpts;

    const char *path, *ver;

    PyObject *logging_message = Py_BuildValue("s", "Before tuple parse");
    Py_XINCREF(logging_message);
    PyObject_CallMethod(logging_object, "debug", "O", logging_message, NULL);
    Py_DECREF(logging_message);

    // ADD THE 2 PARENTHESIS AFTER FINAL VAR (THIS HAS HAPPENED TWICE NOW)
    if (!PyArg_ParseTuple(args, "Oss(ffpff)", &coeffList, &path, &ver, &configOpts.minZ, &configOpts.maxZ, &configOpts.invertZ, &configOpts.maxLine, &configOpts.maxArc))
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
    configOpts.coeffs = new double*[numRows];

    PyObject *coeffRow = PySequence_Fast_GET_ITEM(coeffList, 0);
    coeffRow = PySequence_Fast(coeffRow, "argument must be iterable");
    const int numCols = PySequence_Fast_GET_SIZE(coeffRow);

    // convert from the python 2D sequence to a C 2d double array
    for (int i = 0; i < numRows; i++)
    {
        PyObject *coeffRow = PySequence_Fast_GET_ITEM(coeffList, i);
        coeffRow = PySequence_Fast(coeffRow, "argument must be iterable");
        configOpts.coeffs[i] = new double[numCols];

        // Get the coords and convert to pyfloat then c double
        for (int j = 0; j < numCols; j++)
        {
            configOpts.coeffs[i][j] = PyFloat_AS_DOUBLE(PyNumber_Float(PySequence_Fast_GET_ITEM(coeffRow, j)));
        }
    }

    // print out the double array
    for (int i = 0; i < numRows; i++)
    {
        for (int j = 0; j < numCols-1; j++)
        {
            std::cout << configOpts.coeffs[i][j] << ", ";
        }
        std::cout << configOpts.coeffs[i][numCols-1] << std::endl;
    }

    std::string opath;

    Py_DECREF(coeffList);

    Py_UNBLOCK_THREADS
    debug("Started leveling");

    configOpts.xDeg = numRows;
    configOpts.yDeg = numCols;

    opath = levelFile((std::string) path, (std::string) ver, &configOpts);
    debug("Done leveling");

    // free the double array once done
    for (int i = 0; i < numRows; i++)
    {
        delete[] configOpts.coeffs[i];
    }
    delete[] configOpts.coeffs;

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
