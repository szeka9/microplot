"""
Stepper motor functions
"""

from uasyncio import sleep as asleep
from micropython import const

from microplot.machine import MachineBase

DIR_ANTICLOCKWISE = const(0x0000)
DIR_CLOCKWISE = const(0x0001)

###########################
# Stepper motor functions #
###########################


def deactivate(m: MachineBase):
    """
    Deactivate the coils of the stepper motors.
    """
    for p_i, p in enumerate(m.primary_pins):
        p.value(int(f"{0:04b}"[-p_i - 1]))

    for p_i, p in enumerate(m.secondary_pins):
        p.value(int(f"{0:04b}"[-p_i - 1]))
    m.activated = False


def activate(m: MachineBase):
    """
    Activate the coils of the stepper motors to maintain the current position.
    """
    for p_i, p in enumerate(m.primary_pins):
        p.value(int(f"{m.current_step_primary:04b}"[-p_i - 1]))

    for p_i, p in enumerate(m.secondary_pins):
        p.value(int(f"{m.current_step_secondary:04b}"[-p_i - 1]))
    m.activated = True


def is_active(m: MachineBase):
    """
    Returns if stepper motors are activated.
    :return activated boolean: current state
    """
    return m.activated


async def step_primary(m: MachineBase, is_backward=False):
    """
    Move the stepper motor of the primary motor while
    adjusting for preconfigured backlash.
    :param is_backward boolean: go backwards
    """

    # Backlash correction
    if m.backlash_steps_primary and is_backward and m.dir_primary == m.dir_forward:
        for _ in range(m.backlash_steps_primary):
            m.current_step_primary = (
                int(m.current_step_primary / 2)
                if m.current_step_primary > 1
                else (2 ** (len(m.primary_pins) - 1))
            )
            if m.current_step_primary == 2 ** len(m.primary_pins):
                m.current_step_primary = 1
            for p_i, p in enumerate(m.primary_pins):
                p.value(int(f"{m.current_step_primary:04b}"[-p_i - 1]))
            await asleep(m.step_delay_ms_rapid / 1000)

    if m.backlash_steps_primary and not is_backward and m.dir_primary == m.dir_backward:
        for _ in range(m.backlash_steps_primary):
            m.current_step_primary *= 2
            if m.current_step_primary == 2 ** len(m.primary_pins):
                m.current_step_primary = 1
            for p_i, p in enumerate(m.primary_pins):
                p.value(int(f"{m.current_step_primary:04b}"[-p_i - 1]))
            await asleep(m.step_delay_ms_rapid / 1000)

    m.dir_primary = is_backward

    # Regular stepping
    if is_backward:
        m.current_step_primary = (
            int(m.current_step_primary / 2)
            if m.current_step_primary > 1
            else (2 ** (len(m.primary_pins) - 1))
        )
        m.current_pos_primary -= 1
    else:
        m.current_step_primary *= 2
        m.current_pos_primary += 1

    if m.current_step_primary == 2 ** len(m.primary_pins):
        m.current_step_primary = 1

    for p_i, p in enumerate(m.primary_pins):
        p.value(int(f"{m.current_step_primary:04b}"[-p_i - 1]))


async def step_secondary(m: MachineBase, is_backward=False):
    """
    Move the stepper motor of the secondary motor while
    adjusting for preconfigured backlash.
    :param delay_ms int: delay between consecutive steps
    :param is_backward boolean: go backwards
    """

    # Backlash correction
    if m.backlash_steps_secondary and is_backward and m.dir_secondary == m.dir_forward:
        for _ in range(m.backlash_steps_secondary):
            m.current_step_secondary = (
                int(m.current_step_secondary / 2)
                if m.current_step_secondary > 1
                else (2 ** (len(m.secondary_pins) - 1))
            )
            if m.current_step_secondary == 2 ** len(m.secondary_pins):
                m.current_step_secondary = 1
            for p_i, p in enumerate(m.secondary_pins):
                p.value(int(f"{m.current_step_secondary:04b}"[-p_i - 1]))
            await asleep(m.step_delay_ms_rapid / 1000)

    if (
        m.backlash_steps_secondary
        and not is_backward
        and m.dir_secondary == m.dir_backward
    ):
        for _ in range(m.backlash_steps_secondary):
            m.current_step_secondary *= 2
            if m.current_step_secondary == 2 ** len(m.secondary_pins):
                m.current_step_secondary = 1
            for p_i, p in enumerate(m.secondary_pins):
                p.value(int(f"{m.current_step_secondary:04b}"[-p_i - 1]))
            await asleep(m.step_delay_ms_rapid / 1000)

    m.dir_secondary = is_backward

    # Regular stepping
    if is_backward:
        m.current_step_secondary = (
            int(m.current_step_secondary / 2)
            if m.current_step_secondary > 1
            else (2 ** (len(m.secondary_pins) - 1))
        )
        m.current_pos_secondary -= 1
    else:
        m.current_step_secondary *= 2
        m.current_pos_secondary += 1

    if m.current_step_secondary == 2 ** len(m.secondary_pins):
        m.current_step_secondary = 1

    for p_i, p in enumerate(m.secondary_pins):
        p.value(int(f"{m.current_step_secondary:04b}"[-p_i - 1]))
