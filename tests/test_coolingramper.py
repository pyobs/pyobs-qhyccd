"""Tests for the cooling ramp of the GUI, with a fake driver."""

from __future__ import annotations

import pytest

try:
    from pyobs_qhyccd.qhyccddriver import Control  # type: ignore

    from pyobs_qhyccd.coolingramper import SdkCoolingRamper
except ImportError as e:  # the camera library is not installed
    pytest.skip(f"Driver cannot be imported: {e}", allow_module_level=True)


class FakeDriver:
    """Stands in for QHYCCDDriver. The sensor sits at a fixed offset above the setpoint while the cooler is on."""

    def __init__(self, sensor: float, setpoint: float = -100.0, offset: float = 0.5) -> None:
        self.sensor = sensor
        self.setpoint = setpoint
        self.pwm = 255.0 * 3  # garbage until a PWM was set
        self.offset = offset
        self.writes: list[tuple[Control, float]] = []

    def get_param(self, control: Control) -> float:
        if control == Control.CONTROL_COOLER:
            return self.setpoint
        if control == Control.CONTROL_CURPWM:
            return self.pwm
        if control == Control.CONTROL_CURTEMP:
            return self.sensor
        raise KeyError(control)

    def set_param(self, control: Control, value: float) -> None:
        self.writes.append((control, value))
        if control == Control.CONTROL_COOLER:
            self.setpoint = value
            self.sensor = value + self.offset
            self.pwm = 100.0
        elif control == Control.CONTROL_MANULPWM:
            self.pwm = value


def run(ramper: SdkCoolingRamper, enabled: bool, target: float, limit: int = 200) -> list[float]:
    delays: list[float] = []
    for _ in range(limit):
        delay = ramper.step(enabled, target)
        if delay is None:
            return delays
        delays.append(delay)
    raise AssertionError("ramp did not finish")


def test_idle_camera_gets_pwm_0_and_is_off() -> None:
    driver = FakeDriver(sensor=20.0)
    ramper = SdkCoolingRamper(driver)
    assert driver.writes == [(Control.CONTROL_MANULPWM, 0)]
    assert not ramper.cooler_is_on()
    assert ramper.power() == 0
    assert ramper.step(False, 20.0) is None  # nothing to warm up


def test_cooler_left_on_is_found() -> None:
    driver = FakeDriver(sensor=-4.5, setpoint=-5.0)
    ramper = SdkCoolingRamper(driver)
    assert driver.writes == []
    assert ramper.cooler_is_on() and ramper.setpoint() == -5.0


def test_ramps_down_in_one_degree_steps() -> None:
    driver = FakeDriver(sensor=20.0)
    ramper = SdkCoolingRamper(driver)
    delays = run(ramper, True, -5.0)
    setpoints = [v for c, v in driver.writes if c == Control.CONTROL_COOLER]
    assert setpoints[0] == 20.0 and setpoints[-1] == -5.0
    assert all(abs(a - b) <= 1.0 + 1e-9 for a, b in zip(setpoints, setpoints[1:], strict=False))
    assert all(d == pytest.approx(60.0) for d in delays)  # 1 degC/min
    assert ramper.cooler_is_on()


def test_warm_up_ends_with_pwm_0() -> None:
    driver = FakeDriver(sensor=-4.5, setpoint=-5.0)
    ramper = SdkCoolingRamper(driver)
    assert ramper.warmup_minutes() == pytest.approx(25.0)
    run(ramper, False, ramper.ramp.off_temperature)
    assert driver.writes[-1] == (Control.CONTROL_MANULPWM, 0)
    assert not ramper.cooler_is_on()
    # the camera keeps reporting the last target, but the cooler counts as off
    assert driver.setpoint > -99.0 and ramper.warmup_minutes() is None


def test_switch_off_is_immediate() -> None:
    driver = FakeDriver(sensor=-4.5, setpoint=-5.0)
    ramper = SdkCoolingRamper(driver)
    ramper.switch_off()
    assert driver.writes == [(Control.CONTROL_MANULPWM, 0)] and not ramper.cooler_is_on()


def test_power_is_clamped() -> None:
    driver = FakeDriver(sensor=20.0)
    ramper = SdkCoolingRamper(driver)
    driver.pwm = 300.0
    assert ramper.power() == 100
    driver.pwm = -3.0
    assert ramper.power() == 0
