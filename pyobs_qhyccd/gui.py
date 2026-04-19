import asyncio
import sys

import qasync
from PySide6 import QtWidgets, QtCore
from qfitswidget import QFitsWidget

from .qhyccddriver import QHYCCDDriver, Control, set_log_level  # type: ignore


class ExposeWidget(QtWidgets.QGroupBox):
    expose_clicked = QtCore.Signal()
    abort_clicked = QtCore.Signal()

    def __init__(self, can_abort: bool = True):
        super().__init__("Expose")
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)
        self.button = QtWidgets.QPushButton("Expose")
        layout.addWidget(self.button)



class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
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


async def main(app: QtWidgets.QApplication) -> None:
    #connect()
    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)
    main_window = MainWindow()
    main_window.show()
    await app_close_event.wait()

def connect():
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

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    asyncio.run(main(app), loop_factory=qasync.QEventLoop)