"""
Common plotter routines
"""

from utime import time, ticks_ms

from microplot.machine import MachineBase, LimitSwitchException
from microplot.speed_ctrl import SpeedController
from microplot import stepper


async def home_cycle(m: MachineBase):
    """
    Homing routine to find x=0, y=0 based on limit switches.
    """
    await m.raise_tool()

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


async def measure_step_loss(m: MachineBase):
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


async def measure_workspace(m: MachineBase):
    """
    Measure the size of usable workspace, and adjust global boundaries.
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


async def measure_feedrate(m: MachineBase):
    """
    Measure the size of usable workspace, and adjust global boundaries.
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


async def unblock_limit(m: MachineBase, axis: str, direction: str):
    """
    Unlbock axis that triggered a limit switch.
    :param axis str: name of the axis (e.g. "x", "y")
    :param direction str: axis direction ("-" or "+")
    """
    if not m.is_primary_limit() and not m.is_secondary_limit():
        return

    await m.raise_tool()

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


async def eject_workspace(m: MachineBase):
    """
    Raise the tool and move it away from the workspace.
    """
    await m.raise_tool()
    await m.move_to(m.global_boundaries["x_max"] / 2, m.global_boundaries["y_max"] - 5)
