"""Unit tests for the non-hardware logic in QHYCCDVideo: frames(), the setters and the settings
restart. The QHYCCD driver is replaced by a fake.
"""

import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import numpy.typing as npt
import pytest
from pyobs.utils.enums import ImageFormat

from pyobs_qhyccd.qhyccdvideo import Control, QHYCCDVideo


class FakeDriver:
    """Stands in for QHYCCDDriver: frames come from a list, calls are recorded."""

    def __init__(self, frames: list[npt.NDArray[Any]] | None = None) -> None:
        self.frames = [] if frames is None else frames
        self.calls: list[Any] = []
        self.params: dict[Any, float] = {}
        self.fail_resolution = False

    def get_live_frame(self, buffer: npt.NDArray[np.uint8]) -> tuple[int, int, int, int] | None:
        if not self.frames:
            return None
        frame = self.frames.pop(0)
        raw = frame.tobytes()
        buffer[: len(raw)] = np.frombuffer(raw, dtype=np.uint8)
        return frame.shape[1], frame.shape[0], frame.itemsize * 8, 1

    def begin_live(self) -> None:
        self.calls.append("start")

    def stop_live(self) -> None:
        self.calls.append("stop")

    def set_bin_mode(self, x: int, y: int) -> None:
        self.calls.append(("bin", x, y))

    def set_resolution(self, *args: int) -> None:
        if self.fail_resolution:
            raise ValueError("Could not set resolution.")
        self.calls.append(("res", *args))

    def set_bits_mode(self, bits: int) -> None:
        self.calls.append(("bits", bits))

    def set_param(self, param: Any, value: float) -> None:
        # cameras round the exposure time to their own step size
        self.params[param] = round(value / 7) * 7 if param == Control.CONTROL_EXPOSURE else value

    def get_param(self, param: Any) -> float:
        return self.params[param]

    def get_mem_length(self) -> int:
        return 1024


def _video(fake: FakeDriver) -> QHYCCDVideo:
    video = QHYCCDVideo(exposure_time=0.001)
    video._driver = fake  # type: ignore[assignment]
    video._buffer = np.empty(1024, dtype=np.uint8)
    video._window = (0, 0, 100, 50)
    video._has_bits = video._has_gain = video._has_offset = True
    comm = MagicMock()
    comm.set_state = AsyncMock()
    video._comm = comm
    return video


def _frame(value: int, dtype: Any = np.uint16) -> npt.NDArray[Any]:
    return np.full((2, 3), value, dtype=dtype)


@pytest.mark.asyncio
async def test_frames_yields_copies_in_order_and_stops_live_on_close() -> None:
    fake = FakeDriver([_frame(i) for i in range(3)])
    video = _video(fake)

    iterator = video.frames()
    frames = [await anext(iterator) for _ in range(3)]
    await iterator.aclose()

    assert [int(f.data[0, 0]) for f in frames] == [0, 1, 2]
    assert all(f.data.shape == (2, 3) and f.data.dtype == np.uint16 for f in frames)
    # each frame owns its data, not a view of the reused buffer
    assert all(f.data.base is None for f in frames)
    assert all(f.generation == 0 and f.exposure_time == 0.001 and f.start is None for f in frames)
    assert fake.calls == ["start", "stop"]
    assert video._capturing is False


@pytest.mark.asyncio
async def test_frames_handles_8bit() -> None:
    fake = FakeDriver([_frame(200, np.uint8)])
    video = _video(fake)

    iterator = video.frames()
    frame = await anext(iterator)
    await iterator.aclose()

    assert frame.data.dtype == np.uint8 and int(frame.data[1, 2]) == 200


@pytest.mark.asyncio
async def test_set_exposure_time_restarts_live_and_bumps_generation() -> None:
    fake = FakeDriver()
    video = _video(fake)
    video._capturing = True

    await video.set_exposure_time(0.5)

    assert fake.calls == ["stop", ("bin", 1, 1), ("res", 0, 0, 100, 50), ("bits", 16), "start"]
    assert video.generation == 1
    # the read-back value, not the requested one
    assert video._exposure_time == fake.params[Control.CONTROL_EXPOSURE] / 1e6 != 0.5


@pytest.mark.asyncio
async def test_set_binning_sets_binned_resolution() -> None:
    fake = FakeDriver()
    video = _video(fake)
    video._window = (10, 20, 100, 50)

    await video.set_binning(2, 2)

    assert fake.calls[:2] == [("bin", 2, 2), ("res", 5, 10, 50, 25)]


@pytest.mark.asyncio
async def test_set_image_format_int8() -> None:
    fake = FakeDriver()
    video = _video(fake)

    await video.set_image_format(ImageFormat.INT8)

    assert ("bits", 8) in fake.calls


@pytest.mark.asyncio
async def test_set_image_format_rejected_without_transferbit() -> None:
    video = _video(FakeDriver())
    video._has_bits = False
    with pytest.raises(ValueError):
        await video.set_image_format(ImageFormat.INT8)


@pytest.mark.asyncio
async def test_rejected_settings_are_restored() -> None:
    fake = FakeDriver()
    video = _video(fake)
    await video.set_window(0, 0, 100, 50)

    fake.fail_resolution = True
    with pytest.raises(ValueError):
        await video.set_window(0, 0, 10000, 50)
    fake.fail_resolution = False
    assert video._window == (0, 0, 100, 50)


@pytest.mark.asyncio
async def test_frames_after_settings_change_carry_new_generation() -> None:
    fake = FakeDriver([_frame(0)])
    video = _video(fake)
    iterator = video.frames()

    first = await anext(iterator)
    await video.set_exposure_time(0.5)
    fake.frames.append(_frame(1))
    second = await anext(iterator)
    await iterator.aclose()

    assert (first.generation, first.exposure_time) == (0, 0.001)
    assert (second.generation, second.exposure_time) == (1, fake.params[Control.CONTROL_EXPOSURE] / 1e6)


@pytest.mark.asyncio
async def test_run_blocking_serializes_with_driver_lock() -> None:
    video = _video(FakeDriver())
    held = threading.Event()

    def check() -> None:
        if video._driver_lock.locked():
            held.set()

    await video._run_blocking(check)
    assert held.is_set()
