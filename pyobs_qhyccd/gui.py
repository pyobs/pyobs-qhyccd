from pyobs.utils.parallel import event_wait
from time import time

import asyncio
import sys

import qasync  # type: ignore
from PySide6 import QtWidgets, QtCore
from qfitswidget import QFitsWidget

from .qhyccddriver import QHYCCDDriver, set_log_level  # type: ignore


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


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.central_widget = QtWidgets.QWidget()
        self.setCentralWidget(self.central_widget)

        global_layout = QtWidgets.QHBoxLayout()
        self.central_widget.setLayout(global_layout)
        self.widgets_frame = QtWidgets.QGroupBox()
        self.fits_widget = QFitsWidget()
        global_layout.addWidget(self.widgets_frame)
        global_layout.addWidget(self.fits_widget)

        layout = QtWidgets.QVBoxLayout()
        self.widgets_frame.setLayout(layout)
        self.expose = ExposeWidget()
        layout.addWidget(self.expose)

        self.abort_exposure = asyncio.Event()
        self.expose.expose_clicked.connect(self._expose_clicked)
        self.expose.abort_clicked.connect(self._abort_clicked)

    @qasync.asyncSlot()  # type: ignore
    async def _expose_clicked(self) -> None:
        self.expose.start_exposure(5)
        await event_wait(self.abort_exposure, 7)
        # for i in range(10):
        #    await asyncio.sleep(1)
        #    self.expose.set_progress(i * 10)
        self.expose.set_exposures_left()

    @qasync.asyncSlot()  # type: ignore
    async def _abort_clicked(self) -> None:
        self.abort_exposure.set()
        self.abort_exposure = asyncio.Event()


async def main(app: QtWidgets.QApplication) -> None:
    # connect()
    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)
    main_window = MainWindow()
    main_window.show()
    await app_close_event.wait()


def connect() -> None:
    # get devices
    set_log_level(0)  # TODO:
    devices = QHYCCDDriver.list_devices()
    if len(devices) == 0:
        return None

    # print and prompt
    print(f"Found {len(devices)} QHYCCD devices:")
    for i, d in enumerate(devices, 1):
        name = d.decode("utf-8")
        print(f"{i}. {name}")
    print("0. Quit")
    print("Select device:")


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    asyncio.run(main(app), loop_factory=qasync.QEventLoop)  # type: ignore
