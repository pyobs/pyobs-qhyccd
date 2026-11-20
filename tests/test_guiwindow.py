"""Builds the GUI window with a fake driver (offscreen Qt, no camera)."""

from __future__ import annotations

import os
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6 import QtWidgets  # type: ignore[import-untyped]

    from pyobs_qhyccd.gui import Control, MainWindow
except ImportError as e:  # no Qt extras, or the camera library is not installed
    pytest.skip(f"GUI cannot be imported: {e}", allow_module_level=True)


class FakeDriver:
    def __init__(self, cooler: float = -100.0, with_modes: bool = True) -> None:
        self.values = {
            Control.CONTROL_GAIN: 10.0,
            Control.CONTROL_OFFSET: 140.0,
            Control.CONTROL_COOLER: cooler,
            Control.CONTROL_CURTEMP: 20.0,
            Control.CONTROL_CURPWM: 0.0,
        }
        self.limits = {
            Control.CONTROL_GAIN: (0.0, 3624.0, 1.0),
            Control.CONTROL_OFFSET: (0.0, 200.0, 1.0),
            Control.CONTROL_COOLER: (-50.0, 50.0, 0.1),
        }
        self.with_modes = with_modes
        self.writes: list[tuple[Control, float]] = []

    def get_chip_info(self) -> tuple[float, ...]:
        return (19.5, 13.2, 4164.0, 2822.0, 2.081e-320, 1.408e-320)

    def get_read_modes(self) -> list[tuple[int, str, int, int]]:
        if not self.with_modes:
            return []
        return [(0, "11M MODE", 4164, 2822), (1, "47M MODE", 8336, 5648)]

    def is_control_available(self, control: Control) -> bool:
        return control in self.values

    def get_param(self, control: Control) -> float:
        return self.values[control]

    def get_param_limits(self, control: Control) -> tuple[float, ...] | None:
        return self.limits.get(control)

    def set_param(self, control: Control, value: float) -> None:
        self.writes.append((control, value))
        self.values[control] = value


@pytest.fixture(scope="module")
def app() -> QtWidgets.QApplication:
    return cast(QtWidgets.QApplication, QtWidgets.QApplication.instance() or QtWidgets.QApplication([]))


def test_window_uses_the_read_mode_size_and_the_sdk_ranges(app: QtWidgets.QApplication) -> None:
    window = MainWindow(b"QHY294PROM-x", FakeDriver())  # type: ignore[arg-type]
    assert window.window_widget.max_width == 4164 and window.window_widget.max_height == 2822
    assert window.read_mode_box is not None and window.read_mode_box.count() == 2
    assert window.gain_offset is not None
    assert window.gain_offset.spin_gain.maximum() == 3624 and window.gain_offset.spin_gain.value() == 10
    assert window.gain_offset.spin_offset.maximum() == 200 and window.gain_offset.spin_offset.value() == 140
    assert window.cooling is not None and window.cooling_ramper is not None
    assert not window.cooling.enabled and not window.cooling_ramper.cooler_is_on()
    assert window.cooling.spin_set_point.minimum() == -50.0
    window.cooling_timer.stop()


def test_window_without_read_modes_or_cooler(app: QtWidgets.QApplication) -> None:
    driver = FakeDriver(with_modes=False)
    del driver.values[Control.CONTROL_COOLER]
    window = MainWindow(b"QHY5-x", driver)  # type: ignore[arg-type]
    assert window.read_mode_box is None and window.cooling is None
    assert window.window_widget.max_width == 4164  # chip info


def test_cooler_left_on_shows_in_the_widget(app: QtWidgets.QApplication) -> None:
    window = MainWindow(b"QHY294PROM-x", FakeDriver(cooler=-7.0))  # type: ignore[arg-type]
    assert window.cooling is not None and window.cooling.enabled and window.cooling.set_point == -7.0
    window.cooling_timer.stop()
