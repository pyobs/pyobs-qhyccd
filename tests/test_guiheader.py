"""Tests for the FITS header the GUI writes."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

try:
    from pyobs_qhyccd.gui import Control, control_range, full_frame, make_header, pixel_size_mm
except ImportError as e:  # no Qt extras, or the camera library is not installed
    pytest.skip(f"GUI cannot be imported: {e}", allow_module_level=True)


class FakeDevice:
    def __init__(self, available: set[Control]) -> None:
        self.available = available
        self.values = {
            Control.CONTROL_GAIN: 10.0,
            Control.CONTROL_OFFSET: 140.0,
            Control.CONTROL_CURTEMP: -9.5,
            Control.CONTROL_CURPWM: 127.5,
        }

    def is_control_available(self, control: Control) -> bool:
        return control in self.available

    def get_param(self, control: Control) -> float:
        return self.values[control]


CHIP = (23.4, 15.6, 6280.0, 4210.0, 3.76, 3.76)
DATE = datetime(2026, 11, 17, 10, 0, 0, tzinfo=UTC)
DATA = np.array([[1, 2], [3, 6]], dtype=np.uint16)
ALL = {
    Control.CONTROL_GAIN,
    Control.CONTROL_OFFSET,
    Control.CONTROL_CURTEMP,
    Control.CONTROL_CURPWM,
    Control.CONTROL_COOLER,
}


def test_header_has_the_module_keys() -> None:
    h = make_header(FakeDevice(ALL), CHIP, DATE, 5.0, (0, 0, 100, 100), DATA)  # type: ignore[arg-type]
    assert h["EXPTIME"] == 5.0 and h["DATE-OBS"] == "2026-11-17T10:00:00.000000"
    assert h["GAIN"] == 10.0 and h["OFFSET"] == 140.0
    assert h["DET-TEMP"] == -9.5 and h["DET-COOL"] == 50
    assert h["DET-PIXL"] == pytest.approx(0.00376) and h["XORGSUBF"] == 0 and h["DET-BIN1"] == 1
    assert (h["DATAMIN"], h["DATAMAX"], h["DATAMEAN"]) == (1.0, 6.0, 3.0)


def test_header_leaves_out_unavailable_controls() -> None:
    h = make_header(FakeDevice({Control.CONTROL_GAIN}), CHIP, DATE, 5.0, (0, 0, 100, 100), DATA)  # type: ignore[arg-type]
    assert h["GAIN"] == 10.0
    for key in ("OFFSET", "DET-TEMP", "DET-COOL"):
        assert key not in h


def test_pixel_size_garbage_is_left_out() -> None:
    garbage = (19.5, 13.2, 4164.0, 2822.0, 2.081e-320, 1.408e-320)
    assert pixel_size_mm(garbage) is None
    assert pixel_size_mm((1.0, 1.0, 1.0, 1.0, float("nan"), 1.0)) is None
    assert pixel_size_mm((1.0, 1.0, 1.0, 1.0, 4.63, 4.63)) == pytest.approx(0.00463)
    h = make_header(FakeDevice(ALL), garbage, DATE, 5.0, (0, 0, 100, 100), DATA)  # type: ignore[arg-type]
    assert "DET-PIXL" not in h


class FakeModes:
    def __init__(self, modes: list[tuple[int, str, int, int]], limits: dict[Control, tuple[float, ...]]) -> None:
        self.modes = modes
        self.limits = limits

    def get_read_modes(self) -> list[tuple[int, str, int, int]]:
        return self.modes

    def get_param_limits(self, control: Control) -> tuple[float, ...] | None:
        return self.limits.get(control)


def test_full_frame_follows_the_read_mode() -> None:
    device = FakeModes([(0, "11M MODE", 4164, 2822), (1, "47M MODE", 8336, 5648)], {})
    assert full_frame(device, CHIP, 0) == (4164, 2822)  # type: ignore[arg-type]
    assert full_frame(device, CHIP, 1) == (8336, 5648)  # type: ignore[arg-type]
    assert full_frame(FakeModes([], {}), CHIP, 0) == (6280, 4210)  # type: ignore[arg-type]


def test_control_range_falls_back() -> None:
    device = FakeModes([], {Control.CONTROL_GAIN: (0.0, 3624.0, 1.0), Control.CONTROL_OFFSET: (5.0, 5.0, 1.0)})
    assert control_range(device, Control.CONTROL_GAIN, (0.0, 100.0)) == (0.0, 3624.0)  # type: ignore[arg-type]
    assert control_range(device, Control.CONTROL_OFFSET, (0.0, 255.0)) == (0.0, 255.0)  # type: ignore[arg-type]
    assert control_range(device, Control.CONTROL_COOLER, (-30.0, 30.0)) == (-30.0, 30.0)  # type: ignore[arg-type]
