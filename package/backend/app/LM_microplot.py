"""
Module main
"""

from uasyncio import sleep as asleep
from usys import print_exception
from utime import time

from Common import micro_task, syslog, manage_task, console

from microplot import stepper, positioning
from microplot.gcode import parse_command, motion_command
from microplot.machine import MachineBase, LimitSwitchException, read_from_config
from microplot.routines import  home_cycle
from microplot.http_api import setup_endpoints


async def run_command(m: MachineBase, command):
    """
    Execute a G-code command.
    :param command string: G-code command
    """
    from microplot.routines import (
        measure_workspace,
        measure_step_loss,
        measure_feedrate,
        unblock_limit,
        eject_workspace,
    )

    parsed = parse_command(command)
    if not any(dir(parsed)):
        console(f"Invalid G-code/M-code syntax: {command}")
        return

    # ------------------------------------
    # Non-movement instructions
    # ------------------------------------

    if parsed.positioning_command:
        if parsed.positioning_command.group(1) == "90":
            m.absolute_positioning(True)
        elif parsed.positioning_command.group(1) == "91":
            m.relative_positioning(True)
        if not parsed.gcode_command:
            return

    if parsed.homing_command:
        await home_cycle(m)
        return

    if parsed.tool_change_command:
        await m.prepare_tool()
        m.paused = True
        return

    if parsed.end_pos_command:
        await measure_workspace(m)
        return

    if parsed.step_loss_command:
        await measure_step_loss(m)
        return

    if parsed.feedrate_measure_command:
        await measure_feedrate(m)
        return

    if parsed.wcs_set_command:
        m.cs_coordinates[f"G5{parsed.wcs_set_command.group(1)}"] = (
            float(parsed.wcs_set_command.group(2)),
            float(parsed.wcs_set_command.group(4)),
        )
        return

    if parsed.cs_select_command:
        m.current_cs = f"G5{parsed.cs_select_command.group(1)}"
        return

    if parsed.scaling_command:
        if parsed.scaling_command.group(1) == "0":
            m.cs_scaling = 1.0
        else:
            m.cs_scaling = float(parsed.scaling_command.group(2))
        return

    if parsed.unblock_limit_command:
        axis = parsed.unblock_limit_command.group(1)
        direction = parsed.unblock_limit_command.group(2)
        await unblock_limit(m, axis, direction)
        return

    if parsed.eject_workspace_command:
        await eject_workspace(m)
        return

    # ------------------------------------
    # G-code movement command
    # ------------------------------------

    mode = int(parsed.gcode_command.group(1))
    x = float(parsed.gcode_command.group(2))
    y = float(parsed.gcode_command.group(4))

    if mode == 0:
        await m.raise_tool()
        delay_ms = m.step_delay_ms_rapid

    if mode == 1:
        await m.lower_tool()
        delay_ms = m.step_delay_ms_linear

    # TODO: implement junction factor for SCARA too, this is only for cartesian as of now
    current_pos = m.get_current_pos()["sum"]
    junction_factor = 1

    if not m.gcode_queue:
        junction_factor = 0
    else:
        next_command = motion_command(m.gcode_queue[0])
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
                    await m.raise_tool()
                else:
                    command = ""
                    if len(m.gcode_queue):
                        command = m.gcode_queue.popleft()
                    if command:
                        if not stepper.is_active(m):
                            stepper.activate(m)
                        last_command_ts = time()
                        await run_command(m, command)
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


def load(config_path):
    """
    Initialize the module, and create endpoints to be able to run G-code commands through HTTP.
    """
    machine = read_from_config(config_path)
    setup_endpoints(machine)
    micro_task(tag=machine.control_task_tag, task=__control_task(machine))


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
