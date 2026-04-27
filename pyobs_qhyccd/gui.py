import os

import numpy as np
from astropy.io import fits

from pyobs.utils.enums import ImageFormat
from pyobs.utils.parallel import event_wait
from time import time
import asyncio
import sys
import qasync  # type: ignore
from PySide6 import QtWidgets, QtCore, QtGui
from qfitswidget import QFitsWidget

from .qhyccddriver import QHYCCDDriver, Control, set_log_level  # type: ignore


class WindowWidget(QtWidgets.QGroupBox):
    window_changed = QtCore.Signal(int, int, int, int)

    def __init__(self, max_width: int, max_height: int) -> None:
        super().__init__()

        self._max_width = max_width
        self._max_height = max_height
        self._binning = (1, 1)

        layout = QtWidgets.QFormLayout()
        self.setLayout(layout)

        self.spin_left = QtWidgets.QSpinBox()
        self.spin_left.setMinimum(0)
        self.spin_left.valueChanged.connect(self._update_min_max)
        layout.addRow("Left:", self.spin_left)
        self.spin_top = QtWidgets.QSpinBox()
        self.spin_top.setMinimum(0)
        self.spin_top.valueChanged.connect(self._update_min_max)
        layout.addRow("Top:", self.spin_top)
        self.spin_width = QtWidgets.QSpinBox()
        self.spin_width.setMinimum(1)
        layout.addRow("Width:", self.spin_width)
        self.spin_height = QtWidgets.QSpinBox()
        self.spin_height.setMinimum(1)
        layout.addRow("Height:", self.spin_height)

        self.button = QtWidgets.QPushButton("Full Frame")
        self.button.clicked.connect(self.full_frame)
        layout.addRow(self.button)

        self._signal_timer = QtCore.QTimer()
        self._signal_timer.setSingleShot(True)
        self._signal_timer.timeout.connect(self._emit_signal)
        self.spin_left.valueChanged.connect(lambda: self._signal_timer.start(500))
        self.spin_top.valueChanged.connect(lambda: self._signal_timer.start(500))
        self.spin_width.valueChanged.connect(lambda: self._signal_timer.start(500))
        self.spin_height.valueChanged.connect(lambda: self._signal_timer.start(500))

        self._update_min_max()
        self.full_frame()

    @property
    def left(self) -> int:
        return self.spin_left.value()

    @property
    def top(self) -> int:
        return self.spin_left.value()

    @property
    def width(self) -> int:
        return self.spin_width.value()

    @property
    def height(self) -> int:
        return self.spin_height.value()

    @property
    def values(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.width, self.height

    @property
    def max_width(self) -> int:
        return self._max_width

    @max_width.setter
    def max_width(self, value: int) -> None:
        self._max_width = value
        self._update_min_max()

    @property
    def max_height(self) -> int:
        return self._max_height

    @max_height.setter
    def max_height(self, value: int) -> None:
        self._max_height = value
        self._update_min_max()

    @property
    def binning(self) -> tuple[int, int]:
        return self._binning

    @QtCore.Slot(int, int)
    def set_binning(self, x: int, y: int) -> None:
        self._binning = (x, y)
        self._update_min_max()
        self.full_frame()

    @property
    def binned_width(self) -> int:
        return self._max_width // self.binning[0]

    @property
    def binned_height(self) -> int:
        return self._max_height // self.binning[1]

    @QtCore.Slot()
    def _update_min_max(self) -> None:
        self.spin_left.setMaximum(self.binned_width)
        self.spin_top.setMaximum(self.binned_height)
        self.spin_width.setMaximum(self.binned_width - self.spin_left.value())
        self.spin_height.setMaximum(self.binned_height - self.spin_top.value())

    @QtCore.Slot()
    def full_frame(self) -> None:
        self.spin_left.setValue(0)
        self.spin_top.setValue(0)
        self.spin_width.setValue(self.binned_width)
        self.spin_height.setValue(self.binned_height)

    def _emit_signal(self) -> None:
        self.window_changed.emit(
            self.spin_left.value(), self.spin_top.value(), self.spin_width.value(), self.spin_height.value()
        )


class BinningWidget(QtWidgets.QGroupBox):
    binning_changed = QtCore.Signal(int, int)

    def __init__(self, binnings: list[tuple[int, int]]) -> None:
        super().__init__()

        self._binnings = binnings

        layout = QtWidgets.QFormLayout()
        self.setLayout(layout)

        self.combo_binnings = QtWidgets.QComboBox()
        self.combo_binnings.addItems([f"{b[0]}x{b[1]}" for b in binnings])
        self.combo_binnings.setCurrentIndex(0)
        self.combo_binnings.currentIndexChanged.connect(self._binning_changed)
        layout.addRow("Binning:", self.combo_binnings)

    def _binning_changed(self, index: int) -> None:
        self.binning_changed.emit(*self._binnings[index])


class ExposureTimeWidget(QtWidgets.QGroupBox):
    exposure_time_changed = QtCore.Signal(float)

    def __init__(self, max_exposure_time_sec: float = 9999.99) -> None:
        super().__init__()

        layout = QtWidgets.QFormLayout()
        self.setLayout(layout)

        self.spin_exposure_time = QtWidgets.QDoubleSpinBox()
        self.spin_exposure_time.setRange(0, max_exposure_time_sec)
        self.spin_exposure_time.valueChanged.connect(self._exposure_time_changed)
        layout.addRow("ExpTime:", self.spin_exposure_time)

    @QtCore.Slot(float)
    def _exposure_time_changed(self, value: float) -> None:
        self.exposure_time_changed.emit(value)

    @property
    def value(self) -> float:
        return self.spin_exposure_time.value()


class FormatWidget(QtWidgets.QGroupBox):
    format_changed = QtCore.Signal(ImageFormat)

    def __init__(self, formats: list[ImageFormat]) -> None:
        super().__init__()

        self._formats = formats

        layout = QtWidgets.QFormLayout()
        self.setLayout(layout)

        self.combo_formats = QtWidgets.QComboBox()
        self.combo_formats.addItems([f"{f.name}" for f in formats])
        self.combo_formats.setCurrentIndex(0)
        self.combo_formats.currentIndexChanged.connect(self._format_changed)
        layout.addRow("Format:", self.combo_formats)

    @property
    def value(self) -> ImageFormat:
        return self._formats[self.combo_formats.currentIndex()]

    def _format_changed(self, index: int) -> None:
        self.format_changed.emit(self._formats[index])


class ExposeWidget(QtWidgets.QGroupBox):
    expose_clicked = QtCore.Signal(int)
    abort_clicked = QtCore.Signal()

    def __init__(self, can_abort_exposure: bool = True, can_progress: bool = True):
        super().__init__()

        self._can_abort_exposure = can_abort_exposure
        self._exposures_left = 1
        self._exposing = False
        self._progress = 0.0
        self._exposure_time = 0.0
        self._exposure_start = 0.0

        layout = QtWidgets.QFormLayout()
        self.setLayout(layout)

        self.spin_count = QtWidgets.QSpinBox()
        self.spin_count.setMinimum(1)
        self.spin_count.setMaximum(9999)
        layout.addRow("Count:", self.spin_count)

        self.button = QtWidgets.QPushButton("Expose")
        self.button.setStyleSheet("background-color: lime; color: black;")
        self.button.clicked.connect(self._button_clicked)
        layout.addRow(self.button)

        self.progress_bar = QtWidgets.QProgressBar()
        layout.addRow(self.progress_bar)

        self.label_exposures_left = QtWidgets.QLabel("Exposures")
        self.label_exposures_left.setVisible(False)
        layout.addRow(self.label_exposures_left)

        self.progress_timer = QtCore.QTimer()
        self.progress_timer.setInterval(100)
        self.progress_timer.timeout.connect(self._progress_timer_update)

    def _update_gui(self) -> None:
        if self._exposing:
            if self._exposures_left > 1:
                self.button.setText("Abort sequence")
                self.button.setStyleSheet("background-color: red; color: black;")
            else:
                if self._can_abort_exposure:
                    self.button.setText("Abort")
                    self.button.setStyleSheet("background-color: red; color: black;")
                else:
                    self.button.setStyleSheet("")
                    self.button.setEnabled(False)
        else:
            self.button.setEnabled(True)
            self.button.setText("Expose")
            self.button.setStyleSheet("background-color: lime; color: black;")

        self.label_exposures_left.setVisible(self._exposures_left > 1)
        self.label_exposures_left.setText(f"Exposures left: {self._exposures_left}")

    @QtCore.Slot()
    def _button_clicked(self) -> None:
        if self._exposing:
            self.abort_clicked.emit()
        else:
            self._exposing = True
            self._exposures_left = self.spin_count.value()
            self.progress_bar.setValue(0)
            self._update_gui()
            self.expose_clicked.emit(self.spin_count.value())

    @QtCore.Slot()
    def set_exposures_left(self, exposures_left: int = 0) -> None:
        self._exposing = exposures_left > 0
        self._exposures_left = exposures_left
        self.progress_timer.stop()
        self.progress_bar.setValue(0)
        self._update_gui()

    @QtCore.Slot()
    def start_exposure(self, exposure_time: float) -> None:
        self._exposure_time = exposure_time
        self._exposure_start = time()
        self.progress_timer.start()

    @QtCore.Slot()
    def _progress_timer_update(self) -> None:
        done = min(100.0, (time() - self._exposure_start) / self._exposure_time * 100.0)
        self.progress_bar.setValue(int(done))

    @QtCore.Slot()
    def set_progress(self, progress: float = 0.0) -> None:
        self._progress = progress
        self.progress_bar.setValue(int(self._progress))


class DataDisplayWidget(QtWidgets.QWidget):  # type: ignore
    signal_update_gui = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()

        self.vertical_layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.vertical_layout)
        self.tab_widget = QtWidgets.QTabWidget()
        self.vertical_layout.addWidget(self.tab_widget)

        # image
        self.fits_widget = QFitsWidget()
        self.tab_widget.addTab(self.fits_widget, "Image")

        # fits header
        self.tab_fits_header = QtWidgets.QWidget()
        self.tab_fits_header_layout = QtWidgets.QVBoxLayout(self.tab_fits_header)
        self.tab_fits_header_layout.setContentsMargins(0, 0, 0, 0)
        self.table_fits_header = QtWidgets.QTableWidget(self.tab_fits_header)
        self.table_fits_header.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_fits_header.setAlternatingRowColors(True)
        self.table_fits_header.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table_fits_header.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_fits_header.horizontalHeader().setStretchLastSection(True)
        self.table_fits_header.verticalHeader().setVisible(False)
        self.tab_fits_header_layout.addWidget(self.table_fits_header)
        self.tab_widget.addTab(self.tab_fits_header, "FITS header")

        # toolbar
        self.toolbar_layout = QtWidgets.QHBoxLayout()
        self.check_auto_save = QtWidgets.QCheckBox("Auto save:")
        self.toolbar_layout.addWidget(self.check_auto_save)
        self.text_autosave_path = QtWidgets.QLineEdit()
        self.text_autosave_path.setEnabled(False)
        self.toolbar_layout.addWidget(self.text_autosave_path)
        self.button_autosave = QtWidgets.QToolButton()
        self.button_autosave.setText("...")
        self.button_autosave.setEnabled(False)
        self.toolbar_layout.addWidget(self.button_autosave)
        self.toolbar_spacer = QtWidgets.QSpacerItem(
            40, 20, QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Minimum
        )
        self.toolbar_layout.addItem(self.toolbar_spacer)
        self.button_save_to = QtWidgets.QToolButton()
        self.button_save_to.setText("Save to...")
        self.button_save_to.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button_save_to.setEnabled(False)
        self.toolbar_layout.addWidget(self.button_save_to)
        self.vertical_layout.addLayout(self.toolbar_layout)
        self.tab_widget.setCurrentIndex(0)

        # set headers for fits header tab
        self.table_fits_header.setColumnCount(3)
        self.table_fits_header.setHorizontalHeaderLabels(["Key", "Value", "Comment"])

        # connect signals
        # self.signal_update_gui.connect(self.update_gui)
        self.check_auto_save.stateChanged.connect(lambda x: self.text_autosave_path.setEnabled(x))
        self.check_auto_save.stateChanged.connect(lambda x: self.button_autosave.setEnabled(x))
        self.button_autosave.clicked.connect(self.select_autosave_path)
        self.button_save_to.clicked.connect(self.save_data)

        # variables
        self._count = 0
        self.data: fits.ImageHDU | None = None

    def set_data(self, data: fits.ImageHDU) -> None:
        """Show data."""
        self.button_save_to.setEnabled(True)
        self.data = data
        self.data.header["FNAME"] = f"image_{self._count:04d}.fits"
        self._count += 1
        self.fits_widget.display(self.data)
        self._show_fits_headers()
        if self.check_auto_save.isChecked():
            self._auto_save()

    def _show_fits_headers(self) -> None:
        # get all header cards
        headers = {}
        for card in self.data.header.cards:
            headers[card.keyword] = (card.value, card.comment)

        # prepare table
        self.table_fits_header.setRowCount(len(headers))

        # set headers
        for i, key in enumerate(sorted(headers.keys())):
            self.table_fits_header.setItem(i, 0, QtWidgets.QTableWidgetItem(key))
            self.table_fits_header.setItem(i, 1, QtWidgets.QTableWidgetItem(str(headers[key][0])))
            self.table_fits_header.setItem(i, 2, QtWidgets.QTableWidgetItem(headers[key][1]))

        # adjust column widths
        self.table_fits_header.resizeColumnToContents(0)
        self.table_fits_header.resizeColumnToContents(1)

    def _auto_save(self) -> None:
        # autosave?
        path = self.text_autosave_path.text()

        # get path and check
        if not os.path.exists(path):
            print("Invalid path for auto-saving.")

        else:
            # save image
            filename = os.path.join(path, self.data.header["FNAME"])
            fits.writeto(filename, self.data.data, self.data.header, overwrite=True)

    @QtCore.Slot()  # type: ignore
    def select_autosave_path(self) -> None:
        """Select path for auto-saving."""

        # ask for path
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Directory")

        # set it
        if path:
            self.text_autosave_path.setText(path)
        else:
            self.text_autosave_path.clear()

    @QtCore.Slot()  # type: ignore
    def save_data(self) -> None:
        """Save image."""

        # get initial filename
        init_filename = "image.fits"

        # ask for filename
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save image", init_filename, "FITS Files (*.fits *.fits.gz)"
        )

        # save
        if filename:
            fits.writeto(filename, self.data.data, self.data.header, overwrite=True)


class ListPickerDialog(QtWidgets.QDialog):
    def __init__(self, items: list[str]):
        super().__init__()

        layout = QtWidgets.QHBoxLayout()
        self.setLayout(layout)

        self.combo_box = QtWidgets.QComboBox()
        self.combo_box.addItems(items)
        layout.addWidget(self.combo_box)

        self.button = QtWidgets.QPushButton("ok")
        layout.addWidget(self.button)
        self.button.clicked.connect(self.accept)

    def comboBox(self) -> QtWidgets.QComboBox:
        return self.combo_box


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
        self.window_widget = WindowWidget(chip_info[2], chip_info[3])
        layout.addWidget(self.window_widget)
        self.binning_widget = BinningWidget([(1, 1)])
        self.binning_widget.binning_changed.connect(self.window_widget.set_binning)
        layout.addWidget(self.binning_widget)
        self.format_widget = FormatWidget([ImageFormat.INT8, ImageFormat.INT16])
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
