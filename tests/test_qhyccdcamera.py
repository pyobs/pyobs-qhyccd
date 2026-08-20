"""Unit tests for the non-hardware logic in QHYCCDCamera: constructor defaults, the
window/binning setters, the cooling-control guard, and the _run_blocking wrappers.

Hardware I/O (opening, exposing, reading out) is out of scope here.
"""

import asyncio
import threading
import time
from unittest.mock import AsyncMock

import pytest
from pyobs.interfaces import IBinning, ICooling, IWindow

from pyobs_qhyccd import QHYCCDCamera


def test_constructor_defaults() -> None:
    camera = QHYCCDCamera()
    assert camera._setpoint == -10
    assert camera._window == (0, 0, 0, 0)
    assert camera._binning == (1, 1)
    assert camera._effective_area == (0, 0, 0, 0)
    assert camera._cooling_step == 1.0
    assert camera._cooling_wait == 60.0
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


@pytest.mark.asyncio
async def test_set_cooling_without_driver_publishes_state() -> None:
    camera = QHYCCDCamera()
    camera.comm.set_state = AsyncMock()  # type: ignore[method-assign]

    await camera.set_cooling(True, -15.0)

    # no driver attached, so power can't be read back and is published as None
    assert camera._setpoint == -15.0
    assert camera.comm.set_state.await_args is not None
    interface, state = camera.comm.set_state.await_args.args
    assert interface is ICooling
    assert (state.setpoint, state.power, state.enabled) == (-15.0, None, True)


@pytest.mark.asyncio
async def test_set_cooling_disabled_publishes_no_setpoint() -> None:
    camera = QHYCCDCamera()
    camera.comm.set_state = AsyncMock()  # type: ignore[method-assign]

    await camera.set_cooling(False, -15.0)

    # disabling cooling publishes setpoint=None even though a setpoint was passed in
    assert camera.comm.set_state.await_args is not None
    interface, state = camera.comm.set_state.await_args.args
    assert interface is ICooling
    assert (state.setpoint, state.enabled) == (None, False)


@pytest.mark.asyncio
async def test_set_gain_requires_driver() -> None:
    camera = QHYCCDCamera()
    with pytest.raises(ValueError):
        await camera.set_gain(10.0)


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
