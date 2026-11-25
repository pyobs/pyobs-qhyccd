import asyncio
import math
import sys
import time
import traceback
from datetime import UTC, datetime
from typing import Any

import qasync  # type: ignore
from astropy.io import fits
from numpy.typing import NDArray
from pyobs.utils.enums import ImageFormat
from pyobs.utils.frameheader import FrameSettings, make_frame_header
from pyobs.utils.gui.camera import (
    BinningWidget,
    CoolingWidget,
    DataDisplayWidget,
    ExposeWidget,
    ExposureTimeWidget,
    GainOffsetWidget,
    ImageFormatWidget,
    ListPickerDialog,
)
from pyobs.utils.gui.camera.windowingwidget import WindowingWidget
from pyobs.utils.parallel import event_wait
from PySide6 import QtCore, QtWidgets  # type: ignore[import-untyped]

from .coolingramper import SdkCoolingRamper
from .qhyccddriver import Control, EmptyFrameError, QHYCCDDriver, set_sdk_path

# pixel sizes outside this range (um) are taken as garbage; GetQHYCCDChipInfo returned garbage on a QHY294PRO-M
PIXEL_SIZE_RANGE = (0.5, 50.0)
# gain and offset the GUI starts with (the pyobs-qhyccd defaults; 140 keeps the bias clear of the clipping of offset 0)
# a readout longer than this (seconds) hints at a hanging camera; a normal one takes at most about 1.5 s
SLOW_READOUT = 30.0
DEFAULT_GAIN = 10
DEFAULT_OFFSET = 140
# setpoint range of the cooler widget if the SDK does not tell
DEFAULT_COOLING_RANGE = (-30.0, 30.0)


def pixel_size_mm(chip_info: tuple[float, ...]) -> float | None:
    """Pixel size in mm from the chip info (um at index 4), or None if the value is not plausible."""
    size = chip_info[4]
    if not math.isfinite(size) or not PIXEL_SIZE_RANGE[0] <= size <= PIXEL_SIZE_RANGE[1]:
        return None
    return size / 1000.0


def control_range(device: QHYCCDDriver, control: Control, default: tuple[float, float]) -> tuple[float, float]:
    """Minimum and maximum of a control from the SDK, or the default if the SDK does not tell (blocking)."""
    limits = device.get_param_limits(control)
    if limits is None or not all(math.isfinite(v) for v in limits[:2]) or limits[0] >= limits[1]:
        return default
    return limits[0], limits[1]


def full_frame(device: QHYCCDDriver, chip_info: tuple[float, ...], read_mode: int) -> tuple[int, int]:
    """Width and height of the full frame in a read mode; the chip info if the camera has no read modes (blocking)."""
    for index, _name, width, height in device.get_read_modes():
        if index == read_mode:
            return int(width), int(height)
    return int(chip_info[2]), int(chip_info[3])


def make_header(
    device: QHYCCDDriver,
    chip_info: tuple[float, ...],
    date_obs: datetime,
    exposure_time: float,
    window: tuple[int, int, int, int],
    data: NDArray[Any],
) -> fits.Header:
    """Builds the FITS header for a frame, reading gain, offset and cooling from the camera (blocking).

    Args:
        device: Camera to read the current settings from.
        chip_info: Result of the driver's get_chip_info (pixel size in um at index 4).
        date_obs: UTC time the exposure was started.
        exposure_time: Exposure time in seconds.
        window: Left, top, width and height of the window.
        data: The frame.

    Returns:
        The header.
    """

    def param(control: Control) -> float | None:
        return float(device.get_param(control)) if device.is_control_available(control) else None

    power = param(Control.CONTROL_CURPWM) if device.is_control_available(Control.CONTROL_COOLER) else None
    return make_frame_header(
        FrameSettings(
            date_obs=date_obs,
            exposure_time=exposure_time,
            window=window,
            binning=(1, 1),  # the GUI only offers 1x1
            pixel_size=pixel_size_mm(chip_info),
            gain=param(Control.CONTROL_GAIN),
            offset=param(Control.CONTROL_OFFSET),
            temperature=param(Control.CONTROL_CURTEMP),
            cooler_power=None if power is None else round(power / 255 * 100),
            data=data,
        )
    )


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, device_name: bytes, device: QHYCCDDriver | None = None) -> None:
        """Creates the window and opens the camera.

        Args:
            device_name: SDK ID of the camera.
            device: An already opened driver to use instead of opening the camera (for tests).
        """
        super().__init__()

        self.device_name = device_name
        self.read_mode = 0
        self._reopening = False
        if device is None:
            device = QHYCCDDriver(device_name)
            device.open(read_mode=self.read_mode)
        self.device = device
        chip_info = self.device.get_chip_info()
        self.chip_info = chip_info
        read_modes = self.device.get_read_modes()
        width, height = full_frame(self.device, chip_info, self.read_mode)

        self.central_widget = QtWidgets.QWidget()
        self.setCentralWidget(self.central_widget)

        global_layout = QtWidgets.QHBoxLayout()
        self.central_widget.setLayout(global_layout)
        self.widgets_frame = QtWidgets.QGroupBox()
        self.data_display_widget = DataDisplayWidget()
        global_layout.addWidget(self.widgets_frame)
        global_layout.addWidget(self.data_display_widget)

        layout = QtWidgets.QVBoxLayout()
        self.widgets_frame.setLayout(layout)

        # The read mode is set before the camera is initialised, so changing it means opening the camera again.
        self.read_mode_box: QtWidgets.QComboBox | None = None
        if len(read_modes) > 1:
            self.read_mode_box = QtWidgets.QComboBox()
            for index, name, mode_width, mode_height in read_modes:
                self.read_mode_box.addItem(f"{name} ({mode_width}x{mode_height})", index)
            self.read_mode_box.currentIndexChanged.connect(self._read_mode_changed)
            read_mode_frame = QtWidgets.QGroupBox("Read mode")
            read_mode_layout = QtWidgets.QVBoxLayout()
            read_mode_frame.setLayout(read_mode_layout)
            read_mode_layout.addWidget(self.read_mode_box)
            layout.addWidget(read_mode_frame)

        self.window_widget = WindowingWidget(width, height)
        layout.addWidget(self.window_widget)
        self.binning_widget = BinningWidget([(1, 1)])
        self.binning_widget.binning_changed.connect(self.window_widget.set_binning)
        layout.addWidget(self.binning_widget)
        self.format_widget = ImageFormatWidget([ImageFormat.INT16, ImageFormat.INT8])  # the first entry is the default
        layout.addWidget(self.format_widget)
        self.exposure_time = ExposureTimeWidget()
        layout.addWidget(self.exposure_time)

        self.gain_offset: GainOffsetWidget | None = None
        if self.device.is_control_available(Control.CONTROL_GAIN) and self.device.is_control_available(
            Control.CONTROL_OFFSET
        ):
            gain_min, gain_max = control_range(self.device, Control.CONTROL_GAIN, (0.0, 100.0))
            offset_min, offset_max = control_range(self.device, Control.CONTROL_OFFSET, (0.0, 255.0))
            gain = int(min(max(DEFAULT_GAIN, gain_min), gain_max))
            offset = int(min(max(DEFAULT_OFFSET, offset_min), offset_max))
            self.device.set_param(Control.CONTROL_GAIN, float(gain))
            self.device.set_param(Control.CONTROL_OFFSET, float(offset))
            self.gain_offset = GainOffsetWidget(
                (int(gain_min), int(gain_max)), (int(offset_min), int(offset_max)), gain, offset
            )
            self.gain_offset.gain_changed.connect(self._gain_changed)
            self.gain_offset.offset_changed.connect(self._offset_changed)
            layout.addWidget(self.gain_offset)

        # The cooler is ramped in steps, so that warming up does not shock the sensor.
        self.cooling: CoolingWidget | None = None
        self.cooling_ramper: SdkCoolingRamper | None = None
        self.cooling_target: tuple[bool, float] | None = None
        self.cooling_wakeup = asyncio.Event()
        self.cooling_task: asyncio.Task[None] | None = None
        self.warmup_task: asyncio.Task[None] | None = None
        self._close_confirmed = False
        if self.device.is_control_available(Control.CONTROL_COOLER):
            self.cooling_ramper = SdkCoolingRamper(self.device)
            cooling_min, cooling_max = control_range(self.device, Control.CONTROL_COOLER, DEFAULT_COOLING_RANGE)
            if not DEFAULT_COOLING_RANGE[0] - 70.0 <= cooling_min < cooling_max <= DEFAULT_COOLING_RANGE[1] + 70.0:
                cooling_min, cooling_max = DEFAULT_COOLING_RANGE
            on = self.cooling_ramper.cooler_is_on()
            self.cooling = CoolingWidget(
                (cooling_min, cooling_max), on, self.cooling_ramper.setpoint() if on else min(-5.0, cooling_max)
            )
            self.cooling.cooling_changed.connect(self._cooling_changed)
            layout.addWidget(self.cooling)
            self.cooling_timer = QtCore.QTimer()
            self.cooling_timer.setInterval(2000)
            self.cooling_timer.timeout.connect(self._update_cooling)
            self.cooling_timer.start()

        self.expose = ExposeWidget()
        layout.addWidget(self.expose)

        self.abort_exposure = asyncio.Event()
        self.expose.expose_clicked.connect(self._expose_clicked)
        self.expose.abort_clicked.connect(self._abort_clicked)

    @qasync.asyncSlot()  # type: ignore
    async def _gain_changed(self, gain: int) -> None:
        await asyncio.get_running_loop().run_in_executor(None, self.device.set_param, Control.CONTROL_GAIN, float(gain))

    @qasync.asyncSlot()  # type: ignore
    async def _offset_changed(self, offset: int) -> None:
        await asyncio.get_running_loop().run_in_executor(
            None, self.device.set_param, Control.CONTROL_OFFSET, float(offset)
        )

    @qasync.asyncSlot()  # type: ignore
    async def _read_mode_changed(self, index: int) -> None:
        assert self.read_mode_box is not None
        mode = int(self.read_mode_box.itemData(index))
        if mode == self.read_mode or self._reopening:
            return

        def restore() -> None:
            self.read_mode_box.blockSignals(True)  # type: ignore[union-attr]
            self.read_mode_box.setCurrentIndex(self.read_mode_box.findData(self.read_mode))  # type: ignore[union-attr]
            self.read_mode_box.blockSignals(False)  # type: ignore[union-attr]

        # opening the camera again switches the cooler off at once
        if self.cooling_ramper is not None and self.cooling_ramper.cooler_is_on():
            QtWidgets.QMessageBox.warning(
                self, "Cooler is on", "Switch the cooler off and let the sensor warm up before changing the read mode."
            )
            restore()
            return

        self._reopening = True
        try:
            loop = asyncio.get_running_loop()
            device = await loop.run_in_executor(None, self._reopen, mode)
        except Exception as e:
            traceback.print_exc()
            QtWidgets.QMessageBox.critical(self, "Read mode", f"Could not open the camera in read mode {mode}: {e}")
            self._close_confirmed = True
            self.close()
            return
        finally:
            self._reopening = False

        self.device = device
        self.read_mode = mode
        if self.cooling_ramper is not None:
            self.cooling_ramper.driver = device
        width, height = full_frame(device, self.chip_info, mode)
        self.window_widget.max_width = width
        self.window_widget.max_height = height
        self.window_widget.full_frame()

    def _reopen(self, mode: int) -> QHYCCDDriver:
        """Closes the camera and opens it in another read mode, then sets gain and offset again (blocking)."""
        self.device.close()
        devices = QHYCCDDriver.list_devices()
        name = self.device_name if self.device_name in devices else devices[0]
        device = QHYCCDDriver(name)
        device.open(read_mode=mode)
        if self.gain_offset is not None:
            device.set_param(Control.CONTROL_GAIN, float(self.gain_offset.gain))
            device.set_param(Control.CONTROL_OFFSET, float(self.gain_offset.offset))
        if self.cooling_ramper is not None:
            device.set_param(Control.CONTROL_MANULPWM, 0)
        return device

    @qasync.asyncSlot()  # type: ignore
    async def _cooling_changed(self, enabled: bool, set_point: float) -> None:
        # a new target replaces a running ramp, which continues from the current setpoint
        self.cooling_target = (enabled, set_point)
        self.cooling_wakeup.set()
        if self.cooling_task is None or self.cooling_task.done():
            self.cooling_task = asyncio.create_task(self._ramp_cooling())

    async def _ramp_cooling(self) -> None:
        assert self.cooling_ramper is not None
        loop = asyncio.get_running_loop()
        while self.cooling_target is not None:
            target = self.cooling_target
            self.cooling_wakeup.clear()
            try:
                delay = await loop.run_in_executor(None, self.cooling_ramper.step, *target)
            except Exception:
                traceback.print_exc()
                delay = 5.0
            if delay is None:
                if self.cooling_target is target:
                    self.cooling_target = None
                continue
            try:
                await asyncio.wait_for(self.cooling_wakeup.wait(), delay)
            except TimeoutError:
                pass

    @qasync.asyncSlot()  # type: ignore
    async def _update_cooling(self) -> None:
        if self.cooling is None or self.cooling_ramper is None or self._reopening:
            return
        ramper = self.cooling_ramper

        def _read() -> tuple[float, int]:
            return ramper.temperature(), ramper.power()

        temperature, power = await asyncio.get_running_loop().run_in_executor(None, _read)
        self.cooling.set_temperature(temperature)
        self.cooling.set_power(power)

    @qasync.asyncSlot()  # type: ignore
    async def _expose_clicked(self) -> None:
        self.device.set_resolution(*self.window_widget.values)
        self.device.set_param(Control.CONTROL_EXPOSURE, int(self.exposure_time.value * 1000.0 * 1000.0))

        if self.device.is_control_available(Control.CONTROL_TRANSFERBIT):
            if self.format_widget.value == ImageFormat.INT8:
                self.device.set_bits_mode(8)
            else:
                self.device.set_bits_mode(16)

        date_obs = datetime.now(UTC)
        self.expose.start_exposure(self.exposure_time.value)
        self.abort_exposure.clear()
        self.device.expose_single_frame()
        aborted = await event_wait(self.abort_exposure, self.exposure_time.value - 0.5)
        self.expose.set_exposures_left()
        if aborted:
            # a cancelled exposure must not be read out (see cancel_exposure's docs)
            self.device.cancel_exposure()
            return

        loop = asyncio.get_running_loop()
        start = time.monotonic()
        try:
            image_data = await loop.run_in_executor(None, self.device.get_single_frame)
        except EmptyFrameError as e:
            QtWidgets.QMessageBox.critical(self, "Readout", str(e))
            return
        finally:
            readout = time.monotonic() - start
            if readout > SLOW_READOUT:
                print(
                    f"Warning: the readout took {readout:.0f} s, the camera may hang (unplug USB and power).",
                    file=sys.stderr,
                )

        header = await loop.run_in_executor(
            None,
            make_header,
            self.device,
            self.chip_info,
            date_obs,
            self.exposure_time.value,
            self.window_widget.values,
            image_data,
        )
        image = fits.PrimaryHDU(image_data, header=header)
        self.data_display_widget.set_data(image)

    @qasync.asyncSlot()  # type: ignore
    async def _abort_clicked(self) -> None:
        self.abort_exposure.set()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # Closing the camera switches the cooler off at once, which warms the sensor abruptly. So with the cooler
        # on, offer to warm up first.
        if not self._close_confirmed and self.cooling_ramper is not None and self.cooling_ramper.cooler_is_on():
            event.ignore()
            if self.warmup_task is None or self.warmup_task.done():
                self._ask_close()
            return
        if self.cooling_ramper is not None:
            self.cooling_ramper.switch_off()
        self.device.close()
        super().closeEvent(event)

    def _ask_close(self) -> None:
        assert self.cooling_ramper is not None
        minutes = self.cooling_ramper.warmup_minutes()
        duration = "" if minutes is None else f" (about {minutes:.0f} min)"
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Cooler is on")
        box.setText(
            "Closing the camera switches the cooler off at once, which warms the sensor abruptly.\n"
            f"Warm up first{duration}?"
        )
        warm = box.addButton("Warm up, then close", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        now = box.addButton("Close now", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is warm:
            self.warmup_task = asyncio.create_task(self._warm_up_and_close())
        elif box.clickedButton() is now:
            self._close_confirmed = True
            self.close()

    async def _warm_up_and_close(self) -> None:
        """Ramps to the off temperature, switches the cooler off, then closes the window."""
        assert self.cooling_ramper is not None
        progress = QtWidgets.QProgressDialog("Warming up...", "Close now", 0, 0, self)
        progress.setWindowTitle("Warming up")
        progress.setMinimumDuration(0)
        progress.show()

        await self._cooling_changed(False, self.cooling_ramper.ramp.off_temperature)
        loop = asyncio.get_running_loop()
        while self.cooling_task is not None and not self.cooling_task.done() and not progress.wasCanceled():
            temperature = await loop.run_in_executor(None, self.cooling_ramper.temperature)
            progress.setLabelText(f"Warming up, sensor at {temperature:.1f} \N{DEGREE SIGN}C...")
            await asyncio.sleep(1.0)
        progress.close()

        if progress.wasCanceled():
            # stop the ramp, the camera is closed right away
            self.cooling_target = None
            self.cooling_wakeup.set()
        self._close_confirmed = True
        self.close()


async def async_main(app: QtWidgets.QApplication) -> None:
    # connect()
    devices = QHYCCDDriver.list_devices()
    if len(devices) == 0:
        print("No devices found. Exiting...")
        return
    device_picker = ListPickerDialog([d.decode("utf-8") for d in devices])
    if device_picker.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        print("No device selected. Exiting...")
        return
    device_name = devices[device_picker.comboBox().currentIndex()]

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)
    main_window = MainWindow(device_name)
    main_window.show()
    await app_close_event.wait()


def main() -> None:
    # optional path of libqhyccd.so as the first argument, like asi-gui
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        set_sdk_path(sys.argv[1])
    app = QtWidgets.QApplication(sys.argv)
    with qasync.QEventLoop(app) as loop:
        loop.run_until_complete(async_main(app))


if __name__ == "__main__":
    main()
