"""
Machine settings and types
"""

from math import pi
from ujson import loads
from ucollections import deque
from micropython import const
from umachine import Pin, PWM

from Common import console, manage_task

from microplot import positioning, stepper
from microplot.speed_ctrl import SpeedController

MACHINE_TYPE_CARTESIAN = const(0x0001)
MACHINE_TYPE_SCARA = const(0x0002)


class LimitSwitchException(Exception):
    """
    Exception used for events when a limit switch is triggered.
    """


class MachineBase:
    """
    Base class for different plotter types.
    """

    __slots__ = (
        "primary_pins",
        "secondary_pins",
        "servo_pin",
        "primary_limit_pin",
        "servo_pin",
        "primary_limit_pin",
        "secondary_limit_pin",
        "steps_per_revolution",
        "step_delay_ms_rapid",
        "step_delay_ms_linear",
        "step_delay_ms_init",
        "pen_delay_ms_init",
        "pen_delay_ms_target",
        "pen_acceleration_rate",
        "min_pen_duty",
        "max_pen_duty",
        "backlash_steps_primary",
        "backlash_steps_secondary",
        "acceleration_rate",
        "positioning",
        "current_cs",
        "cs_coordinates",
        "cs_scaling",
        "tile_grid_size",
        "current_tile_idx",
        "dir_forward",
        "dir_backward",
        "control_task_tag",
        "file_session_task_tag",
        "max_queue_length",
        "gcode_queue",
        "additional_info",
        "user_data_root",
        "primary_speed_controller",
        "secondary_speed_controller",
        "user_boundaries",
        "global_boundaries",
        "reject_oob",
        "dir_primary",
        "current_pos_primary",
        "current_step_primary",
        "dir_secondary",
        "current_pos_secondary",
        "current_step_secondary",
        "activated",
        "active_timeout",
        "machine_paused",
    )

    def __init__(
        self,
        primary_pins,  # List of pin objects for the primary stepper motor
        secondary_pins,  # List of pin objects for the secondary stepper motor
        servo_pin,  # PWM object for controlling the servo (pen)
        primary_limit_pin,  # Pin object for the primary motor's limit switch
        secondary_limit_pin,  # Pin object for the secondary motor's limit switch
        steps_per_revolution,  # Number of steps per a complete revolution (primary & secondary)
        step_delay_ms_rapid,  # Delay of milliseconds of rapid movement
        step_delay_ms_linear,  # Delay of milliseconds of linear movement
        step_delay_ms_init,  # Initial delay of milliseconds of any movement
        pen_delay_ms_init,  # Initial delay of seconds of pen movement
        pen_delay_ms_target,  # Target delay of seconds of pen movement
        pen_acceleration_rate,  # Pen acceleration rate (0;1]
        min_pen_duty,  # PWM duty cycle of the starting position of the servo (pen)
        max_pen_duty,  # PWM duty cycle of the end position of the servo (pen)
        backlash_steps_primary,  # Number of steps measuring the primary motor's backlash
        backlash_steps_secondary,  # Number of steps measuring the secondary motor's backlash
        acceleration_rate,  # Stepper acceleration rate (0;1]
        x_min,  # Lowest X coordinate
        x_max,  # Highest X coordinate
        y_min,  # Lowest Y coordinate
        y_max,  # Lowest Y coordinate
        reject_oob,  # Reject or accept (and constrain) targets out of boundary
    ):

        # Keyword arguments
        self.primary_pins = primary_pins
        self.secondary_pins = secondary_pins
        self.servo_pin = servo_pin
        self.primary_limit_pin = primary_limit_pin
        self.secondary_limit_pin = secondary_limit_pin
        self.steps_per_revolution = steps_per_revolution
        self.step_delay_ms_rapid = step_delay_ms_rapid
        self.step_delay_ms_linear = step_delay_ms_linear
        self.step_delay_ms_init = step_delay_ms_init
        self.pen_delay_ms_init = pen_delay_ms_init
        self.pen_delay_ms_target = pen_delay_ms_target
        self.pen_acceleration_rate = pen_acceleration_rate
        self.min_pen_duty = min_pen_duty
        self.max_pen_duty = max_pen_duty
        self.backlash_steps_primary = backlash_steps_primary
        self.backlash_steps_secondary = backlash_steps_secondary
        self.acceleration_rate = acceleration_rate

        # Defaults
        self.positioning = positioning.POS_ABSOLUTE
        self.current_cs = "G53"
        self.cs_coordinates = {
            "G53": (0, 0),  # Machine coordinate syste (MCS), must not be changed
            "G54": (0, 0),  # WCS #1 - Work coordinate system
            "G55": (0, 0),  # WCS #2
            "G56": (0, 0),  # WCS #3
            "G57": (0, 0),  # WCS #4
            "G58": (0, 0),  # WCS #5
            "G59": (0, 0),  # WCS #6
            "G59.1": (0, 0),  # WCS #7
            "G59.2": (0, 0),  # WCS #8
            "G59.3": (0, 0),  # WCS #9
        }
        self.cs_scaling = 1.0
        self.tile_grid_size = 3
        self.current_tile_idx = 0
        self.dir_forward = stepper.DIR_ANTICLOCKWISE
        self.dir_backward = stepper.DIR_CLOCKWISE

        self.control_task_tag = "microplot.gcode_runner"
        self.file_session_task_tag = "microplot.file_reader"
        self.max_queue_length = 100
        self.gcode_queue = deque((), self.max_queue_length)
        self.additional_info = []
        self.user_data_root = "/web/plotter/user_data"

        # Derived
        self.primary_speed_controller = SpeedController(
            step_delay_ms_rapid, step_delay_ms_init, acceleration_rate
        )
        self.secondary_speed_controller = SpeedController(
            step_delay_ms_rapid, step_delay_ms_init, acceleration_rate
        )
        self.user_boundaries = {
            "x_min": None,
            "y_min": None,
            "x_max": None,
            "y_max": None,
        }
        self.global_boundaries = {
            "x_min": x_min,
            "y_min": y_min,
            "x_max": x_max,
            "y_max": y_max,
        }
        self.reject_oob = reject_oob

        # Machine state
        self.dir_primary = None
        self.current_pos_primary = 0
        self.current_step_primary = 1

        self.dir_secondary = None
        self.current_pos_secondary = 0
        self.current_step_secondary = 1

        self.activated = True
        self.active_timeout = 35
        self.machine_paused = False

    def is_paused(self):
        """
        Returns if G-code execution is paused.
        :return paused boolean: current state
        """
        return self.machine_paused

    def is_session_in_progress(self):
        """
        Returns if a G-code exeuction session is in progress.
        :return is_busy boolean: current state
        """
        return manage_task(self.file_session_task_tag, "isbusy")

    def absolute_positioning(self, enabled=None):
        """
        Get/set absolute positioning mode (G90).
        :param enabled boolean: turn on/off absolute positioning
        :return enabled boolean: absolute positioning enabled
        """
        if enabled is None:
            return self.positioning == positioning.POS_ABSOLUTE
        if enabled:
            self.positioning = positioning.POS_ABSOLUTE
        else:
            self.positioning = positioning.POS_RELATIVE
        console(f"Absolute positioning: {enabled}")
        return enabled

    def relative_positioning(self, enabled=None):
        """
        Get/set relative positioning mode (G91).
        :param enabled boolean: turn on/off absolute positioning
        :return enabled boolean: absolute positioning enabled
        """
        if enabled is None:
            return self.positioning == positioning.POS_RELATIVE
        if enabled:
            self.positioning = positioning.POS_RELATIVE
        else:
            self.positioning = positioning.POS_ABSOLUTE
        console(f"Relative positioning: {enabled}")
        return enabled

    async def position_pen(self, target):
        """
        Position the pen in the range of [0; 100] mapped to the configured PWM cycles
        :param target int: target position
        """
        if target not in range(0, 101):
            raise ValueError(f"invalid target position: {target}")

        target_duty = int(
            self.min_pen_duty + (self.max_pen_duty - self.min_pen_duty) * (target) / 100
        )
        current_duty = self.servo_pin.duty()

        if current_duty == target_duty:
            return

        with SpeedController(
            self.pen_delay_ms_target, self.pen_delay_ms_init, self.pen_acceleration_rate
        ) as ctrl:
            if current_duty < target_duty:
                for duty in range(current_duty, target_duty + 1, 1):
                    self.servo_pin.duty(duty)
                    ctrl.update_speed(target_duty - duty)
                    await ctrl.control()
            else:
                for duty in range(current_duty, target_duty - 1, -1):
                    self.servo_pin.duty(duty)
                    ctrl.update_speed(target_duty - duty)
                    await ctrl.control()

    async def raise_pen(self):
        """
        Raise plotter pen.
        """
        await self.position_pen(100)

    async def prepare_pen(self):
        """
        Raise the pen holder to a position, where the pen can be mounted.
        """
        await self.position_pen(50)

    async def lower_pen(self):
        """
        Lower plotter pen smoothly.
        """
        await self.position_pen(0)

    def is_primary_limit(self):
        """
        Check if primary limit switch is reached.
        :return reached boolean: primary limit switch reached
        """
        return self.primary_limit_pin.value() == 1

    def is_primary_home(self):
        """
        Check if primary limit switch is reached at home position.
        :return reached boolean: primary limit switch reached at home
        """
        return (
            self.primary_limit_pin.value() == 1
            and self.dir_primary == self.dir_backward
        )

    def is_secondary_limit(self):
        """
        Check if secondary limit switch is reached.
        :return reached boolean: secondary limit switch reached
        """
        return self.secondary_limit_pin.value() == 1

    def is_secondary_home(self):
        """
        Check if secondary limit switch is reached at home position.
        :return reached boolean: secondary limit switch reached at home
        """
        return (
            self.secondary_limit_pin.value() == 1
            and self.dir_secondary == self.dir_backward
        )

    def limit_status(self):
        """
        Return current limit switch status.
        :return status dict: primary and secondary limit switch status
        """
        return {
            "limit primary": self.is_primary_limit(),
            "limit secondary": self.is_secondary_limit(),
        }

    def set_user_boundaries(self, x_min, y_min, x_max, y_max):
        """
        Set boundaries specified by the user.
        :param x_min float:
        :param y_min float:
        :param x_max float:
        :param y_max float:
        """
        if (
            x_min < self.global_boundaries["x_min"]
            or y_min < self.global_boundaries["y_min"]
            or x_max > self.global_boundaries["x_max"]
            or y_max > self.global_boundaries["y_max"]
        ):
            raise ValueError(
                f"boundary [{x_min}, {y_min}], [{x_max}, {y_max}] is out of globals bounds"
                + f" [{self.global_boundaries['x_min']}, {self.global_boundaries['y_min']}]"
                + f" [{self.global_boundaries['x_max']}, {self.global_boundaries['y_max']}]"
            )

        self.user_boundaries["x_min"] = x_min
        self.user_boundaries["y_min"] = y_min
        self.user_boundaries["x_max"] = x_max
        self.user_boundaries["y_max"] = y_max

    def get_step_differential(self, x, y):
        """
        Abstract base method for determining the number of steps
        per each axis to move from the current position to (x;y).
        """
        raise NotImplementedError("Abstract base method, must not be used!")

    async def move_to(
        self,
        x,
        y,
        target_delay_ms=None,
        step_delay_ms_init=None,
        acceleration_rate=None,
        junction_factor=0.0,
        safe=True,
    ):
        """
        Change the current position of the machine, while respecting predefined boundaries.
        Uses Bresenham's algorithm for efficient stepping (integer-only).
        """
        target_delay_ms = (
            target_delay_ms if target_delay_ms else self.step_delay_ms_rapid
        )
        step_delay_ms_init = (
            step_delay_ms_init if step_delay_ms_init else self.step_delay_ms_init
        )
        acceleration_rate = (
            acceleration_rate if acceleration_rate else self.acceleration_rate
        )

        # --- Boundary checks ---
        out_of_global_boundaries = (
            x < self.global_boundaries["x_min"]
            or y < self.global_boundaries["y_min"]
            or x > self.global_boundaries["x_max"]
            or y > self.global_boundaries["y_max"]
        )

        out_of_user_boundaries = None not in self.user_boundaries.values() and (
            x < self.user_boundaries["x_min"]
            or y < self.user_boundaries["y_min"]
            or x > self.user_boundaries["x_max"]
            or y > self.user_boundaries["y_max"]
        )

        if safe and (out_of_global_boundaries or out_of_user_boundaries):
            if self.reject_oob:
                raise ValueError(f"position out of boundary: ({x},{y})")

            # Clamp to valid boundaries
            if None not in self.user_boundaries.values():
                x = max(
                    self.user_boundaries["x_min"],
                    min(self.user_boundaries["x_max"], x),
                )
                y = max(
                    self.user_boundaries["y_min"],
                    min(self.user_boundaries["y_max"], y),
                )
            else:
                x = max(
                    self.global_boundaries["x_min"],
                    min(self.global_boundaries["x_max"], x),
                )
                y = max(
                    self.global_boundaries["y_min"],
                    min(self.global_boundaries["y_max"], y),
                )

        # --- Step differentials ---
        dx, dy = self.get_step_differential(x, y)
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
        with self.primary_speed_controller as pc, self.secondary_speed_controller as sc:
            pc.update(step_delay_ms_init, target_delay_ms, acceleration_rate)
            sc.update(step_delay_ms_init, target_delay_ms, acceleration_rate)

            while remaining_x > 0 or remaining_y > 0:
                if safe and (self.is_primary_limit() or self.is_secondary_limit()):
                    raise LimitSwitchException("limit switch triggered")

                e2 = 2 * err

                # Step X
                if e2 > -dy and remaining_x > 0:
                    await stepper.step_primary(self, sx < 0)
                    remaining_x -= 1
                    err -= dy

                # Step Y
                if e2 < dx and remaining_y > 0:
                    await stepper.step_secondary(self, sy < 0)
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


class CartesianPlotter(MachineBase):
    """
    Cartesian-type plotter child class.
    """

    __slots__ = ("machine_type", "unit_per_revolution")

    def __init__(self, unit_per_revolution, **kwargs):
        super().__init__(**kwargs)

        self.machine_type = MACHINE_TYPE_CARTESIAN
        self.unit_per_revolution = unit_per_revolution

    def get_primary_cartesian(self):
        """
        Get the cartesian coordinates corresponding to the primary axis for cartesian machines.
        :return tuple: cartesian coordinate
        """
        return (
            self.current_pos_primary / self.steps_per_revolution
        ) * self.unit_per_revolution

    def get_secondary_cartesian(self):
        """
        Get the cartesian coordinates corresponding to the secondary axis for cartesian machines.
        :return tuple: cartesian coordinate
        """
        return (
            self.current_pos_secondary / self.steps_per_revolution
        ) * self.unit_per_revolution

    def get_current_pos(self):
        """
        Get the current position of the machine.
        :return dict: primary, secondary and absolute positions
        """
        primary_cartesian = self.get_primary_cartesian()
        secondary_cartesian = self.get_secondary_cartesian()
        return {
            "sum": (primary_cartesian, secondary_cartesian),
            "x": primary_cartesian,
            "y": secondary_cartesian,
        }

    def get_step_differential(self, x, y):
        """
        Determine the number of steps per each axis to move from the current position to (x;y).
        :param x float: target position on the x axis
        :param y float: target position on the y axis
        :return status dict: primary and secondary limit switch status
        """
        diff_steps_primary = int(
            ((x - self.get_primary_cartesian()) / self.unit_per_revolution)
            * self.steps_per_revolution
        )
        diff_steps_secondary = int(
            ((y - self.get_secondary_cartesian()) / self.unit_per_revolution)
            * self.steps_per_revolution
        )

        return diff_steps_primary, diff_steps_secondary


class ScaraPlotter(MachineBase):
    """
    SCARA-type plotter child class.
    """

    __slots__ = ("machine_type", "radius_primary", "radius_secondary")

    def __init__(self, radius_primary, radius_secondary, **kwargs):
        super().__init__(**kwargs)

        self.machine_type = MACHINE_TYPE_SCARA
        self.radius_primary = radius_primary
        self.radius_secondary = radius_secondary

    def get_primary_polar(self):
        """
        Get the polar coordinates corresponding to the primary arm for SCARA machines.
        :return tuple: polar coordinate
        """
        return (
            self.radius_primary,
            pi * 360 * (self.current_pos_primary / self.steps_per_revolution) / 180,
        )

    def get_secondary_polar(self):
        """
        Get the polar coordinates corresponding to the secondary arm for SCARA machines.
        :return tuple: polar coordinate
        """
        return (
            self.radius_secondary,
            pi * 360 * (self.current_pos_secondary / self.steps_per_revolution) / 180,
        )

    def get_current_pos(self):
        """
        Get the current position of the machine.
        :return dict: primary, secondary and absolute positions
        """
        primary_polar = self.get_primary_polar()
        secondary_polar = self.get_secondary_polar()
        primary_pos = positioning.polar_to_cartesian(primary_polar[0], primary_polar[1])
        secondary_pos = positioning.polar_to_cartesian(
            secondary_polar[0], secondary_polar[1]
        )
        secondary_pos_rot = positioning.rotate_cartesian(
            secondary_pos[0], secondary_pos[1], primary_polar[1]
        )
        return {
            "sum": (
                primary_pos[0] + secondary_pos_rot[0],
                primary_pos[1] + secondary_pos_rot[1],
            ),
            "primary arm": primary_pos,
            "secondary arm": secondary_pos_rot,
        }

    def get_step_differential(self, x, y):
        """
        Determine the number of steps per each axis to move from the current position to (x;y).
        :param x float: target position on the x axis
        :param y float: target position on the y axis
        :return status dict: primary and secondary limit switch status
        """
        angle_primary, angle_secondary = positioning.resolve_arm_angles(
            x, y, self.get_primary_polar(), self.get_secondary_polar()
        )

        diff_steps_primary = positioning.convert_to_steps(
            angle_primary, self.steps_per_revolution
        )
        diff_steps_secondary = positioning.convert_to_steps(
            angle_secondary, self.steps_per_revolution
        )

        return diff_steps_primary, diff_steps_secondary


def read_from_config(config_path):
    """
    Read machine configuration from file (json).
    :param config_path: path to configuration file
    """

    with open(config_path, encoding="utf-8") as file:
        config = loads(file.read())

    machine_type = config["machine_type"].lower()
    servo_pin = config["servo"]["gpio"]
    primary_pins = config["primary_axis"]["gpio"]
    secondary_pins = config["secondary_axis"]["gpio"]
    primary_limit_pin = config["primary_axis"]["limit_gpio"]
    secondary_limit_pin = config["secondary_axis"]["limit_gpio"]

    for k in ["primary_axis", "secondary_axis", "machine_type", "servo"]:
        del config[k]

    if len(primary_pins) != 4 or len(secondary_pins) != 4:
        raise ValueError(
            "The number of pins must be exactly four (only unipolar stepper motors are supported)!"
        )

    pin_kwargs = {
        "primary_pins": [Pin(p, Pin.OUT) for p in primary_pins],
        "secondary_pins": [Pin(p, Pin.OUT) for p in secondary_pins],
        "servo_pin": PWM(Pin(servo_pin), freq=50),
        "primary_limit_pin": Pin(primary_limit_pin, Pin.IN),
        "secondary_limit_pin": Pin(secondary_limit_pin, Pin.IN),
    }

    if machine_type.lower() == "cartesian":
        return CartesianPlotter(**pin_kwargs, **config)
    if machine_type.lower() == "scara":
        return ScaraPlotter(**pin_kwargs, **config)

    raise ValueError('Machine type must either be "cartesian" or "scara"!')
