#include <stdio.h>
#include <math.h>
#include <cmath>
#include <iostream>

class Vector
{
    public:
        double x, y, z;
        Vector () {this->x=0;this->y=0;this->z=0;};
        Vector (double x, double y, double z)
        :x(x)
        ,y(y)
        ,z(z)
        {};

        Vector (const Vector* orig) {this->x = orig->x; this->y = orig->y; this->z = orig->z;};

        void setValue (double x, double y, double z) {this->x=x; this->y=y; this->z=z;};

        friend Vector operator+(Vector a, Vector b);
        friend Vector operator-(Vector a, Vector b);
        friend Vector operator*(Vector v, double s);
        friend Vector operator*(double s, Vector v);
        friend std::ostream& operator<<(std::ostream &strm, const Vector &v);

        friend double distBetweenPoints(Vector *a, Vector *b);

        friend double crossVector(Vector *a, Vector *b);

        double magSqr();
        double magnitude();
        void normalize ();
        Vector normalized ();
        void print ();

        void add(const Vector *v);
        void add(const Vector v);
        void sub(const Vector v);
        void mult(double s);

        void reset() {x=0;y=0;z=0;};

        void rotate(double radians);
        void recip();
        bool bothNums();

        friend double dot (Vector *a, Vector *b);
        friend Vector cross (Vector *a, Vector *b);
};

Vector operator+ (Vector a, Vector b)
{
    double x = a.x + b.x, y = a.y + b.y, z = a.z + b.z;

    return Vector(x, y, z);
};

Vector operator- (Vector a, Vector b)
{
    double x = a.x - b.x, y = a.y - b.y, z = a.z - b.z;

    return Vector(x, y, z);
};

Vector operator* (Vector v, double s)
{
    double x = v.x * s, y = v.y * s, z = v.z * s;

    return Vector(x, y, z);
};

Vector operator* (double s, Vector v)
{
    double x = v.x * s, y = v.y * s, z = v.z * s;

    return Vector(x, y, z);
};

void Vector::normalize()
{
    double scaleValue = 1.0/this->magnitude();

    this->mult(scaleValue);
};

Vector Vector::normalized()
{
    Vector q = *this;

    q.normalize();

    return q;
};

void Vector::print()
{
    printf("(x, y, z): %f, %f, %f\n", this->x, this->y, this->z);
};


std::ostream& operator<<(std::ostream &strm, const Vector &v) {
  return strm << "(" << v.x << ", " << v.y << ", " << v.z << ")";
}

double Vector::magSqr()
{
    return pow(this->x, 2.0) + pow(this->y, 2.0) + pow(this->z, 2.0);
};

double Vector::magnitude()
{
    return sqrt(this->magSqr());
};

void Vector::add(const Vector *v)
{
    this->x += v->x;
    this->y += v->y;
    this->z += v->z;
};

void Vector::add(const Vector v)
{
    this->x += v.x;
    this->y += v.y;
    this->z += v.z;
};

void Vector::sub(const Vector v)
{
    this->x -= v.x;
    this->y -= v.y;
    this->z -= v.z;
};

void Vector::mult(double s)
{
    this->x *= s;
    this->y *= s;
    this->z *= s;
};


double distBetweenPoints(Vector *a, Vector *b)
{
    return (*a-*b).magnitude();
};

double dot(Vector a, Vector b)
{
    return a.x * b.x + a.y * b.y + a.z * b.z;
};

double dot(Vector *a, Vector *b)
{
    return a->x * b->x + a->y * b->y + a->z * b->z;
};

double dirComp(Vector dir, Vector *v)
{
    dir.normalize();
    return dot(&dir, v);
};

Vector projectNVector(Vector *normalizedDir, Vector *testing)
{
    return *normalizedDir * dot(normalizedDir, testing);
};

Vector projectVector(Vector dir, Vector *testing)
{
    dir.normalize();
    return dir * dot(&dir, testing);
};

Vector cross(Vector *a, Vector *b)
{
    return Vector(a->y*b->z-a->z*b->y, -a->x*b->z+b->z*b->x, a->x*b->y-a->y*b->x);
};

// Rotate anti-clockwise about Z axis (ignores Z component)
void Vector::rotate(double radians)
{
    double x = this->x*cos(radians) - this->y*sin(radians);
    double y = this->x*sin(radians) + this->y*cos(radians);

    this->x = x;
    this->y = y;
}

// Reciprocate a flat vector (ignores Z component)
void Vector::recip()
{
    double x = -this->y;
    double y = this->x;

    this->x = x;
    this->y = y;
}

bool Vector::bothNums()
{
    return !isnan(x) && !isnan(y);
}
