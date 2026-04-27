from astropy.io import fits
from pyobs.utils.enums import ImageFormat
from pyobs.utils.gui.camera import (
    DataDisplayWidget,
    BinningWidget,
    ImageFormatWidget,
    ExposureTimeWidget,
    ExposeWidget,
    ListPickerDialog,
)
from pyobs.utils.gui.camera.windowingwidget import WindowingWidget
from pyobs.utils.parallel import event_wait
import asyncio
import sys
import qasync  # type: ignore
from PySide6 import QtWidgets

from .qhyccddriver import QHYCCDDriver, Control, set_log_level  # type: ignore


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, device_name: bytes) -> None:
        super().__init__()

        self.device = QHYCCDDriver(device_name)
        self.device.open()
        chip_info = self.device.get_chip_info()

        self.central_widget = QtWidgets.QWidget()
        self.setCentralWidget(self.central_widget)

        global_layout = QtWidgets.QHBoxLayout()
        self.central_widget.setLayout(global_layout)
        self.widgets_frame = QtWidgets.QGroupBox()
        # self.fits_widget = QFitsWidget()
        self.data_display_widget = DataDisplayWidget()
        global_layout.addWidget(self.widgets_frame)
        global_layout.addWidget(self.data_display_widget)

        layout = QtWidgets.QVBoxLayout()
        self.widgets_frame.setLayout(layout)
        self.window_widget = WindowingWidget(chip_info[2], chip_info[3])
        layout.addWidget(self.window_widget)
        self.binning_widget = BinningWidget([(1, 1)])
        self.binning_widget.binning_changed.connect(self.window_widget.set_binning)
        layout.addWidget(self.binning_widget)
        self.format_widget = ImageFormatWidget([ImageFormat.INT8, ImageFormat.INT16])
        layout.addWidget(self.format_widget)
        self.exposure_time = ExposureTimeWidget()
        layout.addWidget(self.exposure_time)
        self.expose = ExposeWidget()
        layout.addWidget(self.expose)

        self.abort_exposure = asyncio.Event()
        self.expose.expose_clicked.connect(self._expose_clicked)
        self.expose.abort_clicked.connect(self._abort_clicked)

    @qasync.asyncSlot()  # type: ignore
    async def _expose_clicked(self) -> None:
        self.device.set_resolution(*self.window_widget.values)
        self.device.set_param(Control.CONTROL_EXPOSURE, int(self.exposure_time.value * 1000.0 * 1000.0))

        if self.device.is_control_available(Control.CONTROL_TRANSFERBIT):
            if self.format_widget.value == ImageFormat.INT8:
                self.device.set_bits_mode(8)
            else:
                self.device.set_bits_mode(16)

        self.expose.start_exposure(self.exposure_time.value)
        abort_event = asyncio.Event()
        self.device.expose_single_frame()
        await event_wait(abort_event, self.exposure_time.value - 0.5)
        loop = asyncio.get_running_loop()
        image_data = await loop.run_in_executor(None, self.device.get_single_frame)
        self.expose.set_exposures_left()

        image = fits.PrimaryHDU(image_data)
        self.data_display_widget.set_data(image)

    @qasync.asyncSlot()  # type: ignore
    async def _abort_clicked(self) -> None:
        self.abort_exposure.set()
        self.abort_exposure = asyncio.Event()


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
    app = QtWidgets.QApplication(sys.argv)
    asyncio.run(async_main(app), loop_factory=qasync.QEventLoop)  # type: ignore


if __name__ == "__main__":
    main()
