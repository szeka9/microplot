"""
HTTP callback functions & machine context
"""

import ujson
from uos import listdir
from uasyncio import sleep as asleep
from usys import print_exception

from Common import micro_task, syslog, manage_task, web_endpoint
from Web import ServerBusyException

from microplot.machine import MachineBase
from microplot.stepper import is_active

class _MachineContext:
    machine = None
    initialized = False

ctx = _MachineContext()


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
            "active": is_active(m),
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


def setup_endpoints(m: MachineBase):
    if ctx.initialized:
        del ctx.machine
    ctx.machine = m
    ctx.initialized = True

    web_endpoint("plotter/gcode", _queue_gcode_req_clb, "POST")
    web_endpoint("plotter/status", _plotter_status_clb)
    web_endpoint("plotter/pause", _plotter_pause_clb, "POST")
    web_endpoint("plotter/stop", _plotter_stop_clb, "POST")
    web_endpoint("plotter/tiling", _plotter_set_tiling_clb, "POST")
    web_endpoint("plotter/tiling/switch", _plotter_switch_tile_clb, "POST")
    web_endpoint("plotter/play", _plotter_play_clb, "POST")
    web_endpoint("plotter/test", _plotter_test_clb, "POST")
