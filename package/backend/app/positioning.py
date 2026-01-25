"""
Helper functions for positioning and unit conversions
"""

from math import sqrt, cos, sin, acos, atan2, copysign, pi
from micropython import const

POS_ABSOLUTE = const(0x0001)
POS_RELATIVE = const(0x0002)

#################################
# Math helpers                  #
#################################


def cosine_similarity(p0, p1, p2):
    """
    Compute the cosine similary of vectors defined by line segments p0p1, p1p2.
    :param p0 tuple: first coordinate
    :param p1 tuple: second coordinate
    :param p2 tuple: third coordinate
    """
    # first segment vector
    v1 = (p1[0] - p0[0], p1[1] - p0[1])
    # second segment vector
    v2 = (p2[0] - p1[0], p2[1] - p1[1])

    n1 = (v1[0] ** 2 + v1[1] ** 2) ** 0.5
    n2 = (v2[0] ** 2 + v2[1] ** 2) ** 0.5
    if n1 == 0 or n2 == 0:
        return 0.0  # degenerate case (no movement)

    return (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)


def rotate_cartesian(x, y, phi):
    """
    Rotate Cartesian coordinates by phi.
    :param x float: x coordinate
    :param y float: y coordinate
    :param phi float: angle to rotate by (radians)
    :return tuple: polar coordinate
    """
    return (cos(phi) * x - sin(phi) * y, sin(phi) * x + cos(phi) * y)


def convert_to_polar(x, y):
    """
    Convert Cartesian coordinate to polar.
    :param x float: x coordinate
    :param y float: y coordinate
    :return tuple: polar coordinate
    """
    radius = sqrt(x**2 + y**2)
    angle = atan2(y, x)
    return (radius, angle)


def polar_to_cartesian(radius, angle):
    """
    Convert polar coordinate to Cartesian.
    :param radius float: radius
    :param angle float: angle (radians)
    :return tuple: Cartesian coordinate
    """
    return (cos(angle) * radius, sin(angle) * radius)


def convert_to_steps(angle, steps_per_revolution):
    """
    Translate an angle to the number of full steps of a stepper motor.
    :param angle float: angle (degrees)
    :return tuple: polar coordinates
    """
    return int((angle / 360) * steps_per_revolution)


#################################
# Machine type specific helpers #
#################################


def resolve_arm_angles(x, y, primary_p, secondary_p):
    """
    Simple inverse kinematics solver to compute the angles of the primary and secondary arms
    for SCARA type machines in order to move to point (x;y) from the current position.
    :param x float: x coordinate
    :param y float: y coordinate
    :param primary_p tuple: polar coordinates of the primary arm
    :param secondary_p tuple: polar coordinates of the secondary arm
    :return tuple: relative angles (degrees)
    """
    target_p = convert_to_polar(x, y)

    a = 2 * cos(target_p[1]) * cos(primary_p[1]) + 2 * sin(target_p[1]) * sin(
        primary_p[1]
    )
    b = 2 * sin(target_p[1]) * cos(primary_p[1]) - 2 * cos(target_p[1]) * sin(
        primary_p[1]
    )
    c = (primary_p[0] ** 2 - secondary_p[0] ** 2 + target_p[0] ** 2) / (
        target_p[0] * primary_p[0]
    )
    r = sqrt(a**2 + b**2)

    if r == 0:
        raise ValueError("Cannot compute with zero radius!")

    if abs(c / r) > 1:
        # Correcting domain errors for acos
        c = copysign(r, c)

    phi = atan2(b, a)
    angle_1 = phi + acos(c / r) % (2 * pi)
    angle_2 = phi - acos(c / r) % (2 * pi)

    # There are at most two solutions, chose the closest one
    if angle_1 > pi:
        angle_1 = angle_1 - 2 * pi
    if angle_2 > pi:
        angle_2 = angle_2 - 2 * pi
    angle_primary = min([angle_1, angle_2], key=lambda x: abs(x))

    # Calculate secondary arm angle
    a1_abs = primary_p[1] + angle_primary
    d = (cos(target_p[1]) * target_p[0] - cos(a1_abs) * primary_p[0]) / secondary_p[0]
    e = (sin(target_p[1]) * target_p[0] - sin(a1_abs) * primary_p[0]) / secondary_p[0]
    angle_secondary = (
        atan2(-sin(a1_abs) * d + cos(a1_abs) * e, cos(a1_abs) * d + sin(a1_abs) * e)
        - secondary_p[1]
    )
    angle_secondary = angle_secondary % (2 * pi)

    if angle_secondary > pi:
        angle_secondary = angle_secondary - 2 * pi

    return (180 * (angle_primary) / pi, 180 * (angle_secondary) / pi)
