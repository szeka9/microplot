"""
Module main
"""

from uasyncio import sleep as asleep
import ujson
from uos import listdir
from ure import compile
from usys import print_exception
from utime import time, ticks_ms

from Common import micro_task, web_endpoint, console, syslog, manage_task
from Web import ServerBusyException

from microplot import stepper, positioning
from microplot.machine import MachineBase, LimitSwitchException, read_from_config
from microplot.speed_ctrl import SpeedController


class _MachineContext:
    machine = None
    initialized = False


ctx = _MachineContext()


#####################
# Plotter functions #
#####################


async def home_cycle(m: MachineBase):
    """
    Homing routine to find x=0, y=0 based on limit switches.
    """
    await m.raise_pen()

    if True in m.limit_status().values():
        raise LimitSwitchException("limit switch hit before homing cycle")

    # Hit limits
    with SpeedController(
        m.step_delay_ms_linear, m.step_delay_ms_init, m.acceleration_rate
    ) as ctrl:
        while not m.is_primary_home() or not m.is_secondary_home():

            if not m.is_primary_home():
                await stepper.step_primary(m, m.dir_backward)

            if not m.is_secondary_home():
                await stepper.step_secondary(m, m.dir_backward)

            ctrl.update_speed()
            await ctrl.control()

    # Add slight offset to untrigger limit switches
    with SpeedController(
        m.step_delay_ms_linear, m.step_delay_ms_init, m.acceleration_rate
    ) as ctrl:
        offset_steps = 0
        while m.is_primary_limit() or m.is_secondary_limit():

            if offset_steps > m.steps_per_revolution:
                raise ValueError("limit switch error, cannot untrigger")

            if m.is_primary_limit():
                await stepper.step_primary(m, m.dir_forward)

            if m.is_secondary_limit():
                await stepper.step_secondary(m, m.dir_forward)

            offset_steps += 1
            ctrl.update_speed()
            await ctrl.control()

    m.current_pos_primary = 0
    m.current_pos_secondary = 0


async def _measure_step_loss(m: MachineBase):
    """
    Test function to check how many steps are lost at a given speed.
    """
    measure_offset = m.steps_per_revolution
    expected_steps = m.steps_per_revolution
    await home_cycle(m)
    await m.move_to(
        measure_offset,
        measure_offset,
        m.step_delay_ms_linear,
        m.step_delay_ms_linear * 2,
        safe=False,
    )

    actual_steps_primary = 0

    with SpeedController(
        m.step_delay_ms_rapid, m.step_delay_ms_init, m.acceleration_rate
    ) as ctrl:
        while not m.is_primary_home():
            await stepper.step_primary(m, m.dir_backward)
            ctrl.update_speed()
            await ctrl.control()
            actual_steps_primary += 1

    if actual_steps_primary != expected_steps:
        print(
            "mismatch in expected vs measured steps during travel in primary axis: "
            + f"{expected_steps} != {actual_steps_primary} (measured)"
        )

    m.additional_info.append(
        (
            f"{time()}: measured steps in primary axis: "
            f"{actual_steps_primary} (expected: {expected_steps})"
        )
    )

    actual_steps_secondary = 0

    with SpeedController(
        m.step_delay_ms_rapid, m.step_delay_ms_init, m.acceleration_rate
    ) as ctrl:
        while not m.is_secondary_home():
            await stepper.step_secondary(m, m.dir_backward)
            ctrl.update_speed()
            await ctrl.control()
            actual_steps_secondary += 1

    if actual_steps_secondary != expected_steps:
        print(
            "mismatch in expected vs measured steps during travel in secondary axis: "
            + f"{expected_steps} != {actual_steps_secondary} (measured)"
        )

    m.additional_info.append(
        (
            f"{time()}: measured steps in secondary axis: "
            f"{actual_steps_primary} (expected: {expected_steps})"
        )
    )

    # Move backwards to untrigger the limit switches
    with SpeedController(
        m.step_delay_ms_linear, m.step_delay_ms_init, m.acceleration_rate
    ) as ctrl:
        while m.is_primary_limit() or m.is_secondary_limit():

            if m.is_primary_limit():
                await stepper.step_primary(m, m.dir_forward)

            if m.is_secondary_limit():
                await stepper.step_secondary(m, m.dir_forward)

            ctrl.update_speed()
            await ctrl.control()
    await home_cycle(m)


async def _measure_workspace(m: MachineBase):
    """
    Measure the size of usable workspace, and adjust global boundaries.
    :param delay_ms int: step delay in microseconds
    """
    await home_cycle(m)
    await m.move_to(
        m.steps_per_revolution,
        m.steps_per_revolution,
        m.step_delay_ms_linear,
        m.step_delay_ms_init,
    )

    actual_steps_primary = m.steps_per_revolution
    actual_steps_secondary = m.steps_per_revolution

    with SpeedController(
        m.step_delay_ms_linear, m.step_delay_ms_init, m.acceleration_rate
    ) as ctrl:
        while not m.is_primary_limit() or not m.is_secondary_limit():

            if not m.is_primary_limit():
                await stepper.step_primary(m, m.dir_forward)
                actual_steps_primary += 1

            if not m.is_secondary_limit():
                await stepper.step_secondary(m, m.dir_forward)
                actual_steps_secondary += 1

            ctrl.update_speed()
            await ctrl.control()

    # Move backwards to untrigger the limit switches
    with SpeedController(
        m.step_delay_ms_linear, m.step_delay_ms_init, m.acceleration_rate
    ) as ctrl:
        while m.is_primary_limit() or m.is_secondary_limit():

            if m.is_primary_limit():
                await stepper.step_primary(m, m.dir_backward)
                actual_steps_primary -= 1

            if m.is_secondary_limit():
                await stepper.step_secondary(m, m.dir_backward)
                actual_steps_secondary -= 1

            ctrl.update_speed()
            await ctrl.control()

    primary_dimension = (
        actual_steps_primary / m.steps_per_revolution
    ) * m.steps_per_revolution
    print(f"primary dimension [mm]: {primary_dimension}")

    secondary_dimension = (
        actual_steps_secondary / m.steps_per_revolution
    ) * m.steps_per_revolution
    print(f"secondary dimension [mm]: {secondary_dimension}")

    m.global_boundaries["x_max"] = primary_dimension
    m.global_boundaries["y_max"] = secondary_dimension

    m.additional_info.append(
        f"{time()}: measured workspace dimension in primary axis: {primary_dimension}mm"
    )
    m.additional_info.append(
        f"{time()}: measured workspace dimension in secondary axis: {secondary_dimension}mm"
    )

    await m.move_to(primary_dimension / 2, secondary_dimension / 2)


async def _measure_feedrate(m: MachineBase):
    """
    Measure the size of usable workspace, and adjust global boundaries.
    :param delay_ms int: step delay in microseconds
    """
    for delay_ms in [m.step_delay_ms_rapid, m.step_delay_ms_linear]:
        await home_cycle(m)

        # Primary
        current_time = ticks_ms()
        await m.move_to(m.global_boundaries["x_max"], 0, delay_ms, delay_ms * 2)
        end_time = ticks_ms()
        m.additional_info.append(
            (
                f"{time()}: primary feedrate at {delay_ms}ms step delay: "
                f"{1000*m.global_boundaries["x_max"]/(end_time-current_time)}mm/s"
            )
        )

        # Secondary
        current_time = ticks_ms()
        await m.move_to(
            m.global_boundaries["x_max"],
            m.global_boundaries["y_max"],
            delay_ms,
            delay_ms * 2,
        )
        end_time = ticks_ms()
        m.additional_info.append(
            (
                f"{time()}: secondary feedrate at {delay_ms}ms step delay: "
                f"{1000*m.global_boundaries["x_max"]/(end_time-current_time)}mm/s"
            )
        )
    home_cycle(m)


async def _unblock_limit(m: MachineBase, axis, direction):
    if not m.is_primary_limit() and not m.is_secondary_limit():
        return

    await m.raise_pen()

    axis = axis.lower()
    current_pos_x = m.get_current_pos()["sum"][0]
    current_pos_y = m.get_current_pos()["sum"][1]
    offset = 1.5 if direction == "+" else -1.5

    if axis == "x":
        await m.move_to(current_pos_x + offset, current_pos_y, safe=False)
    elif axis == "y":
        await m.move_to(current_pos_x, current_pos_y + offset, safe=False)

    if not m.is_primary_limit() and not m.is_secondary_limit():
        await home_cycle(m)
    else:
        if axis == "x":
            await m.move_to(current_pos_x, current_pos_y, safe=False)
        elif axis == "y":
            await m.move_to(current_pos_x, current_pos_y, safe=False)
        m.additional_info.append(f"{time()}: failed to unblock limit switches")


async def _eject_workspace(m: MachineBase):
    await m.raise_pen()
    await m.move_to(m.global_boundaries["x_max"] / 2, m.global_boundaries["y_max"] - 5)


async def run_gcode(m: MachineBase, command):
    """
    Execute a G-code command.
    :param command string: G-code command
    """

    gcode_regex = compile(
        r"\s*G(0|1)\s*[Xx]([-]?\d+(\.\d+)?)\s*[Yy]([-]?\d+(\.\d+)?)\s*$"
    )  # Motion command
    positioning_regex = compile(
        r"^\s*G(90|91)\s*(\s*G(0|1)\s*[Xx]([-]?\d+(\.\d+)?)\s*[Yy]([-]?\d+(\.\d+)?)\s*$)?"
    )  # Absolute/relative positioning
    homing_regex = compile(r"^\s*G(28)\s*$")  # Homing cycle
    tool_change_regex = compile(r"^\s*M0?6\s*$")  # Tool change
    end_pos_regex = compile(
        r"^\s*M100\s*$"
    )  # Custom machine command for measuring workspace and updating boundaries
    step_loss_regex = compile(
        r"^\s*M101\s*$"
    )  # Custom machine command for measuring step loss at currently set speeds
    feedrate_measure_regex = compile(
        r"^\s*M102\s*$"
    )  # Custom machine command for measuring feedrates
    unblock_limit_regex = compile(
        r"^\s*M103\s*([xXyY])\s*([+-])\s*$"
    )  # Custom machine command for recovering from triggered limit switch
    eject_workspace_regex = compile(
        r"^\s*M104\s*$"
    )  # Custom machine command to eject workspace
    wcs_set_regex = compile(
        r"^\s*G5(4|5|6|7|8|9|9\.1|9\.2|9\.3)\s*[Xx]([-]?\d+(\.\d+)?)\s*[Yy]([-]?\d+(\.\d+)?)\s*$"
    )  # Work coordinate system setting
    cs_select_regex = compile(
        r"^\s*G5(3|4|5|6|7|8|9|9\.1|9\.2|9\.3)\s*$"
    )  # Machine/work coordinate system selection
    # TODO: custom center point for scaling?
    scaling_regex = compile(
        r"^\s*G5(0|1\s*S(\d+(\.\d+)?))\s*$"
    )  # Scaling, G50 - off, G51 - on

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

    if (
        not gcode_command
        and not positioning_command
        and not homing_command
        and not tool_change_command
        and not end_pos_command
        and not step_loss_command
        and not feedrate_measure_command
        and not wcs_set_command
        and not cs_select_command
        and not scaling_command
        and not unblock_limit_command
        and not eject_workspace_command
    ):
        console(f"Invalid G-code/M-code syntax: {command}")
        return

    # ------------------------------------
    # Non-movement instructions
    # ------------------------------------

    if positioning_command:
        if positioning_command.group(1) == "90":
            m.absolute_positioning(True)
        elif positioning_command.group(1) == "91":
            m.relative_positioning(True)
        if not gcode_command:
            return

    if homing_command:
        await home_cycle(m)
        return

    if tool_change_command:
        await m.prepare_pen()
        m.paused = True
        return

    if end_pos_command:
        await _measure_workspace(m)
        return

    if step_loss_command:
        await _measure_step_loss(m)
        return

    if feedrate_measure_command:
        await _measure_feedrate(m)
        return

    if wcs_set_command:
        m.cs_coordinates[f"G5{wcs_set_command.group(1)}"] = (
            float(wcs_set_command.group(2)),
            float(wcs_set_command.group(4)),
        )
        return

    if cs_select_command:
        m.current_cs = f"G5{cs_select_command.group(1)}"
        return

    if scaling_command:
        if scaling_command.group(1) == "0":
            m.cs_scaling = 1.0
        else:
            m.cs_scaling = float(scaling_command.group(2))
        return

    if unblock_limit_command:
        axis = unblock_limit_command.group(1)
        direction = unblock_limit_command.group(2)
        await _unblock_limit(m, axis, direction)
        return

    if eject_workspace_command:
        await _eject_workspace(m)
        return

    # ------------------------------------
    # G-code movement command
    # ------------------------------------

    mode = int(gcode_command.group(1))
    x = float(gcode_command.group(2))
    y = float(gcode_command.group(4))

    if mode == 0:
        await m.raise_pen()
        delay_ms = m.step_delay_ms_rapid

    if mode == 1:
        await m.lower_pen()
        delay_ms = m.step_delay_ms_linear

    # TODO: implement junction factor for SCARA too, this is only for cartesian as of now
    current_pos = m.get_current_pos()["sum"]
    junction_factor = 1

    if not m.gcode_queue:
        junction_factor = 0
    else:
        next_command = gcode_regex.search(m.gcode_queue[0])
        if next_command:
            next_mode = int(next_command.group(1))
            if next_mode != mode:
                junction_factor = 0
            else:
                x_n = float(next_command.group(2))
                y_n = float(next_command.group(4))
                if m.absolute_positioning():
                    junction_factor = max(
                        positioning.cosine_similarity(current_pos, (x, y), (x_n, y_n)),
                        0,
                    )
                else:
                    target_pos = (current_pos[0] + x, current_pos[1] + y)
                    next_pos = (
                        target_pos[0] + x_n,
                        target_pos[1] + y_n,
                    )  # TODO: fix this, there might be a G90 in the next command
                    junction_factor = max(
                        positioning.cosine_similarity(
                            current_pos, target_pos, next_pos
                        ),
                        0,
                    )

    offset_x, offset_y = m.cs_coordinates[m.current_cs]
    transformed_x, transformed_y = 0, 0
    if m.absolute_positioning():
        transformed_x = offset_x + x * m.cs_scaling
        transformed_y = offset_y + y * m.cs_scaling

    elif m.relative_positioning():
        transformed_x = current_pos[0] + x * m.cs_scaling
        transformed_y = current_pos[1] + y * m.cs_scaling

    await m.move_to(
        transformed_x,
        transformed_y,
        delay_ms,
        safe=True,
        junction_factor=junction_factor,
    )


async def __control_task(m: MachineBase, ms_period=10):
    """
    Control task for queueing G-code commands.
    :param ms_period int: delay between executing commands
    """
    with micro_task(tag=m.control_task_tag):
        try:
            await home_cycle(m)
        except LimitSwitchException as e:
            print_exception(e)
            syslog(f"[ERR] plotter: {e}")
            m.additional_info.append(f"{time()}: {e}")

        last_command_ts = 0
        while True:
            try:
                if stepper.is_active(m) and time() - last_command_ts > m.active_timeout:
                    stepper.deactivate(m)
                    if not m.is_paused() and m.is_session_in_progress():
                        syslog(f"[INFO] plotter: killed task {m.file_session_task_tag}")
                        manage_task(m.file_session_task_tag, "kill")

                if m.is_paused():
                    await m.raise_pen()
                else:
                    command = ""
                    if len(m.gcode_queue):
                        command = m.gcode_queue.popleft()
                    if command:
                        if not stepper.is_active(m):
                            stepper.activate(m)
                        last_command_ts = time()
                        await run_gcode(m, command)
                await asleep(ms_period / 1000)

            except LimitSwitchException as e:
                print_exception(e)
                syslog(f"[ERR] plotter: {e}")
                m.additional_info.append(f"{time()}: {e}")
                stepper.deactivate(m)
                return

            except Exception as e:
                print_exception(e)
                syslog(f"[ERR] plotter: {e}")
                m.additional_info.append(f"{time()}: {e}")


def with_machine(func):
    def decorated(*args, **kwargs):
        if not ctx.initialized:
            raise RuntimeError("Call load() first")
        return func(ctx.machine, *args, **kwargs)

    return decorated


@with_machine
def _queue_gcode_req_clb(m: MachineBase, command: bytes):
    """
    Callback function to append commands to the G-code queue.
    :param commad string: G-code command
    :return result tuple: content-type and message
    """
    if m.is_session_in_progress():
        raise ServerBusyException("busy\n")
    try:
        commands = command.decode("utf8").splitlines()
        if len(m.gcode_queue) + len(commands) > m.max_queue_length:
            raise RuntimeError(
                f"command queue length exceeded ({m.max_queue_length}), try again\n"
            )
        for c in commands:
            m.gcode_queue.append(c)
    except Exception as e:
        raise RuntimeError(f"queueing error: {e}") from e
    return "text/plain", "ok\n"


@with_machine
def _plotter_status_clb(m: MachineBase):
    """
    Callback function to get the current status of the machine.
    :return result tuple: content-type and status message
    """
    return "application/json", ujson.dumps(
        {
            "queue_size": len(m.gcode_queue),
            "active": stepper.is_active(m),
            "paused": m.is_paused(),
            "limit_primary": m.is_primary_limit(),
            "limit_secondary": m.is_secondary_limit(),
            "positioning": "absolute" if m.absolute_positioning() else "relative",
            "x": m.get_current_pos()["sum"][0],
            "y": m.get_current_pos()["sum"][1],
            "coordinate_system": m.current_cs,
            "additional_info": m.additional_info,
        }
    )


@with_machine
def _plotter_pause_clb(m: MachineBase, paused: bytes):
    """
    Callback function to pause execution of G-code commands from the queue.
    :param paused boolean: pause/unpause G-code execution
    :return result tuple: content-type and message
    """
    if paused.decode("utf8").lower() == "true":
        m.paused = True
    elif paused.decode("utf8").lower() == "false":
        m.paused = False
    else:
        raise ValueError("invalid value: only true or false is accepted\n")
    return "text/plain", "ok\n"


@with_machine
def _plotter_stop_clb(m: MachineBase, *_):
    """
    Callback function to stop execution of G-code commands from the queue
    and clear the contents of the queue.
    :return result tuple: content-type and message
    """
    manage_task(m.file_session_task_tag, "kill")
    while len(m.gcode_queue):
        m.gcode_queue.popleft()
    m.paused = False
    return "text/plain", "ok\n"


@with_machine
def _plotter_set_tiling_clb(m: MachineBase, grid_size: bytes):
    """
    Callback function to set up work coordinate systems (WCS) for custom tiling
    :param grid_size integer: size of the grid (2 <= n <= 3), will result in n*n tiles
    :return result tuple: content-type and message
    """
    if m.is_session_in_progress():
        raise ServerBusyException("busy\n")

    grid_size = int(grid_size)
    if grid_size not in range(1, 4):
        raise ValueError("invalid value: grid_size must be in [1,3]\n")

    m.tile_grid_size = grid_size
    m.current_tile_idx = 1
    x_spacing = (
        m.global_boundaries["x_max"] - m.global_boundaries["x_min"]
    ) / grid_size
    y_spacing = (
        m.global_boundaries["y_max"] - m.global_boundaries["y_min"]
    ) / grid_size
    wcs_names = sorted(list(m.cs_coordinates.keys()))

    for i in range(grid_size):
        for j in range(grid_size):
            m.gcode_queue.append(
                f"{wcs_names[i*grid_size+j+1]} X{x_spacing*j} Y{y_spacing*(grid_size-1-i)}"
            )
            syslog(
                f"{wcs_names[i*grid_size+j+1]} X{x_spacing*j} Y{y_spacing*(grid_size-1-i)}"
            )

    m.gcode_queue.append(f"G51 S{1/grid_size}")
    m.gcode_queue.append(wcs_names[m.current_tile_idx])
    return "text/plain", "ok\n"


@with_machine
def _plotter_switch_tile_clb(m: MachineBase, idx: bytes = None):
    if m.is_session_in_progress():
        raise ServerBusyException("busy\n")

    if idx is not None and len(idx):
        idx = int(idx)

    if idx is None or idx == "":
        m.current_tile_idx = max(
            (m.current_tile_idx + 1) % (m.tile_grid_size**2 + 1), 1
        )
    elif idx in range(m.tile_grid_size**2 + 1):
        m.current_tile_idx = idx
    else:
        raise ValueError("invalid index\n")

    wcs_names = sorted(list(m.cs_coordinates.keys()))
    m.gcode_queue.append(wcs_names[m.current_tile_idx])
    return "text/plain", "ok\n"


def _plotter_play_clb(m: MachineBase, play_object_str: bytes):
    if m.is_session_in_progress():
        raise ServerBusyException("busy\n")

    try:
        play_object = ujson.loads(play_object_str)
    except Exception as e:
        raise ValueError("invalid object\n") from e

    if not "sketch_name" in play_object.keys():
        raise ValueError("missing sketch_name\n")

    sketch_name = play_object["sketch_name"].split("/")[-1]
    if sketch_name not in listdir(m.user_data_root):
        raise ValueError(f"sketch does not exist: {sketch_name}\n")

    workspaces = []
    if "workspaces" in play_object.keys():
        workspace_indices = play_object["workspaces"]
        if any(
            not isinstance(i, int) or i < 1 or i > m.tile_grid_size**2
            for i in workspace_indices
        ):
            raise ValueError("invalid workspace indices\n")
        coordinate_systems = sorted(list(m.cs_coordinates.keys()))
        workspaces = [coordinate_systems[i] for i in workspace_indices]

    micro_task(
        tag=m.file_session_task_tag, task=__file_reader(m, sketch_name, workspaces)
    )
    return "text/plain", "ok\n"


async def __file_reader(m: MachineBase, sketch_name, workspaces=None, ms_period=50):
    """
    Control task for queueing G-code commands from a file.
    :param ms_period int: delay between executing commands
    """
    try:
        with micro_task(tag=m.file_session_task_tag):
            if not workspaces:
                workspaces = [m.current_cs]

            for w in workspaces:
                while len(m.gcode_queue) == m.max_queue_length:
                    await asleep(ms_period / 1000)
                m.gcode_queue.append(w)
                with open(
                    f"{m.user_data_root}/{sketch_name}", encoding="utf-8"
                ) as sketch:
                    for line in sketch:
                        while len(m.gcode_queue) == m.max_queue_length:
                            await asleep(ms_period / 1000)
                        m.gcode_queue.append(line)
                        await asleep(ms_period / 1000)
            m.gcode_queue.append("M104")
    except Exception as e:
        print(f"Sketch error: {m.user_data_root}/{sketch_name}")
        print_exception(e)
        syslog(f"[ERR] plotter: {e}")


@with_machine
def _plotter_test_clb(m: MachineBase, *_):
    if m.is_session_in_progress():
        raise ServerBusyException("busy\n")

    micro_task(tag=m.file_session_task_tag, task=__file_reader("test_routine.gcode"))
    return "text/plain", "ok\n"


def load(config_path, reload=False):
    """
    Initialize the module, and create endpoints to be able to run G-code commands through HTTP.
    """
    if ctx.initialized and not reload:
        return

    ctx.machine = read_from_config(config_path)
    ctx.initialized = True

    web_endpoint("plotter/gcode", _queue_gcode_req_clb, "POST")
    web_endpoint("plotter/status", _plotter_status_clb)
    web_endpoint("plotter/pause", _plotter_pause_clb, "POST")
    web_endpoint("plotter/stop", _plotter_stop_clb, "POST")
    web_endpoint("plotter/tiling", _plotter_set_tiling_clb, "POST")
    web_endpoint("plotter/tiling/switch", _plotter_switch_tile_clb, "POST")
    web_endpoint("plotter/play", _plotter_play_clb, "POST")
    web_endpoint("plotter/test", _plotter_test_clb, "POST")
    micro_task(tag=ctx.machine.control_task_tag, task=__control_task(ctx.machine))


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
    return None  # TODO pinmap_search(['i2c_scl', 'i2c_sda'])


def help(widgets=False):
    """
    [i] micrOS LM naming convention - built-in help message
    :return tuple:
        (widgets=False) list of functions implemented by this application
        (widgets=True) list of widget json for UI generation
    """
    return None  # TODO resolve(('TEXTBOX measure', 'reset', 'load', 'pinmap'), widgets=widgets)
