import sys
import json
import os

from collections import deque
from machine import Pin, PWM
from math import sqrt, cos, sin, acos, atan2, copysign, pi
from micropython import const
from re import compile
from time import time
from uasyncio import run
from uasyncio import sleep as asleep
from utime import ticks_ms, ticks_us

from Common import micro_task, web_endpoint, console, syslog, manage_task
from Web import ServerBusyException

#################################
# Settings                      #
#################################

class Data:
    MACHINE_TYPE_CARTESIAN = const(0x0001)
    MACHINE_TYPE_SCARA = const(0x0002)
    MACHINE_TYPE = MACHINE_TYPE_CARTESIAN

    ##############################
    # SCARA Physical properties
    ##############################
    RADIUS_PRIMARY = 170
    RADIUS_SECONDARY = 107.1

    ##############################
    # Cartesian Physical properties
    ##############################
    MM_PER_REVOLUTION = 64

    ##############################
    # Pins
    ##############################
    PRIMARY_PINS = [4, 21, 20, 10]
    SECONDARY_PINS = [2, 1, 0, 3]
    SERVO_PIN = 7
    PRIMARY_LIMIT_PIN = 6
    SECONDARY_LIMIT_PIN = 5

    ##############################
    # Positioning
    ##############################
    STEPS_PER_REVOLUTION = 2038 #2048

    # Set it between 2ms and 25ms, 2ms for fast operation and 25ms for high torque
    STEP_DELAY_MS_RAPID = 0.7
    STEP_DELAY_MS_LINEAR = 1.5
    STEP_INIT_MS = 5

    PEN_DELAY_MS_INIT = 20
    PEN_DELAY_MS_TARGET = 1
    PEN_ACCELERATION_RATE = 0.25
    MIN_PEN_DUTY = 20
    MAX_PEN_DUTY = 70

    POS_ABSOLUTE = const(0x0001)
    POS_RELATIVE = const(0x0002)
    POSITIONING = POS_ABSOLUTE

    BACKLASH_STEPS_PRIMARY = 15
    BACKLASH_STEPS_SECONDARY = 15

    ACCELERATION_RATE = 0.05    # (0;1], 1 -> faster acceleration

    USER_BOUNDARIES = {'x_min': None, 'y_min': None, 'x_max': None, 'y_max': None}
    GLOBAL_BOUNDARIES = {'x_min': 0, 'y_min': 0, 'x_max': 128, 'y_max': 131.5}
    REJECT_OOB = False # Reject or accept (and constrain) movement commands with target positions out of boundaries

    CURRENT_CS = "G53"
    CS_COORDINATES = {
        "G53": (0,0), # Machine coordinate syste (MCS), must not be changed
        "G54": (0,0), # WCS #1 - Work coordinate system
        "G55": (0,0), # WCS #2
        "G56": (0,0), # WCS #3
        "G57": (0,0), # WCS #4
        "G58": (0,0), # WCS #5
        "G59": (0,0), # WCS #6
        "G59.1": (0,0), # WCS #7
        "G59.2": (0,0), # WCS #8
        "G59.3": (0,0) # WCS #9
    }
    CS_SCALING = 1.0
    TILE_GRID_SIZE = 3
    CURRENT_TILE_IDX = 0

    ##############################
    # Machine state
    ##############################

    # Direction definitions
    DIR_ANTICLOCKWISE = const(0x0000)
    DIR_CLOCKWISE = const(0x0001)
    
    # Direction aliases
    DIR_FORWARD = DIR_ANTICLOCKWISE
    DIR_BACKWARD = DIR_CLOCKWISE
    
    # Machine position (primary)
    DIR_PRIMARY = None
    CURRENT_POS_PRIMARY = 0
    CURRENT_STEP_PRIMARY = 1

    # Machine position (secondary)
    DIR_SECONDARY = None
    CURRENT_POS_SECONDARY = 0
    CURRENT_STEP_SECONDARY = 1

    # Machine control
    ACTIVATED = True
    ACTIVE_TIMEOUT = 35
    PAUSED = False

    ##############################
    # Miscellaneous
    ##############################
    CONTROL_TASK_TAG = 'plotter._gcode_runner'
    FILE_SESSION_TASK_TAG = 'plotter._file_reader'
    MAX_QUEUE_LENGTH = 100
    GCODE_QUEUE = deque((), MAX_QUEUE_LENGTH)
    ADDITIONAL_INFO = []
    USER_DATA_ROOT = "/web/plotter/user_data"


#################################
# Machine type specific getters #
#################################

def get_current_pos():
    """
    Get the current position of the machine depending on the type.
    :return dict: primary, secondary and absolute positions
    """
    if Data.MACHINE_TYPE == Data.MACHINE_TYPE_SCARA:
        primary_polar = get_primary_polar()
        secondary_polar = get_secondary_polar()
        primary_pos = polar_to_cartesian(primary_polar[0], primary_polar[1])
        secondary_pos = polar_to_cartesian(secondary_polar[0], secondary_polar[1])
        secondary_pos_rot = rotate_cartesian(secondary_pos[0], secondary_pos[1], primary_polar[1])
        return {'sum': (primary_pos[0] + secondary_pos_rot[0], primary_pos[1] + secondary_pos_rot[1]),
                'primary arm': primary_pos,
                'secondary arm': secondary_pos_rot}
    
    elif Data.MACHINE_TYPE == Data.MACHINE_TYPE_CARTESIAN:
        primary_cartesian = get_primary_cartesian()
        secondary_cartesian = get_secondary_cartesian()
        return {'sum': (primary_cartesian, secondary_cartesian),
                'x': primary_cartesian,
                'y': secondary_cartesian}


def get_primary_polar():
    """
    Get the polar coordinates corresponding to the primary arm for SCARA machines.
    :return tuple: polar coordinate
    """
    return (Data.RADIUS_PRIMARY,pi*360*(Data.CURRENT_POS_PRIMARY/Data.STEPS_PER_REVOLUTION)/180)


def get_secondary_polar():
    """
    Get the polar coordinates corresponding to the secondary arm for SCARA machines.
    :return tuple: polar coordinate
    """
    return (Data.RADIUS_SECONDARY,pi*360*(Data.CURRENT_POS_SECONDARY/Data.STEPS_PER_REVOLUTION)/180)


def get_primary_cartesian():
    """
    Get the cartesian coordinates corresponding to the primary axis for cartesian machines.
    :return tuple: cartesian coordinate
    """
    return (Data.CURRENT_POS_PRIMARY/Data.STEPS_PER_REVOLUTION)*Data.MM_PER_REVOLUTION


def get_secondary_cartesian():
    """
    Get the cartesian coordinates corresponding to the secondary axis for cartesian machines.
    :return tuple: cartesian coordinate
    """
    return (Data.CURRENT_POS_SECONDARY/Data.STEPS_PER_REVOLUTION)*Data.MM_PER_REVOLUTION


#################################
# Helpers                       #
#################################

class LimitSwitchException(Exception):
    pass

def rotate_cartesian(x,y,phi):
    """
    Rotate Cartesian coordinates by phi.
    :param x float: x coordinate
    :param y float: y coordinate
    :param phi float: angle to rotate by (radians)
    :return tuple: polar coordinate
    """
    return (cos(phi) * x - sin(phi) * y, sin(phi) * x + cos (phi) * y)


def convert_to_polar(x, y):
    """
    Convert Cartesian coordinate to polar.
    :param x float: x coordinate
    :param y float: y coordinate
    :return tuple: polar coordinate
    """
    radius = sqrt(x**2 + y**2)
    angle = atan2(y,x)
    return (radius, angle)


def polar_to_cartesian(radius, angle):
    """
    Convert polar coordinate to Cartesian.
    :param radius float: radius
    :param angle float: angle (radians)
    :return tuple: Cartesian coordinate
    """
    return (cos(angle)*radius, sin(angle)*radius)


def convert_to_steps(angle):
    """
    Translate an angle to the number of full steps of a stepper motor.
    :param angle float: angle
    :return tuple: polar coordinates
    """
    return int((angle/360) * Data.STEPS_PER_REVOLUTION)


def resolve_arm_angles(x,y):
    """
    Simple inverse kinematics solver to compute the angles of the primary and secondary arms
    for SCARA type machines in order to move to point (x;y) from the current position.
    :param x float: x coordinate
    :param y float: y coordinate
    :return tuple: relative angles (degrees) 
    """
    target_p = convert_to_polar(x,y)
    primary_p = get_primary_polar()
    secondary_p = get_secondary_polar()

    a = 2*cos(target_p[1])*cos(primary_p[1]) + 2*sin(target_p[1])*sin(primary_p[1])
    b = 2*sin(target_p[1])*cos(primary_p[1]) - 2*cos(target_p[1])*sin(primary_p[1])
    c = (primary_p[0]**2 - secondary_p[0]**2 + target_p[0]**2) / (target_p[0] * primary_p[0])
    R = sqrt(a**2 + b**2)
    
    if R == 0:
        raise ValueError("Cannot compute with zero radius!")

    if abs(c/R) > 1:
        # Correcting domain errors for acos
        c = copysign(R, c)

    phi = atan2(b,a)
    angle_1 = phi + acos(c / R) % (2*pi)
    angle_2 = phi - acos(c / R) % (2*pi)

    # There are at most two solutions, chose the closest one
    if angle_1 > pi:
        angle_1 = angle_1 - 2*pi
    if angle_2 > pi:
        angle_2 = angle_2 - 2*pi
    angle_primary = min([angle_1 , angle_2], key=lambda x: abs(x))

    # Calculate secondary arm angle
    a1_abs = primary_p[1] + angle_primary
    d = (cos(target_p[1])*target_p[0] - cos(a1_abs)*primary_p[0])/secondary_p[0]
    e = (sin(target_p[1])*target_p[0] - sin(a1_abs)*primary_p[0])/secondary_p[0]
    angle_secondary = atan2(-sin(a1_abs)*d + cos(a1_abs)*e, cos(a1_abs)*d + sin(a1_abs)*e) - secondary_p[1]
    angle_secondary = angle_secondary % (2*pi)

    if angle_secondary > pi:
        angle_secondary = angle_secondary - 2*pi

    return (180*(angle_primary)/pi, 180*(angle_secondary)/pi)


def get_step_differential(x,y):
    """
    Determine the number of steps per each motor to move from the current position to (x;y), depending on the machine type.
    :param x float: target position on the x axis
    :param y float: target position on the y axis
    :return status dict: primary and secondary limit switch status
    """
    if Data.MACHINE_TYPE == Data.MACHINE_TYPE_SCARA:
        angle_primary, angle_secondary = resolve_arm_angles(x, y)

        diff_steps_primary = convert_to_steps(angle_primary)
        diff_steps_secondary = convert_to_steps(angle_secondary)
        
    if Data.MACHINE_TYPE == Data.MACHINE_TYPE_CARTESIAN:
        diff_steps_primary = int(((x - get_primary_cartesian()) / Data.MM_PER_REVOLUTION) * Data.STEPS_PER_REVOLUTION)
        diff_steps_secondary = int(((y - get_secondary_cartesian()) / Data.MM_PER_REVOLUTION) * Data.STEPS_PER_REVOLUTION)

    return diff_steps_primary, diff_steps_secondary

class speed_controller:
    def __init__(self, target_delay_ms, init_delay_ms, acceleration_rate):
        if not (0 < acceleration_rate <= 1):
            raise ValueError(f'invalid acceleration rate: {acceleration_rate} (must be between zero and one)')
        if init_delay_ms <= target_delay_ms:
            raise ValueError('invalid values for acceleration profile: init_delay_ms must be higher than target_delay_ms')

        self.init_delay_ms = init_delay_ms
        self.target_delay_ms = target_delay_ms
        self.current_delay_ms = init_delay_ms
        self.previous_delay_ms = None
        self.acceleration_rate = acceleration_rate
        self.acceleration_step_ms = (init_delay_ms - target_delay_ms) * acceleration_rate
        self.accelerate = True
        self.decelerate = False
        self.last_step_us = None
        self._running = False

    def __enter__(self):
        self._running = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._running = False

    def _recalculate_acceleration_step_ms(self):
        new_acceleration_step_ms = (self.init_delay_ms - self.target_delay_ms) * self.acceleration_rate
        if new_acceleration_step_ms <= 0:
            raise ValueError(f"Invalid acceleration delay calculated: " +
                              f"init:{self.init_delay_ms}, " +
                              f"target: {self.target_delay_ms}, " +
                              f"acceleration_rate: {self.acceleration_rate}")
        self.acceleration_step_ms = new_acceleration_step_ms

    def update(self, init_delay_ms = None, target_delay_ms = None, acceleration_rate = None):
        if init_delay_ms:
            self.init_delay_ms = init_delay_ms
        if target_delay_ms:
            self.target_delay_ms = target_delay_ms
        if acceleration_rate:
            self.acceleration_rate = acceleration_rate
        self._recalculate_acceleration_step_ms()

    @property
    def delay_ms(self):
        """Current delay in ms."""
        return self.current_delay_ms

    def update_speed(self, remaining_steps=float('inf'), junction_factor=1.0):
        """
        Update current delay based on remaining steps and per-axis junction factor.

        remaining_steps: steps left to complete move (float('inf') if continuous)
        junction_factor: 0–1, 1 = full speed, 0 = must stop
        """

        # Clamp junction factor
        junction_factor = max(0.0, min(junction_factor, 1.0))
        junction_delay_ms = self.target_delay_ms + (self.init_delay_ms - self.target_delay_ms) * (1.0 - junction_factor)

        # Decelerate
        if self.current_delay_ms < self.target_delay_ms or \
           (junction_delay_ms - self.current_delay_ms) / self.acceleration_step_ms >= remaining_steps:
            self.current_delay_ms = min(self.current_delay_ms + self.acceleration_step_ms, junction_delay_ms)

        # Accelerate
        elif self.current_delay_ms > self.target_delay_ms:
            self.current_delay_ms = max(self.current_delay_ms - self.acceleration_step_ms, self.target_delay_ms)


    async def control(self):
        """Sleep according to current delay and update speed."""
        delay_override = self.current_delay_ms

        if self.last_step_us is not None:
            delay_mismatch_prev = (ticks_us() - self.last_step_us)*1000 - self.previous_delay_ms
            if delay_mismatch_prev > 0:
                delay_override -= delay_mismatch_prev
                if delay_override < 0:
                    syslog(f'[WARN] plotter: negative timing {delay_override}ms')
                delay_override = max(delay_override, 0)

        self.last_step = ticks_us()

        self.previous_delay_ms = self.current_delay_ms
        await asleep(delay_override/1000)


primary_speed_controller = speed_controller(Data.STEP_DELAY_MS_RAPID, Data.STEP_INIT_MS, Data.ACCELERATION_RATE)
secondary_speed_controller = speed_controller(Data.STEP_DELAY_MS_RAPID, Data.STEP_INIT_MS, Data.ACCELERATION_RATE)


###########################
# Stepper motor functions #
###########################

def deactivate():
    """
    Deactivate the coils of the stepper motors.
    """
    for i in range(len(Data.PRIMARY_PINS)):
        Data.PRIMARY_PINS[i].value(int('{0:04b}'.format(0)[-i-1]))

    for i in range(len(Data.SECONDARY_PINS)):
        Data.SECONDARY_PINS[i].value(int('{0:04b}'.format(0)[-i-1]))
    Data.ACTIVATED = False


def activate():
    """
    Activate the coils of the stepper motors to maintain the current position.
    """
    for i in range(len(Data.PRIMARY_PINS)):
        Data.PRIMARY_PINS[i].value(int('{0:04b}'.format(Data.CURRENT_STEP_PRIMARY)[-i-1]))

    for i in range(len(Data.SECONDARY_PINS)):
        Data.SECONDARY_PINS[i].value(int('{0:04b}'.format(Data.CURRENT_STEP_SECONDARY)[-i-1]))
    Data.ACTIVATED = True


def is_active():
    """
    Returns if stepper motors are activated.
    :return activated boolean: current state
    """
    return Data.ACTIVATED


async def step_primary(is_backward=False):
    """
    Move the stepper motor of the primary arm while
    adjusting for preconfigured backlash.
    :param is_backward boolean: go backwards
    """

    # Backlash correction
    if Data.BACKLASH_STEPS_PRIMARY and is_backward and Data.DIR_PRIMARY == Data.DIR_FORWARD:
        for i in range(Data.BACKLASH_STEPS_PRIMARY):
            Data.CURRENT_STEP_PRIMARY = int(Data.CURRENT_STEP_PRIMARY/2) if Data.CURRENT_STEP_PRIMARY > 1 else (2**(len(Data.PRIMARY_PINS)-1))
            if Data.CURRENT_STEP_PRIMARY == 2**len(Data.PRIMARY_PINS):
                Data.CURRENT_STEP_PRIMARY  = 1
            for i in range(len(Data.PRIMARY_PINS)):
                Data.PRIMARY_PINS[i].value(int('{0:04b}'.format(Data.CURRENT_STEP_PRIMARY)[-i-1]))
            await asleep(Data.STEP_DELAY_MS_RAPID/1000)

    if Data.BACKLASH_STEPS_PRIMARY and not is_backward and Data.DIR_PRIMARY == Data.DIR_BACKWARD:
        for i in range(Data.BACKLASH_STEPS_PRIMARY):
            Data.CURRENT_STEP_PRIMARY *= 2
            if Data.CURRENT_STEP_PRIMARY == 2**len(Data.PRIMARY_PINS):
                Data.CURRENT_STEP_PRIMARY  = 1
            for i in range(len(Data.PRIMARY_PINS)):
                Data.PRIMARY_PINS[i].value(int('{0:04b}'.format(Data.CURRENT_STEP_PRIMARY)[-i-1]))
            await asleep(Data.STEP_DELAY_MS_RAPID/1000)
    
    Data.DIR_PRIMARY = is_backward

    # Regular stepping
    if is_backward:
        Data.CURRENT_STEP_PRIMARY = int(Data.CURRENT_STEP_PRIMARY/2) if Data.CURRENT_STEP_PRIMARY > 1 else (2**(len(Data.PRIMARY_PINS)-1))
        Data.CURRENT_POS_PRIMARY -= 1
    else:
        Data.CURRENT_STEP_PRIMARY *= 2
        Data.CURRENT_POS_PRIMARY += 1
    
    if Data.CURRENT_STEP_PRIMARY == 2**len(Data.PRIMARY_PINS):
        Data.CURRENT_STEP_PRIMARY  = 1

    for i in range(len(Data.PRIMARY_PINS)):
        Data.PRIMARY_PINS[i].value(int('{0:04b}'.format(Data.CURRENT_STEP_PRIMARY)[-i-1]))


async def step_secondary(is_backward=False):
    """
    Move the stepper motor of the secondary arm while
    adjusting for preconfigured backlash.
    :param delay_ms int: delay between consecutive steps
    :param is_backward boolean: go backwards
    """

    # Backlash correction
    if Data.BACKLASH_STEPS_SECONDARY and is_backward and Data.DIR_SECONDARY == Data.DIR_FORWARD:
        for i in range(Data.BACKLASH_STEPS_SECONDARY):
            Data.CURRENT_STEP_SECONDARY = int(Data.CURRENT_STEP_SECONDARY/2) if Data.CURRENT_STEP_SECONDARY > 1 else (2**(len(Data.SECONDARY_PINS)-1))
            if Data.CURRENT_STEP_SECONDARY == 2**len(Data.SECONDARY_PINS):
                Data.CURRENT_STEP_SECONDARY  = 1
            for i in range(len(Data.SECONDARY_PINS)):
                Data.SECONDARY_PINS[i].value(int('{0:04b}'.format(Data.CURRENT_STEP_SECONDARY)[-i-1]))
            await asleep(Data.STEP_DELAY_MS_RAPID/1000)

    if Data.BACKLASH_STEPS_SECONDARY and not is_backward and Data.DIR_SECONDARY == Data.DIR_BACKWARD:
        for i in range(Data.BACKLASH_STEPS_SECONDARY):
            Data.CURRENT_STEP_SECONDARY *= 2
            if Data.CURRENT_STEP_SECONDARY == 2**len(Data.SECONDARY_PINS):
                Data.CURRENT_STEP_SECONDARY  = 1
            for i in range(len(Data.SECONDARY_PINS)):
                Data.SECONDARY_PINS[i].value(int('{0:04b}'.format(Data.CURRENT_STEP_SECONDARY)[-i-1]))
            await asleep(Data.STEP_DELAY_MS_RAPID/1000)

    Data.DIR_SECONDARY = is_backward

    # Regular stepping
    if is_backward:
        Data.CURRENT_STEP_SECONDARY = int(Data.CURRENT_STEP_SECONDARY/2) if Data.CURRENT_STEP_SECONDARY > 1 else (2**(len(Data.SECONDARY_PINS)-1))
        Data.CURRENT_POS_SECONDARY -= 1
    else:
        Data.CURRENT_STEP_SECONDARY *= 2
        Data.CURRENT_POS_SECONDARY += 1

    if Data.CURRENT_STEP_SECONDARY == 2**len(Data.SECONDARY_PINS):
        Data.CURRENT_STEP_SECONDARY  = 1

    for i in range(len(Data.SECONDARY_PINS)):
        Data.SECONDARY_PINS[i].value(int('{0:04b}'.format(Data.CURRENT_STEP_SECONDARY)[-i-1]))


#####################
# Plotter functions #
#####################

def is_paused():
    """
    Returns if G-code execution is paused.
    :return paused boolean: current state
    """
    return Data.PAUSED


def absolute_positioning(enabled = None):
    """
    Get/set absolute positioning mode (G90).
    :param enabled boolean: turn on/off absolute positioning
    :return enabled boolean: absolute positioning enabled
    """
    if enabled is None:
        return Data.POSITIONING == Data.POS_ABSOLUTE
    if enabled:
        Data.POSITIONING = Data.POS_ABSOLUTE
    else:
        Data.POSITIONING = Data.POS_RELATIVE
    console(f'Absolute positioning: {enabled}')
    return enabled


def relative_positioning(enabled = None):
    """
    Get/set relative positioning mode (G91).
    :param enabled boolean: turn on/off absolute positioning
    :return enabled boolean: absolute positioning enabled
    """
    if enabled is None:
        return Data.POSITIONING == Data.POS_RELATIVE
    if enabled:
        Data.POSITIONING = Data.POS_RELATIVE
    else:
        Data.POSITIONING = Data.POS_ABSOLUTE
    console(f'Relative positioning: {enabled}')
    return enabled


async def position_pen(target):
    if target not in range(0,101):
        raise ValueError(f'invalid target position: {target}')
    
    target_duty = int(Data.MIN_PEN_DUTY + (Data.MAX_PEN_DUTY - Data.MIN_PEN_DUTY) * (target)/100)
    current_duty = Data.SERVO_PIN.duty()

    if current_duty == target_duty:
        return

    with speed_controller(Data.PEN_DELAY_MS_TARGET, Data.PEN_DELAY_MS_INIT, Data.PEN_ACCELERATION_RATE) as ctrl:
        if current_duty < target_duty:
            for duty in range(current_duty, target_duty + 1, 1):
                Data.SERVO_PIN.duty(duty)
                ctrl.update_speed(target_duty - duty)
                await ctrl.control()
        else:
            for duty in range(current_duty, target_duty - 1, -1):
                Data.SERVO_PIN.duty(duty)
                ctrl.update_speed(target_duty - duty)
                await ctrl.control()


async def raise_pen():
    """
    Raise plotter pen.
    """
    await position_pen(100)


async def prepare_pen():
    """
    Raise the pen holder to a position, where the pen can be mounted.
    """
    await position_pen(50)


async def lower_pen():
    """
    Lower plotter pen smoothly.
    """
    await position_pen(0)


def is_primary_limit():
    """
    Check if primary limit switch is reached.
    :return reached boolean: primary limit switch reached
    """
    return Data.PRIMARY_LIMIT_PIN.value() == 1


def is_primary_home():
    """
    Check if primary limit switch is reached at home position.
    :return reached boolean: primary limit switch reached at home
    """
    return Data.PRIMARY_LIMIT_PIN.value() == 1 and Data.DIR_PRIMARY == Data.DIR_BACKWARD


def is_secondary_limit():
    """
    Check if secondary limit switch is reached.
    :return reached boolean: secondary limit switch reached
    """
    return Data.SECONDARY_LIMIT_PIN.value() == 1


def is_secondary_home():
    """
    Check if secondary limit switch is reached at home position.
    :return reached boolean: secondary limit switch reached at home
    """
    return Data.SECONDARY_LIMIT_PIN.value() == 1 and Data.DIR_SECONDARY == Data.DIR_BACKWARD


def limit_status():
    """
    Return current limit switch status.
    :return status dict: primary and secondary limit switch status
    """
    return {'limit primary': is_primary_limit(), 'limit secondary': is_secondary_limit()}


def set_user_boundaries(x_min, y_min, x_max, y_max):
    """
    Set boundaries specified by the user.
    :param x_min float:
    :param y_min float:
    :param x_max float:
    :param y_max float:
    """
    if x_min < Data.GLOBAL_BOUNDARIES['x_min'] or \
       y_min < Data.GLOBAL_BOUNDARIES['y_min'] or \
       x_max > Data.GLOBAL_BOUNDARIES['x_max'] or \
       y_max > Data.GLOBAL_BOUNDARIES['y_max']:
        raise ValueError(f"boundary [{x_min}, {y_min}], [{x_max}, {y_max}] is out of globals bounds" + \
                         f" [{Data.GLOBAL_BOUNDARIES['x_min']}, {Data.GLOBAL_BOUNDARIES['y_min']}]" + \
                         f" [{Data.GLOBAL_BOUNDARIES['x_max']}, {Data.GLOBAL_BOUNDARIES['y_max']}]")

    Data.USER_BOUNDARIES['x_min'] = x_min
    Data.USER_BOUNDARIES['y_min'] = y_min
    Data.USER_BOUNDARIES['x_max'] = x_max
    Data.USER_BOUNDARIES['y_max'] = y_max


def cosine_similarity(p0, p1, p2):
    # first segment vector
    v1 = (p1[0] - p0[0], p1[1] - p0[1])
    # second segment vector
    v2 = (p2[0] - p1[0], p2[1] - p1[1])

    n1 = (v1[0]**2 + v1[1]**2) ** 0.5
    n2 = (v2[0]**2 + v2[1]**2) ** 0.5
    if n1 == 0 or n2 == 0:
        return 0.0  # degenerate case (no movement)

    return (v1[0]*v2[0] + v1[1]*v2[1]) / (n1 * n2)


async def move_to(x, y,
                  target_delay_ms=Data.STEP_DELAY_MS_RAPID,
                  init_delay_ms=Data.STEP_INIT_MS,
                  acceleration_rate=Data.ACCELERATION_RATE,
                  junction_factor=0.0,
                  safe=True):
    """
    Change the current position of the machine, while respecting predefined boundaries.
    Uses Bresenham's algorithm for efficient stepping (integer-only).
    """

    # --- Boundary checks ---
    out_of_global_boundaries = (
        x < Data.GLOBAL_BOUNDARIES['x_min'] or
        y < Data.GLOBAL_BOUNDARIES['y_min'] or
        x > Data.GLOBAL_BOUNDARIES['x_max'] or
        y > Data.GLOBAL_BOUNDARIES['y_max']
    )

    out_of_user_boundaries = (
        None not in Data.USER_BOUNDARIES.values() and
        (x < Data.USER_BOUNDARIES['x_min'] or
         y < Data.USER_BOUNDARIES['y_min'] or
         x > Data.USER_BOUNDARIES['x_max'] or
         y > Data.USER_BOUNDARIES['y_max'])
    )

    if safe and (out_of_global_boundaries or out_of_user_boundaries):
        if Data.REJECT_OOB:
            raise ValueError(f'position out of boundary: ({x},{y})')
        else:
            # Clamp to valid boundaries
            if None not in Data.USER_BOUNDARIES.values():
                x = max(Data.USER_BOUNDARIES["x_min"], min(Data.USER_BOUNDARIES["x_max"], x))
                y = max(Data.USER_BOUNDARIES["y_min"], min(Data.USER_BOUNDARIES["y_max"], y))
            else:
                x = max(Data.GLOBAL_BOUNDARIES["x_min"], min(Data.GLOBAL_BOUNDARIES["x_max"], x))
                y = max(Data.GLOBAL_BOUNDARIES["y_min"], min(Data.GLOBAL_BOUNDARIES["y_max"], y))

    # --- Step differentials ---
    dx, dy = get_step_differential(x, y)
    if not dx and not dy:
        return  # No movement needed

    sx = -1 if dx < 0 else 1
    sy = -1 if dy < 0 else 1
    dx = abs(dx)
    dy = abs(dy)

    # --- Bresenham setup ---
    err = dx - dy
    remaining_x, remaining_y = dx, dy
    x_dominant = dx >= dy  # precompute which axis drives timing

    # --- Speed controllers ---
    with primary_speed_controller as pc, secondary_speed_controller as sc:
        pc.update(init_delay_ms, target_delay_ms, acceleration_rate)
        sc.update(init_delay_ms, target_delay_ms, acceleration_rate)

        while remaining_x > 0 or remaining_y > 0:
            if safe and (is_primary_limit() or is_secondary_limit()):
                raise LimitSwitchException('limit switch triggered')

            e2 = 2 * err

            # Step X
            if e2 > -dy and remaining_x > 0:
                await step_primary(sx < 0)
                remaining_x -= 1
                err -= dy

            # Step Y
            if e2 < dx and remaining_y > 0:
                await step_secondary(sy < 0)
                remaining_y -= 1
                err += dx

            # --- Speed update (both axes) ---
            pc.update_speed(remaining_x, junction_factor)
            sc.update_speed(remaining_y, junction_factor)

            # --- Only dominant axis controls timing ---
            if x_dominant:
                await pc.control()
            else:
                await sc.control()


async def home_cycle():
    """
    Homing routine to find x=0, y=0 based on limit switches.
    """ 
    await raise_pen()

    if True in limit_status().values():
        raise LimitSwitchException("limit switch hit before homing cycle")
    
    # Hit limits
    with speed_controller(Data.STEP_DELAY_MS_LINEAR, Data.STEP_INIT_MS, Data.ACCELERATION_RATE) as ctrl:
        while not is_primary_home() or not is_secondary_home():

            if not is_primary_home():
                await step_primary(Data.DIR_BACKWARD)

            if not is_secondary_home():
                await step_secondary(Data.DIR_BACKWARD)

            ctrl.update_speed()
            await ctrl.control()

    
    # Add slight offset to untrigger limit switches
    with speed_controller(Data.STEP_DELAY_MS_LINEAR, Data.STEP_INIT_MS, Data.ACCELERATION_RATE) as ctrl:
        offset_steps = 0
        while is_primary_limit() or is_secondary_limit():

            if offset_steps > Data.STEPS_PER_REVOLUTION:
                raise ValueError("limit switch error, cannot untrigger")

            if is_primary_limit():
                await step_primary(Data.DIR_FORWARD)

            if is_secondary_limit():
                await step_secondary(Data.DIR_FORWARD)

            offset_steps += 1
            ctrl.update_speed()
            await ctrl.control()

    Data.CURRENT_POS_PRIMARY = 0
    Data.CURRENT_POS_SECONDARY = 0


async def _measure_step_loss(delay_ms = Data.STEP_DELAY_MS_RAPID):
    """
    Test function to check how many steps are lost at a given speed.
    :param delay_ms int: step delay in microseconds
    """ 
    measure_offset_mm = Data.MM_PER_REVOLUTION
    expected_steps = Data.STEPS_PER_REVOLUTION
    await home_cycle()
    await move_to(measure_offset_mm, measure_offset_mm,
                  Data.STEP_DELAY_MS_LINEAR,
                  Data.STEP_DELAY_MS_LINEAR*2,
                  safe=False)

    actual_steps_primary = 0

    with speed_controller(delay_ms, Data.STEP_INIT_MS, Data.ACCELERATION_RATE) as ctrl:
        while not is_primary_home():
            await step_primary(Data.DIR_BACKWARD)
            ctrl.update_speed()
            await ctrl.control()
            actual_steps_primary += 1

    if actual_steps_primary != expected_steps:
        print(f"mismatch in expected vs measured steps during travel in primary axis: " + \
              f"{expected_steps} != {actual_steps_primary} (measured)")
        
    Data.ADDITIONAL_INFO.append(f"{time()}: measured steps in primary axis: {actual_steps_primary} (expected: {expected_steps})")

    actual_steps_secondary = 0

    with speed_controller(delay_ms, Data.STEP_INIT_MS, Data.ACCELERATION_RATE) as ctrl:
        while not is_secondary_home():
            await step_secondary(Data.DIR_BACKWARD)
            ctrl.update_speed()
            await ctrl.control()
            actual_steps_secondary += 1

    if actual_steps_secondary != expected_steps:
        print(f"mismatch in expected vs measured steps during travel in secondary axis: " + \
              f"{expected_steps} != {actual_steps_secondary} (measured)")
        
    Data.ADDITIONAL_INFO.append(f"{time()}: measured steps in secondary axis: {actual_steps_primary} (expected: {expected_steps})")
    
    # Move backwards to untrigger the limit switches
    with speed_controller(Data.STEP_DELAY_MS_LINEAR, Data.STEP_INIT_MS, Data.ACCELERATION_RATE) as ctrl:
        while is_primary_limit() or is_secondary_limit():

            if is_primary_limit():
                await step_primary(Data.DIR_FORWARD)

            if is_secondary_limit():
                await step_secondary(Data.DIR_FORWARD)

            ctrl.update_speed()
            await ctrl.control()
    await home_cycle()
    

async def _measure_workspace():
    """
    Measure the size of usable workspace, and adjust global boundaries.
    :param delay_ms int: step delay in microseconds
    """ 
    await home_cycle()
    await move_to(Data.MM_PER_REVOLUTION, Data.MM_PER_REVOLUTION, Data.STEP_DELAY_MS_LINEAR, Data.STEP_INIT_MS)

    actual_steps_primary = Data.STEPS_PER_REVOLUTION
    actual_steps_secondary = Data.STEPS_PER_REVOLUTION

    with speed_controller(Data.STEP_DELAY_MS_LINEAR, Data.STEP_INIT_MS, Data.ACCELERATION_RATE) as ctrl:
        while not is_primary_limit() or not is_secondary_limit():

            if not is_primary_limit():
                await step_primary(Data.DIR_FORWARD)
                actual_steps_primary += 1

            if not is_secondary_limit():
                await step_secondary(Data.DIR_FORWARD)
                actual_steps_secondary += 1

            ctrl.update_speed()
            await ctrl.control()

    # Move backwards to untrigger the limit switches
    with speed_controller(Data.STEP_DELAY_MS_LINEAR, Data.STEP_INIT_MS, Data.ACCELERATION_RATE) as ctrl:
        while is_primary_limit() or is_secondary_limit():

            if is_primary_limit():
                await step_primary(Data.DIR_BACKWARD)
                actual_steps_primary -= 1

            if is_secondary_limit():
                await step_secondary(Data.DIR_BACKWARD)
                actual_steps_secondary -= 1

            ctrl.update_speed()
            await ctrl.control()

    primary_dimension = (actual_steps_primary / Data.STEPS_PER_REVOLUTION) * Data.MM_PER_REVOLUTION
    print(f"primary dimension [mm]: {primary_dimension}")

    secondary_dimension = (actual_steps_secondary / Data.STEPS_PER_REVOLUTION) * Data.MM_PER_REVOLUTION
    print(f"secondary dimension [mm]: {secondary_dimension}")

    Data.GLOBAL_BOUNDARIES["x_max"] = primary_dimension
    Data.GLOBAL_BOUNDARIES["y_max"] = secondary_dimension

    Data.ADDITIONAL_INFO.append(f"{time()}: measured workspace dimension in primary axis: {primary_dimension}mm")
    Data.ADDITIONAL_INFO.append(f"{time()}: measured workspace dimension in secondary axis: {secondary_dimension}mm")

    await move_to(primary_dimension/2, secondary_dimension/2)


async def _measure_feedrate(delays_ms = [Data.STEP_DELAY_MS_RAPID, Data.STEP_DELAY_MS_LINEAR]):
    """
    Measure the size of usable workspace, and adjust global boundaries.
    :param delay_ms int: step delay in microseconds
    """ 

    for delay_ms in delays_ms:
        await home_cycle()
        
        # Primary
        current_time = ticks_ms()
        await move_to(Data.GLOBAL_BOUNDARIES["x_max"], 0, delay_ms, delay_ms*2)
        end_time = ticks_ms()
        Data.ADDITIONAL_INFO.append(f"{time()}: primary feedrate at {delay_ms}ms step delay: {1000*Data.GLOBAL_BOUNDARIES["x_max"]/(end_time-current_time)}mm/s")

        # Secondary
        current_time = ticks_ms()
        await move_to(Data.GLOBAL_BOUNDARIES["x_max"], Data.GLOBAL_BOUNDARIES["y_max"], delay_ms, delay_ms*2)
        end_time = ticks_ms()
        Data.ADDITIONAL_INFO.append(f"{time()}: secondary feedrate at {delay_ms}ms step delay: {1000*Data.GLOBAL_BOUNDARIES["x_max"]/(end_time-current_time)}mm/s")
    home_cycle()


async def _unblock_limit(axis, direction):
    if not is_primary_limit() and not is_secondary_limit():
        return

    await raise_pen()

    axis = axis.lower()
    current_pos_x = get_current_pos()['sum'][0]
    current_pos_y = get_current_pos()['sum'][1]
    offset = 1.5 if direction == '+' else -1.5

    if axis == 'x':
        await move_to(current_pos_x+offset,current_pos_y,safe=False)
    elif axis == 'y':
        await move_to(current_pos_x,current_pos_y+offset,safe=False)
    
    if not is_primary_limit() and not is_secondary_limit():
        await home_cycle()
    else:
        if axis == 'x':
            await move_to(current_pos_x,current_pos_y,safe=False)
        elif axis  == 'y':
            await move_to(current_pos_x,current_pos_y,safe=False)
        Data.ADDITIONAL_INFO.append(f'{time()}: failed to unblock limit switches')


async def _eject_workspace():
    await raise_pen()
    await move_to(Data.GLOBAL_BOUNDARIES['x_max']/2,Data.GLOBAL_BOUNDARIES['y_max']-5)


def is_session_in_progress():
    return manage_task(Data.FILE_SESSION_TASK_TAG, "isbusy")


def _queue_gcode_req_clb(command:bytes):
    """
    Callback function to append commands to the G-code queue.
    :param commad string: G-code command
    :return result tuple: content-type and message
    """ 
    if is_session_in_progress():
        raise ServerBusyException('busy\n')
    try:
        commands = command.decode('utf8').splitlines()
        if len(Data.GCODE_QUEUE) + len(commands) > Data.MAX_QUEUE_LENGTH:
            raise RuntimeError(f'command queue length exceeded ({Data.MAX_QUEUE_LENGTH}), try again\n')
        for c in commands:
            Data.GCODE_QUEUE.append(c)
    except Exception as e:
        raise RuntimeError(f'queueing error: {e}')
    return 'text/plain', 'ok\n'


def _plotter_status_clb():
    """
    Callback function to get the current status of the machine.
    :return result tuple: content-type and status message
    """ 
    return 'application/json', \
        json.dumps({'queue_size': len(Data.GCODE_QUEUE),
          'active': is_active(),
          'paused':is_paused(),
          'limit_primary': is_primary_limit(),
          'limit_secondary': is_secondary_limit(),
          'positioning': 'absolute' if absolute_positioning() else 'relative',
          'x': get_current_pos()['sum'][0],
          'y': get_current_pos()['sum'][1],
          'coordinate_system': Data.CURRENT_CS,
          'additional_info': Data.ADDITIONAL_INFO
        })


def _plotter_pause_clb(paused:bytes):
    """
    Callback function to pause execution of G-code commands from the queue.
    :param paused boolean: pause/unpause G-code execution
    :return result tuple: content-type and message
    """ 
    if paused.decode('utf8').lower() == 'true':
        Data.PAUSED = True
    elif paused.decode('utf8').lower() == 'false':
        Data.PAUSED = False
    else:
        raise ValueError(f'invalid value: only true or false is accepted\n')
    return 'text/plain', 'ok\n'


def _plotter_stop_clb(*_):
    """
    Callback function to stop execution of G-code commands from the queue
    and clear the contents of the queue.
    :return result tuple: content-type and message
    """ 
    manage_task(Data.FILE_SESSION_TASK_TAG, "kill")
    while len(Data.GCODE_QUEUE):
        Data.GCODE_QUEUE.popleft()
    Data.PAUSED = False
    return 'text/plain', 'ok\n'


def _plotter_set_tiling_clb(grid_size:bytes):
    """
    Callback function to set up work coordinate systems (WCS) for custom tiling
    :param grid_size integer: size of the grid (2 <= n <= 3), the workspace will consist of n*n tiles
    :return result tuple: content-type and message
    """
    if is_session_in_progress():
        raise ServerBusyException('busy\n')

    grid_size = int(grid_size)
    if grid_size not in range(1,4):
        raise ValueError(f'invalid value: grid_size must be in [1,3]\n')
    
    Data.TILE_GRID_SIZE = grid_size
    Data.CURRENT_TILE_IDX = 1
    x_spacing = (Data.GLOBAL_BOUNDARIES['x_max'] - Data.GLOBAL_BOUNDARIES['x_min'])/grid_size
    y_spacing = (Data.GLOBAL_BOUNDARIES['y_max'] - Data.GLOBAL_BOUNDARIES['y_min'])/grid_size
    wcs_names = sorted(list(Data.CS_COORDINATES.keys()))

    for i in range(grid_size):
        for j in range(grid_size):
            Data.GCODE_QUEUE.append(f"{wcs_names[i*grid_size+j+1]} X{x_spacing*j} Y{y_spacing*(grid_size-1-i)}")
            syslog(f"{wcs_names[i*grid_size+j+1]} X{x_spacing*j} Y{y_spacing*(grid_size-1-i)}")

    Data.GCODE_QUEUE.append(f"G51 S{1/grid_size}")
    Data.GCODE_QUEUE.append(wcs_names[Data.CURRENT_TILE_IDX])
    return 'text/plain', 'ok\n'


def _plotter_switch_tile_clb(idx:bytes=None):
    if is_session_in_progress():
        raise ServerBusyException('busy\n')

    if idx is not None and len(idx):
        idx = int(idx)

    if idx is None or idx == "":
        Data.CURRENT_TILE_IDX = max((Data.CURRENT_TILE_IDX + 1) % (Data.TILE_GRID_SIZE**2+1),1)
    elif idx in range(Data.TILE_GRID_SIZE**2+1):
        Data.CURRENT_TILE_IDX = idx
    else:
        raise ValueError("invalid index\n")
    
    wcs_names = sorted(list(Data.CS_COORDINATES.keys()))
    Data.GCODE_QUEUE.append(wcs_names[Data.CURRENT_TILE_IDX])
    return 'text/plain', 'ok\n'


def _plotter_play_clb(play_object_str:bytes):
    if is_session_in_progress():
        raise ServerBusyException('busy\n')

    try:
        play_object = json.loads(play_object_str)
    except:
        raise ValueError("invalid object\n")
    
    if not "sketch_name" in play_object.keys():
        raise ValueError("missing sketch_name\n")

    sketch_name = play_object["sketch_name"].split("/")[-1]
    if sketch_name not in os.listdir(Data.USER_DATA_ROOT):
        raise ValueError(f"sketch does not exist: {sketch_name}\n")
    
    workspaces = []
    if "workspaces" in play_object.keys():
        workspace_indices = play_object["workspaces"]
        if any(not isinstance(i,int) or i < 1 or i > Data.TILE_GRID_SIZE**2 for i in workspace_indices):
            raise ValueError(f"invalid workspace indices\n")
        coordinate_systems = sorted(list(Data.CS_COORDINATES.keys()))
        workspaces = [coordinate_systems[i] for i in workspace_indices]


    micro_task(tag=Data.FILE_SESSION_TASK_TAG,task=__file_reader(sketch_name, workspaces))
    return 'text/plain', 'ok\n'


def _plotter_test_clb(*_):
    if is_session_in_progress():
        raise ServerBusyException('busy\n')

    micro_task(tag=Data.FILE_SESSION_TASK_TAG,task=__file_reader("test_routine.gcode"))
    return 'text/plain', 'ok\n'


async def __file_reader(sketch_name, workspaces=[], ms_period=50):
    """
    Control task for queueing G-code commands from a file.
    :param ms_period int: delay between executing commands
    """
    try:
        with micro_task(tag=Data.FILE_SESSION_TASK_TAG):
            if not workspaces:
                workspaces = [Data.CURRENT_CS]

            for w in workspaces:
                while len(Data.GCODE_QUEUE) == Data.MAX_QUEUE_LENGTH:
                    await asleep(ms_period/1000)  
                Data.GCODE_QUEUE.append(w)
                with open(f"{Data.USER_DATA_ROOT}/{sketch_name}") as sketch:
                    for line in sketch:
                        while len(Data.GCODE_QUEUE) == Data.MAX_QUEUE_LENGTH:
                            await asleep(ms_period/1000)    
                        Data.GCODE_QUEUE.append(line)
                        await asleep(ms_period/1000)
            Data.GCODE_QUEUE.append("M104")
    except Exception as e:
        print(f"Sketch error: {Data.USER_DATA_ROOT}/{sketch_name}")
        sys.print_exception(e)
        syslog(f'[ERR] plotter: {e}')


async def run_gcode(command):
    """
    Execute a G-code command.
    :param command string: G-code command
    """
    gcode_movement_cmd = "\s*G(0|1)\s*[Xx]([-]?\d+(\.\d+)?)\s*[Yy]([-]?\d+(\.\d+)?)\s*$"

    gcode_regex = compile(gcode_movement_cmd)                               # Motion command
    positioning_regex = compile(f"^\s*G(90|91)\s*({gcode_movement_cmd})?")  # Absolute/relative positioning
    homing_regex = compile("^\s*G(28)\s*$")                                 # Homing cycle
    tool_change_regex = compile("^\s*M0?6\s*$")                             # Tool change
    end_pos_regex = compile("^\s*M100\s*$")                                 # Custom machine command for measuring workspace and updating boundaries
    step_loss_regex = compile("^\s*M101\s*$")                               # Custom machine command for measuring step loss at currently set speeds
    feedrate_measure_regex = compile("^\s*M102\s*$")                        # Custom machine command for measuring feedrates
    unblock_limit_regex = compile("^\s*M103\s*([xXyY])\s*([+-])\s*$")       # Custom machine command for recovering from triggered limit switch
    eject_workspace_regex = compile("^\s*M104\s*$")                         # Custom machine command to eject workspace

    wcs_set_regex = compile("^\s*G5(4|5|6|7|8|9|9\.1|9\.2|9\.3)\s*[Xx]([-]?\d+(\.\d+)?)\s*[Yy]([-]?\d+(\.\d+)?)\s*$") # Work coordinate system setting
    cs_select_regex = compile("^\s*G5(3|4|5|6|7|8|9|9\.1|9\.2|9\.3)\s*$")   # Machine/work coordinate system selection
    # TODO: custom center point for scaling?
    scaling_regex = compile("^\s*G5(0|1\s*S(\d+(\.\d+)?))\s*$")             # Scaling, G50 - off, G51 - on
    
    gcode_command = gcode_regex.search(command)
    positioning_command = positioning_regex.search(command)
    homing_command = homing_regex.search(command)
    tool_change_command = tool_change_regex.search(command)
    end_pos_command = end_pos_regex.search(command)
    step_loss_command = step_loss_regex.search(command)
    feedrate_measure_command = feedrate_measure_regex.search(command)
    wcs_set_command = wcs_set_regex.search(command)
    cs_select_command = cs_select_regex.search(command)
    scaling_command = scaling_regex.search(command)
    unblock_limit_command = unblock_limit_regex.search(command)
    eject_workspace_command = eject_workspace_regex.search(command)

    if not gcode_command and \
       not positioning_command and \
       not homing_command and \
       not tool_change_command and \
       not end_pos_command and \
       not step_loss_command and \
       not feedrate_measure_command and\
       not wcs_set_command and \
       not cs_select_command and \
       not scaling_command and \
       not unblock_limit_command and \
       not eject_workspace_command:
        console(f'Invalid G-code/M-code syntax: {command}')
        return

    # ------------------------------------
    # Non-movement instructions
    # ------------------------------------

    if positioning_command:
        if positioning_command.group(1) == '90':
            absolute_positioning(True)
        elif positioning_command.group(1) == '91':
            relative_positioning(True)
        if not gcode_command:
            return
        
    if homing_command:
        await home_cycle()
        return
    
    if tool_change_command:
        await prepare_pen()
        Data.PAUSED = True
        return

    if end_pos_command:
        await _measure_workspace()
        return
    
    if step_loss_command:
        await _measure_step_loss()
        return

    if feedrate_measure_command:
        await _measure_feedrate()
        return
    
    if wcs_set_command:
        Data.CS_COORDINATES[f"G5{wcs_set_command.group(1)}"] = (float(wcs_set_command.group(2)), float(wcs_set_command.group(4)))
        return

    if cs_select_command:
        Data.CURRENT_CS = f"G5{cs_select_command.group(1)}"
        return

    if scaling_command:
        if scaling_command.group(1) == '0':
            Data.CS_SCALING = 1.0
        else:
            Data.CS_SCALING = float(scaling_command.group(2))
        return
    
    if unblock_limit_command:
        axis = unblock_limit_command.group(1)
        direction = unblock_limit_command.group(2)
        await _unblock_limit(axis, direction)
        return
    
    if eject_workspace_command:
        await _eject_workspace()
        return

    # ------------------------------------
    # G-code movement command
    # ------------------------------------

    mode = int(gcode_command.group(1))
    x = float(gcode_command.group(2))
    y = float(gcode_command.group(4))

    if mode == 0:
        await raise_pen()
        delay_ms = Data.STEP_DELAY_MS_RAPID

    if mode == 1:
        await lower_pen()
        delay_ms = Data.STEP_DELAY_MS_LINEAR

    # TODO: implement junction factor for SCARA too, this is only for cartesian as of now
    current_pos = get_current_pos()['sum']
    junction_factor = 1

    if not len(Data.GCODE_QUEUE):
        junction_factor = 0
    else:
        next_command = gcode_regex.search(Data.GCODE_QUEUE[0])
        if next_command:
            next_mode = int(next_command.group(1))
            if next_mode != mode:
                junction_factor = 0
            else:
                x_n = float(next_command.group(2))
                y_n = float(next_command.group(4))
                if absolute_positioning():
                    junction_factor = max(cosine_similarity(current_pos, (x,y), (x_n, y_n)),0)
                else:
                    target_pos = (current_pos[0] + x, current_pos[1] + y)
                    next_pos = (target_pos[0] + x_n, target_pos[1] + y_n) # TODO: fix this, there might be a G90 in the next command
                    junction_factor = max(cosine_similarity(current_pos, target_pos, next_pos),0)

    offset_x, offset_y = Data.CS_COORDINATES[Data.CURRENT_CS]
    if absolute_positioning():
        transformed_x = offset_x + x * Data.CS_SCALING
        transformed_y = offset_y + y * Data.CS_SCALING

    elif relative_positioning():
        transformed_x = current_pos[0] + x * Data.CS_SCALING
        transformed_y = current_pos[1] + y * Data.CS_SCALING
    
    await move_to(transformed_x,transformed_y,delay_ms, safe=True, junction_factor=junction_factor)


async def __control_task(ms_period=10):
    """
    Control task for queueing G-code commands.
    :param ms_period int: delay between executing commands
    """
    with micro_task(tag=Data.CONTROL_TASK_TAG):
        try:
            await home_cycle()
        except LimitSwitchException as e:
            sys.print_exception(e)
            syslog(f'[ERR] plotter: {e}')
            Data.ADDITIONAL_INFO.append(f'{time()}: {e}')            

        last_command_ts = 0
        while True:
            try:
                if is_active() and time() - last_command_ts > Data.ACTIVE_TIMEOUT:
                    deactivate()
                    if not is_paused() and is_session_in_progress():
                        syslog(f"[INFO] plotter: killed task {Data.FILE_SESSION_TASK_TAG}")
                        manage_task(Data.FILE_SESSION_TASK_TAG, "kill")

                if is_paused():
                    await raise_pen()
                else:
                    command = ""
                    if len(Data.GCODE_QUEUE):
                        command = Data.GCODE_QUEUE.popleft()
                    if command:
                        if not is_active():
                            activate()
                        last_command_ts = time()
                        await run_gcode(command)
                await asleep(ms_period/1000)
            
            except LimitSwitchException as e:
                sys.print_exception(e)
                syslog(f'[ERR] plotter: {e}')
                Data.ADDITIONAL_INFO.append(f'{time()}: {e}')
                deactivate()
                return
            
            except Exception as e:
                sys.print_exception(e)
                syslog(f'[ERR] plotter: {e}')
                Data.ADDITIONAL_INFO.append(f'{time()}: {e}')

    
def load(primary_pins = Data.PRIMARY_PINS,
         secondary_pins = Data.SECONDARY_PINS,
         radius_primary = Data.RADIUS_PRIMARY,
         radius_secondary = Data.RADIUS_SECONDARY,
         steps_per_revolution = Data.STEPS_PER_REVOLUTION,
         servo_pin = Data.SERVO_PIN,
         limit_pin1 = Data.PRIMARY_LIMIT_PIN,
         limit_pin2 = Data.SECONDARY_LIMIT_PIN,
         webserver = True):
    """
    Initialize the module, and create endpoints to be able to run G-code commands through HTTP.
    :param primary_pins list: pin numbers for the primary arm's stepper motor
    :param secondary_pins list: pin numbers for the secondary arm's stepper motor
    :param radius_primary float: radius of the primary arm, measured in mm
    :param radius_secondary float: radius of the secondary arm, measured in mm
    :param steps_per_revolution int: steps per revolution of the stepper motors
    :param servo_pin int: pin number for the servo motor of the pen mechanism
    :param limit_pin1 int: pin number for the first limit switch
    :param limit_pin2 int: pin number for the second limit switch
    :param webserver bool: turn on/off webserver (API access)
    """

    if len(primary_pins) != 4 or len(secondary_pins) != 4:
        raise ValueError('The number of pins must be exactly four (only unipolar stepper motors are supported)!')

    Data.PRIMARY_PINS = [ Pin(p, Pin.OUT) for p in primary_pins ]
    Data.SECONDARY_PINS = [ Pin(p, Pin.OUT) for p in secondary_pins ]
    Data.RADIUS_PRIMARY = radius_primary
    Data.RADIUS_SECONDARY = radius_secondary
    Data.STEPS_PER_REVOLUTION = steps_per_revolution
    Data.SERVO_PIN = PWM(Pin(servo_pin), freq=50)
    Data.PRIMARY_LIMIT_PIN = Pin(limit_pin1, Pin.IN)
    Data.SECONDARY_LIMIT_PIN = Pin(limit_pin2, Pin.IN)

    if webserver:
        web_endpoint('plotter/gcode', _queue_gcode_req_clb, 'POST')
        web_endpoint('plotter/status', _plotter_status_clb)
        web_endpoint('plotter/pause', _plotter_pause_clb, 'POST')
        web_endpoint('plotter/stop', _plotter_stop_clb, 'POST')
        web_endpoint('plotter/tiling', _plotter_set_tiling_clb, 'POST')
        web_endpoint('plotter/tiling/switch', _plotter_switch_tile_clb, 'POST')
        web_endpoint('plotter/play', _plotter_play_clb, 'POST')
        web_endpoint('plotter/test', _plotter_test_clb, 'POST')
        micro_task(tag=Data.CONTROL_TASK_TAG,task=__control_task())

#######################
# Helper LM functions #
#######################

def pinmap():
    """
    [i] micrOS LM naming convention
    Shows logical pins - pin number(s) used by this Load module
    - info which pins to use for this application
    :return dict: pin name (str) - pin value (int) pairs
    """
    return None #TODO pinmap_search(['i2c_scl', 'i2c_sda'])


def help(widgets=False):
    """
    [i] micrOS LM naming convention - built-in help message
    :return tuple:
        (widgets=False) list of functions implemented by this application
        (widgets=True) list of widget json for UI generation
    """
    return None #TODO resolve(('TEXTBOX measure', 'reset', 'load', 'pinmap'), widgets=widgets)
