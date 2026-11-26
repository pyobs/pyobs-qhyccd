"""Unit tests for the non-hardware logic in QHYCCDCamera: constructor defaults, the
window/binning setters, the cooling-control guard, and the _run_blocking wrappers.

Hardware I/O (opening, exposing, reading out) is out of scope here.
"""

import asyncio
import threading
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from pyobs.interfaces import IBinning, ICooling, IWindow
from pyobs.utils.exceptions import GrabImageError

from pyobs_qhyccd import QHYCCDCamera, qhyccdcamera
from pyobs_qhyccd.blocking import BlockingSdkMixin
from pyobs_qhyccd.qhyccddriver import EMPTY_FRAME_MESSAGE, Control, EmptyFrameError  # type: ignore


def test_constructor_defaults() -> None:
    camera = QHYCCDCamera()
    assert camera._setpoint == -10
    assert camera._window == (0, 0, 0, 0)
    assert camera._binning == (1, 1)
    assert camera._effective_area == (0, 0, 0, 0)
    assert camera._cooling_ramp.rate_cool == 1.0  # unchanged from the old 1 degC per 60 s
    assert camera._cooling_ramp.rate_warm == 1.0
    assert camera._cooling_ramp.step == 1.0
    assert camera._default_gain == 10
    assert camera._default_offset == 140
    assert camera._driver is None


@pytest.mark.asyncio
async def test_set_window() -> None:
    camera = QHYCCDCamera()
    camera.comm.set_state = AsyncMock()  # type: ignore[method-assign]

    await camera.set_window(10, 20, 100, 200)

    assert camera._window == (10, 20, 100, 200)
    assert camera.comm.set_state.await_args is not None
    interface, state = camera.comm.set_state.await_args.args  # type: ignore[union-attr]
    assert interface is IWindow
    assert (state.x, state.y, state.width, state.height) == (10, 20, 100, 200)


@pytest.mark.asyncio
async def test_set_binning() -> None:
    camera = QHYCCDCamera()
    camera.comm.set_state = AsyncMock()  # type: ignore[method-assign]

    await camera.set_binning(2, 3)

    assert camera._binning == (2, 3)
    assert camera.comm.set_state.await_args is not None
    interface, state = camera.comm.set_state.await_args.args  # type: ignore[union-attr]
    assert interface is IBinning
    assert (state.x, state.y) == (2, 3)


def test_deprecated_cooling_step_and_wait_map_to_rates() -> None:
    camera = QHYCCDCamera(cooling_step=2.0, cooling_wait=30.0)
    assert camera._cooling_ramp.step == 2.0
    assert camera._cooling_ramp.rate_cool == pytest.approx(4.0)
    assert camera._cooling_ramp.rate_warm == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_set_cooling_queues_a_ramp_and_keeps_wanted_setpoint() -> None:
    camera = QHYCCDCamera()
    camera.comm.set_state = AsyncMock()  # type: ignore[method-assign]

    await camera.set_cooling(True, -15.0)

    assert camera.cooling_ramping
    assert camera._wanted_setpoint == -15.0
    assert camera._setpoint == -10  # configured default is not overwritten


@pytest.mark.asyncio
async def test_set_cooling_hardware_writes_setpoint_to_cooler_control() -> None:
    camera = QHYCCDCamera()
    driver = MagicMock()
    camera._driver = driver

    await camera._set_cooling_hardware(True, -12.0)

    driver.set_param.assert_called_once_with(Control.CONTROL_COOLER, -12.0)
    driver.set_temperature.assert_not_called()
    assert camera._cooling_off is False


@pytest.mark.asyncio
async def test_set_cooling_hardware_temperature_control_uses_controlqhyccdtemp() -> None:
    camera = QHYCCDCamera(cooling_control="temperature")
    driver = MagicMock()
    camera._driver = driver

    await camera._set_cooling_hardware(True, -12.0)

    driver.set_temperature.assert_called_once_with(-12.0)
    driver.set_param.assert_not_called()


def test_cooling_control_is_validated() -> None:
    with pytest.raises(ValueError):
        QHYCCDCamera(cooling_control="pwm")


def test_pwm_wrap_workaround_is_off_by_default() -> None:
    assert QHYCCDCamera()._pwm_wrap_workaround is False
    assert QHYCCDCamera(pwm_wrap_workaround=True)._pwm_wrap_workaround is True


@pytest.mark.asyncio
async def test_set_cooling_hardware_off_writes_pwm_zero_and_publishes_disabled() -> None:
    camera = QHYCCDCamera()
    camera.comm.set_state = AsyncMock()  # type: ignore[method-assign]
    driver = MagicMock()
    camera._driver = driver

    await camera._set_cooling_hardware(False, None)
    await camera._publish_cooling(50, cooler_available=True)

    driver.set_param.assert_called_once_with(Control.CONTROL_MANULPWM, 0)
    driver.set_temperature.assert_not_called()
    interface, state = camera.comm.set_state.await_args.args  # type: ignore[union-attr]
    assert interface is ICooling
    assert (state.setpoint, state.power, state.enabled) == (None, 50, False)


def _driver_with(cooler: float, pwm: float) -> MagicMock:
    driver = MagicMock()
    values = {Control.CONTROL_COOLER: cooler, Control.CONTROL_CURPWM: pwm}
    driver.get_param.side_effect = lambda control: values.get(control, 0.0)
    return driver


@pytest.mark.asyncio
async def test_get_cooling_hardware_reads_target_and_power() -> None:
    camera = QHYCCDCamera()
    camera._driver = _driver_with(-10.0, 178.5)

    assert await camera._get_cooling_hardware() == (True, -10.0, 70)


@pytest.mark.asyncio
async def test_get_cooling_hardware_has_no_setpoint_when_off_or_unset() -> None:
    camera = QHYCCDCamera()
    camera._driver = _driver_with(-100.0, 0.0)  # the camera reports -100 if no target was ever set
    assert await camera._get_cooling_hardware() == (True, None, 0)

    camera._driver = _driver_with(-10.0, 0.0)  # the last target stays readable after switching off
    camera._cooling_off = True
    assert await camera._get_cooling_hardware() == (False, None, 0)


def test_pwm_percent_is_clamped_to_the_pwm_range() -> None:
    assert QHYCCDCamera._pwm_percent(255.0) == 100.0
    assert QHYCCDCamera._pwm_percent(300.0) == 100.0  # garbage before the first PWM was set
    assert QHYCCDCamera._pwm_percent(-5.0) == 0.0


def test_init_cooling_state_idle_camera_writes_pwm_zero() -> None:
    camera = QHYCCDCamera()
    driver = _driver_with(-100.0, 77.0)

    camera._init_cooling_state(driver)

    driver.set_param.assert_called_once_with(Control.CONTROL_MANULPWM, 0)
    assert camera._cooling_off is True


def test_init_cooling_state_keeps_a_cooler_that_was_left_running() -> None:
    camera = QHYCCDCamera()
    driver = _driver_with(-10.0, 170.0)

    camera._init_cooling_state(driver)

    driver.set_param.assert_not_called()
    assert camera._cooling_off is False


@pytest.mark.asyncio
async def test_publish_cooling_reports_commanded_setpoint_and_target() -> None:
    camera = QHYCCDCamera()
    camera.comm.set_state = AsyncMock()  # type: ignore[method-assign]
    camera._cooling_commanded = -8.0
    await camera.set_cooling(True, -15.0)

    await camera._publish_cooling(40, cooler_available=True)

    interface, state = camera.comm.set_state.await_args.args  # type: ignore[union-attr]
    assert (state.setpoint, state.target, state.ramping, state.enabled) == (-8.0, -15.0, True, True)


@pytest.mark.asyncio
async def test_ramp_starts_from_sensor_temperature_and_steps_down() -> None:
    camera = QHYCCDCamera()
    driver = _driver_with(-100.0, 0.0)  # idle camera
    camera._driver = driver
    camera._cooling_off = True
    camera._current_temperature = 3.0
    await camera.set_cooling(True, 1.0)

    await camera._cooling_tick()  # enables at the sensor temperature, then steps once
    await camera._cooling_tick()

    writes = [c.args for c in driver.set_param.call_args_list if c.args[0] == Control.CONTROL_COOLER]
    assert [value for _, value in writes] == [3.0, 2.0, 1.0]


@pytest.mark.asyncio
async def test_ramp_continues_from_the_setpoint_the_camera_reports() -> None:
    camera = QHYCCDCamera()
    driver = _driver_with(-4.0, 100.0)  # cooler left at -4 degC by an earlier session
    camera._driver = driver
    camera._current_temperature = -3.5
    await camera.set_cooling(True, -6.0)

    await camera._cooling_tick()
    await camera._cooling_tick()

    writes = [c.args for c in driver.set_param.call_args_list if c.args[0] == Control.CONTROL_COOLER]
    assert [value for _, value in writes] == [-5.0, -6.0]


@pytest.mark.asyncio
async def test_set_gain_requires_driver() -> None:
    camera = QHYCCDCamera()
    with pytest.raises(ValueError):
        await camera.set_gain(10.0)


@pytest.mark.asyncio
async def test_reset_restores_gain_offset() -> None:
    camera = QHYCCDCamera(default_gain=20, default_offset=100)
    camera.set_gain = AsyncMock()  # type: ignore[method-assign]
    camera.set_offset = AsyncMock()  # type: ignore[method-assign]

    await camera.reset()

    camera.set_gain.assert_awaited_once_with(20)
    camera.set_offset.assert_awaited_once_with(100)


@pytest.mark.asyncio
async def test_full_reset_restores_cooling() -> None:
    camera = QHYCCDCamera(setpoint=-15.0)
    camera.reset = AsyncMock()  # type: ignore[method-assign]
    camera.set_cooling = AsyncMock()  # type: ignore[method-assign]

    await camera.full_reset()

    camera.reset.assert_awaited_once()
    camera.set_cooling.assert_awaited_once_with(True, -15.0)


@pytest.mark.asyncio
async def test_run_blocking_runs_func_and_returns_true() -> None:
    ran: list[bool] = []

    def fast() -> None:
        ran.append(True)

    camera = QHYCCDCamera()
    assert await camera._run_blocking(fast) is True
    assert ran == [True]


@pytest.mark.asyncio
async def test_run_blocking_times_out() -> None:
    done = threading.Event()

    def slow() -> None:
        done.wait()

    camera = QHYCCDCamera()
    assert await camera._run_blocking(slow, timeout=0.01) is False
    done.set()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_run_blocking_serializes_concurrent_calls() -> None:
    camera = QHYCCDCamera()
    active = 0
    max_active = 0
    track_lock = threading.Lock()

    def worker() -> None:
        nonlocal active, max_active
        with track_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with track_lock:
            active -= 1

    await asyncio.gather(
        camera._run_blocking(worker),
        camera._run_blocking(worker),
        camera._run_blocking(worker),
    )

    assert max_active == 1


@pytest.mark.asyncio
async def test_run_blocking_or_raise_returns_value() -> None:
    camera = QHYCCDCamera()
    assert await camera._run_blocking_or_raise(lambda: 42) == 42


@pytest.mark.asyncio
async def test_run_blocking_or_raise_reraises() -> None:
    camera = QHYCCDCamera()

    def boom() -> int:
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await camera._run_blocking_or_raise(boom)


@pytest.mark.asyncio
async def test_image_header_has_the_shared_cards() -> None:
    camera = QHYCCDCamera()
    camera._window = (0, 0, 4, 2)
    camera._effective_area = (0, 0, 4, 2)
    camera._current_temperature = -9.5
    camera._get_cooling_power = AsyncMock(return_value=50.0)  # type: ignore[method-assign]
    data = np.array([[1, 2, 3, 4], [5, 6, 7, 8]], dtype=np.uint16)

    image = await camera._get_image_with_header(data, "2026-11-17T10:00:00.000000", 5.0)

    h = image.header
    assert h["DATE-OBS"] == "2026-11-17T10:00:00.000000" and h["EXPTIME"] == 5.0
    assert h["DET-TEMP"] == -9.5 and h["DET-COOL"] == 50.0 and "DET-TSET" in h
    assert h["DET-BIN1"] == 1 and h["XORGSUBF"] == 0
    assert (h["DATAMIN"], h["DATAMAX"], h["DATAMEAN"]) == (1.0, 8.0, 4.5)


class _FakeDriverClass:
    """Stands in for QHYCCDDriver when the camera is opened again; every instance is a MagicMock."""

    def __init__(self) -> None:
        self.opened: list[MagicMock] = []
        self.fail: Exception | None = None
        self.controls_available = False

    def list_devices(self) -> list[bytes]:
        if self.fail is not None:
            raise self.fail
        return [b"cam"]

    def __call__(self, cam_id: bytes) -> MagicMock:
        driver = MagicMock()
        driver.is_control_available.side_effect = lambda c: self.controls_available and c is not Control.CAM_COLOR
        self.opened.append(driver)
        return driver


def _camera_with_failing_readout(
    monkeypatch: pytest.MonkeyPatch, get_single_frame: Any
) -> tuple[QHYCCDCamera, MagicMock, _FakeDriverClass]:
    camera = QHYCCDCamera()
    old = MagicMock()
    old.get_single_frame.side_effect = get_single_frame
    camera._driver = old
    camera._prepare_driver_for_exposure = AsyncMock()  # type: ignore[method-assign]
    camera._wait_exposure = AsyncMock(return_value=False)  # type: ignore[method-assign]
    fake = _FakeDriverClass()
    monkeypatch.setattr(qhyccdcamera, "QHYCCDDriver", fake)
    return camera, old, fake


def _raise_empty() -> None:
    raise EmptyFrameError(EMPTY_FRAME_MESSAGE)


@pytest.mark.asyncio
async def test_empty_frame_opens_the_camera_again_with_its_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    camera, old, fake = _camera_with_failing_readout(monkeypatch, _raise_empty)
    camera._gain, camera._offset = 20.0, 30.0
    camera._cooling_off = False
    camera._cooling_commanded = -7.0
    camera._params = {"usbtraffic": 30}
    fake.controls_available = True

    with pytest.raises(GrabImageError, match="opened again"):
        await camera._expose(1.0, False, asyncio.Event())

    old.close.assert_called_once()
    assert camera._driver is fake.opened[0]
    writes = [c.args for c in fake.opened[0].set_param.call_args_list]
    assert (Control.CONTROL_GAIN, 20.0) in writes and (Control.CONTROL_OFFSET, 30.0) in writes
    assert (Control.CONTROL_USBTRAFFIC, 30) in writes  # custom params after the default of 60
    assert (Control.CONTROL_COOLER, -7.0) in writes


@pytest.mark.asyncio
async def test_reopen_with_cooler_off_writes_pwm_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    camera, _, fake = _camera_with_failing_readout(monkeypatch, _raise_empty)
    camera._cooling_off = True
    fake.controls_available = True

    with pytest.raises(GrabImageError):
        await camera._expose(1.0, False, asyncio.Event())

    fake.opened[0].set_param.assert_any_call(Control.CONTROL_MANULPWM, 0)
    assert (Control.CONTROL_COOLER,) not in [c.args[:1] for c in fake.opened[0].set_param.call_args_list]


@pytest.mark.asyncio
async def test_timed_out_readout_reopens_only_after_the_sdk_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    returned = threading.Event()

    def slow_zeros() -> None:
        time.sleep(0.3)
        returned.set()
        _raise_empty()

    camera, old, fake = _camera_with_failing_readout(monkeypatch, slow_zeros)
    old.close.side_effect = lambda: closed_after_return.append(returned.is_set())
    closed_after_return: list[bool] = []
    monkeypatch.setattr(BlockingSdkMixin._run_blocking_or_raise, "__defaults__", (0.05,))

    with pytest.raises(GrabImageError, match="opened again") as info:
        await camera._expose(1.0, False, asyncio.Event())

    assert isinstance(info.value.__cause__, TimeoutError)
    assert closed_after_return == [True]
    assert camera._driver is fake.opened[0]


@pytest.mark.asyncio
async def test_failed_reopen_says_unplug(monkeypatch: pytest.MonkeyPatch) -> None:
    camera, _, fake = _camera_with_failing_readout(monkeypatch, _raise_empty)
    fake.fail = ValueError("No camera found.")

    with pytest.raises(GrabImageError, match="opening the camera again failed.*Unplug USB and power"):
        await camera._expose(1.0, False, asyncio.Event())

    assert camera._driver is None


@pytest.mark.asyncio
async def test_sdk_that_never_returns_says_unplug(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()
    camera, old, _ = _camera_with_failing_readout(monkeypatch, lambda: release.wait())
    monkeypatch.setattr(BlockingSdkMixin._run_blocking_or_raise, "__defaults__", (0.05,))
    monkeypatch.setattr(qhyccdcamera, "HUNG_READOUT_WAIT", 0.1)

    try:
        with pytest.raises(GrabImageError, match="did not return.*Unplug USB and power"):
            await camera._expose(1.0, False, asyncio.Event())
        old.close.assert_not_called()
    finally:
        release.set()
        await asyncio.sleep(0.05)
