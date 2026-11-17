"""Tests for the FITS header the GUI writes."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

try:
    from pyobs_qhyccd.gui import Control, make_header
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


CHIP = (23.4, 15.6, 6280.0, 4210.0, 3760.0, 3760.0)
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
    assert h["DET-PIXL"] == 3.76 and h["XORGSUBF"] == 0 and h["DET-BIN1"] == 1
    assert (h["DATAMIN"], h["DATAMAX"], h["DATAMEAN"]) == (1.0, 6.0, 3.0)


def test_header_leaves_out_unavailable_controls() -> None:
    h = make_header(FakeDevice({Control.CONTROL_GAIN}), CHIP, DATE, 5.0, (0, 0, 100, 100), DATA)  # type: ignore[arg-type]
    assert h["GAIN"] == 10.0
    for key in ("OFFSET", "DET-TEMP", "DET-COOL"):
        assert key not in h
