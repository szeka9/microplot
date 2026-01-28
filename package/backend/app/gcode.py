"""
G-code parser
"""

from ure import compile

GCODE_MOTION_STRING = r"\s*G(0|1)\s*[Xx]([-]?\d+(\.\d+)?)\s*[Yy]([-]?\d+(\.\d+)?)\s*$"


class ParsingResult:
    """
    Object with predefined slots for parsing results.
    """

    __slots__ = (
        "gcode_command",
        "positioning_command",
        "homing_command",
        "tool_change_command",
        "end_pos_command",
        "step_loss_command",
        "feedrate_measure_command",
        "unblock_limit_command",
        "eject_workspace_command",
        "wcs_set_command",
        "cs_select_command",
        "scaling_command",
    )

    def __init__(self):
        for attr in self.__slots__:
            self.__setattr__(attr, None)


def motion_command(command: str):
    """
    Parse default g-code motion command.
    """
    pattern = compile(GCODE_MOTION_STRING)
    return pattern.search(command)


def positioning_command(command: str):
    """
    Parse g-code motion command with G90/G91 positioning mode selection.
    """
    pattern = compile(r"^\s*G(90|91)\s*(" + GCODE_MOTION_STRING + ")?")
    return pattern.search(command)


def homing_command(command: str):
    """
    Parse g-code command for homing cycle.
    """
    pattern = compile(r"^\s*G(28)\s*$")
    return pattern.search(command)


def tool_change_command(command: str):
    """
    Parse tool change m-code command to replace the currently mounted tool.
    """
    pattern = compile(r"^\s*M0?6\s*$")
    return pattern.search(command)


def end_pos_command(command: str):
    """
    Parse custom machine command for measuring workspace and updating boundaries.
    """
    pattern = compile(r"^\s*M100\s*$")
    return pattern.search(command)


def step_loss_command(command: str):
    """
    Parse custom machine command for measuring step loss at currently set speeds.
    """
    pattern = compile(r"^\s*M101\s*$")
    return pattern.search(command)


def feedrate_measurement_command(command: str):
    """
    Parse custom machine command for measuring feedrates.
    """
    pattern = compile(r"^\s*M102\s*$")
    return pattern.search(command)


def unblock_limit_command(command: str):
    """
    Parse custom machine command for recovering from triggered limit switch.
    """
    pattern = compile(r"^\s*M103\s*([xXyY])\s*([+-])\s*$")
    return pattern.search(command)


def eject_workspace_command(command: str):
    """
    Parse custom machine command to eject workspace.
    """
    pattern = compile(r"^\s*M104\s*$")
    return pattern.search(command)


def wcs_set_command(command: str):
    """
    Parse work coordinate system setting.
    """
    pattern = compile(
        r"^\s*G5(4|5|6|7|8|9|9\.1|9\.2|9\.3)\s*[Xx]([-]?\d+(\.\d+)?)\s*[Yy]([-]?\d+(\.\d+)?)\s*$"
    )
    return pattern.search(command)


def cs_select_command(command: str):
    """
    Parse machine/work coordinate system selection.
    """
    pattern = compile(r"^\s*G5(3|4|5|6|7|8|9|9\.1|9\.2|9\.3)\s*$")
    return pattern.search(command)


def scaling_command(command: str):
    """
    Scaling, G50 - off, G51 - on.
    """
    # TODO: custom center point for scaling?
    pattern = compile(r"^\s*G5(0|1\s*S(\d+(\.\d+)?))\s*$")
    return pattern.search(command)


def parse_command(command: str):

    result = ParsingResult()

    result.gcode_command = motion_command(command)
    result.positioning_command = positioning_command(command)
    result.homing_command = homing_command(command)
    result.tool_change_command = tool_change_command(command)
    result.end_pos_command = end_pos_command(command)
    result.step_loss_command = step_loss_command(command)
    result.feedrate_measure_command = feedrate_measurement_command(command)
    result.unblock_limit_command = unblock_limit_command(command)
    result.eject_workspace_command = eject_workspace_command(command)
    result.wcs_set_command = wcs_set_command(command)
    result.cs_select_command = cs_select_command(command)
    result.scaling_command = scaling_command(command)

    return result
