"""
Speed controller context
"""

from utime import ticks_us
from uasyncio import sleep as asleep

from Common import syslog


class SpeedController:
    """
    Speed controller class for stepper motor and pen servo control.
    """

    def __init__(self, target_delay_ms, init_delay_ms, acceleration_rate):
        if not 0 < acceleration_rate <= 1:
            raise ValueError(
                f"invalid acceleration rate: {acceleration_rate} (must be between zero and one)"
            )
        if init_delay_ms <= target_delay_ms:
            raise ValueError(
                (
                    "invalid values for acceleration profile: "
                    "init_delay_ms must be higher than target_delay_ms"
                )
            )

        self.init_delay_ms = init_delay_ms
        self.target_delay_ms = target_delay_ms
        self.current_delay_ms = init_delay_ms
        self.previous_delay_ms = None
        self.acceleration_rate = acceleration_rate
        self.acceleration_step_ms = (
            init_delay_ms - target_delay_ms
        ) * acceleration_rate
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
        new_acceleration_step_ms = (
            self.init_delay_ms - self.target_delay_ms
        ) * self.acceleration_rate
        if new_acceleration_step_ms <= 0:
            raise ValueError(
                "Invalid acceleration delay calculated: "
                + f"init:{self.init_delay_ms}, "
                + f"target: {self.target_delay_ms}, "
                + f"acceleration_rate: {self.acceleration_rate}"
            )
        self.acceleration_step_ms = new_acceleration_step_ms

    def update(self, init_delay_ms=None, target_delay_ms=None, acceleration_rate=None):
        """
        Update variables for speed control.
        :param init_delay_ms int:
        :param target_delay_ms int:
        :param acceleration_rate int:
        """
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

    def update_speed(self, remaining_steps=float("inf"), junction_factor=1.0):
        """
        Update current delay based on remaining steps and per-axis junction factor.

        remaining_steps: steps left to complete move (float('inf') if continuous)
        junction_factor: 0–1, 1 = full speed, 0 = must stop
        """

        # Clamp junction factor
        junction_factor = max(0.0, min(junction_factor, 1.0))
        junction_delay_ms = self.target_delay_ms + (
            self.init_delay_ms - self.target_delay_ms
        ) * (1.0 - junction_factor)

        # Decelerate
        if (
            self.current_delay_ms < self.target_delay_ms
            or (junction_delay_ms - self.current_delay_ms) / self.acceleration_step_ms
            >= remaining_steps
        ):
            self.current_delay_ms = min(
                self.current_delay_ms + self.acceleration_step_ms, junction_delay_ms
            )

        # Accelerate
        elif self.current_delay_ms > self.target_delay_ms:
            self.current_delay_ms = max(
                self.current_delay_ms - self.acceleration_step_ms, self.target_delay_ms
            )

    async def control(self):
        """
        Sleep according to the current delay while compensating
        for previous loop overruns in a stable manner.
        """
        target_delay_us = int(self.current_delay_ms * 1000)

        now_us = ticks_us()

        if self.last_step_us is None:
            # First iteration: no correction possible
            delay_us = target_delay_us
        else:
            elapsed_us = now_us - self.last_step_us
            mismatch_us = elapsed_us - self.previous_delay_us

            if mismatch_us > 0:
                max_correction_us = target_delay_us // 2
                correction_us = min(mismatch_us, max_correction_us)

                delay_us = target_delay_us - correction_us
            else:
                delay_us = target_delay_us

        if delay_us < 0:
            syslog(f"[WARN] plotter: negative timing {delay_us / 1000:.3f} ms")
            delay_us = 0

        self.last_step_us = now_us
        self.previous_delay_us = delay_us

        await asleep(delay_us / 1000000)
