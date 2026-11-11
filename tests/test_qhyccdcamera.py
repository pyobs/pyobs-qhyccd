"""Unit tests for the non-hardware logic in QHYCCDCamera: constructor defaults, the
window/binning setters, the cooling-control guard, and the _run_blocking wrappers.

Hardware I/O (opening, exposing, reading out) is out of scope here.
"""

import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from pyobs.interfaces import IBinning, ICooling, IWindow

from pyobs_qhyccd import QHYCCDCamera


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
    interface, state = camera.comm.set_state.await_args.args
    assert interface is IWindow
    assert (state.x, state.y, state.width, state.height) == (10, 20, 100, 200)


@pytest.mark.asyncio
async def test_set_binning() -> None:
    camera = QHYCCDCamera()
    camera.comm.set_state = AsyncMock()  # type: ignore[method-assign]

    await camera.set_binning(2, 3)

    assert camera._binning == (2, 3)
    assert camera.comm.set_state.await_args is not None
    interface, state = camera.comm.set_state.await_args.args
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
async def test_set_cooling_hardware_writes_setpoint() -> None:
    camera = QHYCCDCamera()
    driver = MagicMock()
    camera._driver = driver

    await camera._set_cooling_hardware(True, -12.0)

    driver.set_temperature.assert_called_once_with(-12.0)
    assert camera._cooling_off is False


@pytest.mark.asyncio
async def test_set_cooling_hardware_off_does_not_write_and_publishes_disabled() -> None:
    camera = QHYCCDCamera()
    camera.comm.set_state = AsyncMock()  # type: ignore[method-assign]
    driver = MagicMock()
    camera._driver = driver

    await camera._set_cooling_hardware(False, None)
    await camera._publish_cooling(50, cooler_available=True)

    driver.set_temperature.assert_not_called()
    interface, state = camera.comm.set_state.await_args.args
    assert interface is ICooling
    assert (state.setpoint, state.power, state.enabled) == (None, 50, False)


@pytest.mark.asyncio
async def test_publish_cooling_reports_commanded_setpoint_and_target() -> None:
    camera = QHYCCDCamera()
    camera.comm.set_state = AsyncMock()  # type: ignore[method-assign]
    camera._cooling_commanded = -8.0
    await camera.set_cooling(True, -15.0)

    await camera._publish_cooling(40, cooler_available=True)

    interface, state = camera.comm.set_state.await_args.args
    assert (state.setpoint, state.target, state.ramping, state.enabled) == (-8.0, -15.0, True, True)


@pytest.mark.asyncio
async def test_ramp_starts_from_sensor_temperature_and_steps_down() -> None:
    camera = QHYCCDCamera()
    driver = MagicMock()
    driver.get_param.return_value = 0.0
    camera._driver = driver
    camera._current_temperature = 3.0
    await camera.set_cooling(True, 1.0)

    await camera._cooling_tick()  # enables at the sensor temperature, then steps once
    await camera._cooling_tick()

    assert [c.args[0] for c in driver.set_temperature.call_args_list] == [3.0, 2.0, 1.0]


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
