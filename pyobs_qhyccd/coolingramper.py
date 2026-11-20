from __future__ import annotations

from typing import Any

from pyobs.utils.coolingramp import CoolingRamp

from .qhyccddriver import Control

# GetQHYCCDParam(CONTROL_COOLER) returns the last target that was set, and -100 if none was set since the camera was
# powered up (measured on a QHY294PRO-M)
COOLER_UNSET = -99.0
PWM_MAX = 255.0


class SdkCoolingRamper:
    """Ramps the cooling setpoint of a QHYCCD camera that is used directly through the driver (no pyobs module).

    The setpoint is written to CONTROL_COOLER, like QHYCCDCamera does by default, and the camera regulates by itself.
    "Off" is PWM 0 on CONTROL_MANULPWM. The camera keeps reporting the last target after that, so whether the cooler is
    on is tracked here. All methods block on SDK calls, so call step() from a worker thread. It uses the same planner
    as the CoolingRampMixin of the QHYCCDCamera module.
    """

    def __init__(self, driver: Any, ramp: CoolingRamp | None = None):
        """Creates a new ramper and finds out whether the cooler was left running.

        Without a target the cooler is idle and PWM 0 is written, so that CONTROL_CURPWM reads a defined value (it reads
        garbage until a PWM was set).

        Args:
            driver: An open QHYCCDDriver.
            ramp: Planner to use. Defaults to 1 degC/min in both directions, as the module does.
        """
        self.driver = driver
        self.ramp = ramp if ramp is not None else CoolingRamp(rate_warm=1.0, rate_cool=1.0)
        self._off = True
        if float(driver.get_param(Control.CONTROL_COOLER)) <= COOLER_UNSET:
            driver.set_param(Control.CONTROL_MANULPWM, 0)
        else:
            self._off = False

    def cooler_is_on(self) -> bool:
        """Whether the cooler is currently switched on."""
        return not self._off

    def setpoint(self) -> float:
        """Setpoint last written to the camera."""
        return float(self.driver.get_param(Control.CONTROL_COOLER))

    def temperature(self) -> float:
        """Current sensor temperature in degC."""
        return float(self.driver.get_param(Control.CONTROL_CURTEMP))

    def power(self) -> int:
        """Current cooler drive level in percent."""
        pwm = min(max(float(self.driver.get_param(Control.CONTROL_CURPWM)), 0.0), PWM_MAX)
        return round(pwm / PWM_MAX * 100)

    def warmup_minutes(self) -> float | None:
        """Estimated minutes until the cooler is off, if switched off now. None if the cooler is off or the
        warm-up is a single step."""
        if self._off or self.ramp.rate_warm is None:
            return None
        return max(0.0, self.ramp.off_temperature - self.setpoint()) / self.ramp.rate_warm

    def switch_off(self) -> None:
        """Stops the cooler at once (PWM 0), without a ramp."""
        self._write(False, None)

    def step(self, enabled: bool, set_point: float) -> float | None:
        """Performs one step towards the target.

        Args:
            enabled: Whether the cooler should be on at the end.
            set_point: Target setpoint if enabled.

        Returns:
            Seconds to wait before the next step, or None if the target was reached.
        """
        temperature = self.temperature()

        if not self._off:
            current = self.setpoint()
        elif not enabled:
            return None  # already off, nothing to warm up
        else:
            # cooler is off: start at the sensor temperature, so the setpoint does not jump
            current = self.ramp.round(temperature)
            self._write(True, current)

        # while warming up, the sensor lags behind the setpoint, so the ramp also needs the cooler power to see
        # whether the cooler is really idle before it is switched off
        power = self.power() if not enabled else None
        step = self.ramp.next_step(current, enabled, set_point, temperature, power)
        if step.write:
            self._write(step.enabled, step.setpoint)
        return None if step.done else step.delay

    def _write(self, enabled: bool, setpoint: float | None) -> None:
        if enabled and setpoint is not None:
            self.driver.set_param(Control.CONTROL_COOLER, setpoint)
            self._off = False
        else:
            # PWM 0 stops the cooler, and a later setpoint takes over again (measured on a QHY294PRO-M)
            self.driver.set_param(Control.CONTROL_MANULPWM, 0)
            self._off = True
