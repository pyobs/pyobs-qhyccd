"""Tests of the ctypes wrapper with a fake SDK library, no camera needed."""

import ctypes
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from pyobs_qhyccd import qhyccddriver
from pyobs_qhyccd.qhyccddriver import Control, QHYCCDDriver

SINGLE_FRAME = Control.CAM_SINGLEFRAMEMODE.value[0]
LIVE = Control.CAM_LIVEVIDEOMODE.value[0]


class FakeSdk(SimpleNamespace):
    """Stands in for the ctypes library: records the calls, camera data are attributes."""

    def __init__(self, **overrides: Any) -> None:
        super().__init__(
            calls=[],
            ids=[b"QHY294PROM-abc"],
            fail={},
            frame=np.zeros((2, 3), dtype=np.uint16),
            bpp=16,
            live_ready=True,
            params={},
        )
        self.__dict__.update(overrides)

    def _call(self, name: str, *args: Any) -> int:
        self.calls.append((name, *args))
        return int(self.fail.get(name, 0))

    # resource
    def SetQHYCCDLogLevel(self, level: int) -> None:
        self._call("SetQHYCCDLogLevel", level)

    def InitQHYCCDResource(self) -> int:
        return self._call("InitQHYCCDResource")

    def ReleaseQHYCCDResource(self) -> int:
        return self._call("ReleaseQHYCCDResource")

    def ScanQHYCCD(self) -> int:
        self._call("ScanQHYCCD")
        return len(self.ids)

    def GetQHYCCDId(self, index: int, buffer: Any) -> int:
        buffer.value = self.ids[index]
        return self._call("GetQHYCCDId", index)

    # opening
    def OpenQHYCCD(self, cam_id: bytes) -> int | None:
        self.calls.append(("OpenQHYCCD", cam_id))
        return None if "OpenQHYCCD" in self.fail else 1234

    def CloseQHYCCD(self, handle: Any) -> int:
        return self._call("CloseQHYCCD")

    def IsQHYCCDControlAvailable(self, handle: Any, control: int) -> int:
        return self._call("IsQHYCCDControlAvailable", control)

    def SetQHYCCDStreamMode(self, handle: Any, mode: int) -> int:
        return self._call("SetQHYCCDStreamMode", mode)

    def SetQHYCCDReadMode(self, handle: Any, mode: int) -> int:
        return self._call("SetQHYCCDReadMode", mode)

    def InitQHYCCD(self, handle: Any) -> int:
        return self._call("InitQHYCCD")

    # information
    def GetQHYCCDEffectiveArea(self, handle: Any, x: Any, y: Any, w: Any, h: Any) -> int:
        x.contents.value, y.contents.value, w.contents.value, h.contents.value = 36, 28, 4164, 2795
        return self._call("GetQHYCCDEffectiveArea")

    def GetQHYCCDOverScanArea(self, handle: Any, x: Any, y: Any, w: Any, h: Any) -> int:
        return self._call("GetQHYCCDOverScanArea")

    def GetQHYCCDChipInfo(self, handle: Any, cw: Any, ch: Any, iw: Any, ih: Any, pw: Any, ph: Any, bpp: Any) -> int:
        cw.contents.value, ch.contents.value, iw.contents.value, ih.contents.value = 19.5, 13.2, 4164, 2822
        pw.contents.value, ph.contents.value, bpp.contents.value = 4.63, 4.63, 16
        return self._call("GetQHYCCDChipInfo")

    def GetQHYCCDNumberOfReadModes(self, handle: Any, count: Any) -> int:
        count.contents.value = 2
        return self._call("GetQHYCCDNumberOfReadModes")

    def GetQHYCCDReadModeName(self, handle: Any, mode: int, name: Any) -> int:
        name.value = [b"11M MODE", b"47M MODE"][mode]
        return self._call("GetQHYCCDReadModeName", mode)

    def GetQHYCCDReadModeResolution(self, handle: Any, mode: int, w: Any, h: Any) -> int:
        w.contents.value, h.contents.value = [(4164, 2822), (8336, 5648)][mode]
        return self._call("GetQHYCCDReadModeResolution", mode)

    # controls
    def GetQHYCCDParamMinMaxStep(self, handle: Any, control: int, vmin: Any, vmax: Any, vstep: Any) -> int:
        vmin.contents.value, vmax.contents.value, vstep.contents.value = 0.0, 3624.0, 1.0
        return self._call("GetQHYCCDParamMinMaxStep", control)

    def GetQHYCCDParam(self, handle: Any, control: int) -> float:
        self.calls.append(("GetQHYCCDParam", control))
        return float(self.params.get(control, 0.0))

    def SetQHYCCDParam(self, handle: Any, control: int, value: float) -> int:
        self.params[control] = value
        return self._call("SetQHYCCDParam", control, value)

    def ControlQHYCCDTemp(self, handle: Any, target: float) -> int:
        return self._call("ControlQHYCCDTemp", target)

    # frames
    def SetQHYCCDResolution(self, handle: Any, x: int, y: int, w: int, h: int) -> int:
        return self._call("SetQHYCCDResolution", x, y, w, h)

    def SetQHYCCDBinMode(self, handle: Any, x: int, y: int) -> int:
        return self._call("SetQHYCCDBinMode", x, y)

    def SetQHYCCDBitsMode(self, handle: Any, bits: int) -> int:
        return self._call("SetQHYCCDBitsMode", bits)

    def ExpQHYCCDSingleFrame(self, handle: Any) -> int:
        return self._call("ExpQHYCCDSingleFrame")

    def CancelQHYCCDExposingAndReadout(self, handle: Any) -> int:
        return self._call("CancelQHYCCDExposingAndReadout")

    def GetQHYCCDMemLength(self, handle: Any) -> int:
        return int(self.frame.nbytes) + 16

    def _write_frame(self, w: Any, h: Any, bpp: Any, channels: Any, address: Any) -> None:
        data = self.frame.tobytes()
        ctypes.memmove(address if isinstance(address, int) else address.value, data, len(data))
        h.contents.value, w.contents.value = self.frame.shape
        bpp.contents.value, channels.contents.value = self.bpp, 1

    def GetQHYCCDSingleFrame(self, handle: Any, w: Any, h: Any, bpp: Any, channels: Any, address: Any) -> int:
        self._write_frame(w, h, bpp, channels, address)
        return self._call("GetQHYCCDSingleFrame")

    def BeginQHYCCDLive(self, handle: Any) -> int:
        return self._call("BeginQHYCCDLive")

    def StopQHYCCDLive(self, handle: Any) -> int:
        return self._call("StopQHYCCDLive")

    def GetQHYCCDLiveFrame(self, handle: Any, w: Any, h: Any, bpp: Any, channels: Any, address: Any) -> int:
        if not self.live_ready:
            return 1
        self._write_frame(w, h, bpp, channels, address)
        return self._call("GetQHYCCDLiveFrame")

    def GetQHYCCDExposureRemaining(self, handle: Any) -> int:
        return 42

    def GetQHYCCDCameraStatus(self, handle: Any, status: Any) -> int:
        status.contents.value = 7
        return self._call("GetQHYCCDCameraStatus")


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> FakeSdk:
    fake = FakeSdk()
    monkeypatch.setattr(qhyccddriver, "_lib", fake)
    monkeypatch.setattr(qhyccddriver, "_lib_path", "/fake/libqhyccd.so")
    return fake


@pytest.fixture
def driver(sdk: FakeSdk) -> QHYCCDDriver:
    camera = QHYCCDDriver(b"QHY294PROM-abc")
    camera.open()
    sdk.calls.clear()
    return camera


def names(sdk: FakeSdk) -> list[str]:
    return [call[0] for call in sdk.calls]


def test_control_values_are_the_sdk_ids() -> None:
    assert Control.CONTROL_GAIN.value == (6,)
    assert Control.CONTROL_MANULPWM.value[0] == 16
    assert Control.CONTROL_COOLER.value[0] == 18
    assert Control.CAM_SINGLEFRAMEMODE.value[0] == 57
    assert Control.CAM_LIVEVIDEOMODE.value[0] == 58


def test_every_prototype_is_declared_with_the_right_argument_count() -> None:
    # the argument counts of the SDK header, a typo in a prototype would crash the process
    assert len(qhyccddriver._PROTOTYPES["GetQHYCCDSingleFrame"][1]) == 6
    assert len(qhyccddriver._PROTOTYPES["GetQHYCCDChipInfo"][1]) == 8
    assert qhyccddriver._PROTOTYPES["OpenQHYCCD"][0] is ctypes.c_void_p


def test_sdk_path_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(qhyccddriver.SDK_ENV_VAR, raising=False)
    assert qhyccddriver.sdk_path() == qhyccddriver.DEFAULT_SDK_PATH
    monkeypatch.setenv(qhyccddriver.SDK_ENV_VAR, "/env/lib.so")
    assert qhyccddriver.sdk_path() == "/env/lib.so"
    assert qhyccddriver.sdk_path("/arg/lib.so") == "/arg/lib.so"


def test_missing_library_gives_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qhyccddriver, "_lib", None)
    monkeypatch.setattr(qhyccddriver, "_requested_path", None)
    with pytest.raises(OSError, match="QHYCCD_SDK"):
        qhyccddriver.load_library("/nonexistent/libqhyccd.so")
    assert qhyccddriver._lib is None


def test_library_is_loaded_once(sdk: FakeSdk) -> None:
    assert qhyccddriver.load_library() is sdk
    assert qhyccddriver.load_library("/fake/libqhyccd.so") is sdk
    with pytest.raises(ValueError, match="already loaded"):
        qhyccddriver.load_library("/other/libqhyccd.so")
    with pytest.raises(ValueError, match="already loaded"):
        qhyccddriver.set_sdk_path("/other/libqhyccd.so")
    qhyccddriver.set_sdk_path(None)  # changes nothing


def test_set_log_level(sdk: FakeSdk) -> None:
    qhyccddriver.set_log_level(0)
    assert ("SetQHYCCDLogLevel", 0) in sdk.calls


def test_list_devices(sdk: FakeSdk) -> None:
    sdk.ids = [b"QHY294PROM-abc", b"QHY178M-def"]
    assert QHYCCDDriver.list_devices() == [b"QHY294PROM-abc", b"QHY178M-def"]
    assert names(sdk)[:2] == ["InitQHYCCDResource", "ScanQHYCCD"]


def test_list_devices_resource_error(sdk: FakeSdk) -> None:
    sdk.fail["InitQHYCCDResource"] = 1
    with pytest.raises(ValueError, match="init"):
        QHYCCDDriver.list_devices()


def test_open_sets_modes_before_init(sdk: FakeSdk) -> None:
    QHYCCDDriver(b"QHY294PROM-abc").open(read_mode=1)
    assert sdk.calls == [
        ("OpenQHYCCD", b"QHY294PROM-abc"),
        ("IsQHYCCDControlAvailable", SINGLE_FRAME),
        ("SetQHYCCDStreamMode", 0),
        ("SetQHYCCDReadMode", 1),
        ("InitQHYCCD",),
    ]


def test_open_live(sdk: FakeSdk) -> None:
    QHYCCDDriver(b"x").open(live=True)
    assert ("IsQHYCCDControlAvailable", LIVE) in sdk.calls
    assert ("SetQHYCCDStreamMode", 1) in sdk.calls
    assert not any(call[0] == "SetQHYCCDReadMode" for call in sdk.calls)


@pytest.mark.parametrize(
    ("failing", "live", "message"),
    [
        ("IsQHYCCDControlAvailable", False, "single frames"),
        ("IsQHYCCDControlAvailable", True, "live mode"),
        ("SetQHYCCDStreamMode", False, "single frame mode"),
        ("SetQHYCCDReadMode", False, "read mode"),
        ("InitQHYCCD", False, "initialize"),
    ],
)
def test_open_errors_close_the_camera(sdk: FakeSdk, failing: str, live: bool, message: str) -> None:
    sdk.fail[failing] = 1
    camera = QHYCCDDriver(b"x")
    with pytest.raises(ValueError, match=message):
        camera.open(live=live, read_mode=0)
    assert names(sdk)[-1] == "ReleaseQHYCCDResource"
    assert "CloseQHYCCD" not in names(sdk)
    with pytest.raises(ValueError, match="not open"):
        camera.get_param(Control.CONTROL_GAIN)


def test_open_fails_without_handle(sdk: FakeSdk) -> None:
    sdk.fail["OpenQHYCCD"] = 1
    with pytest.raises(ValueError, match="open camera"):
        QHYCCDDriver(b"x").open()


def test_close_skips_closeqhyccd_and_is_idempotent(sdk: FakeSdk, driver: QHYCCDDriver) -> None:
    driver.close()
    assert names(sdk) == ["ReleaseQHYCCDResource"]
    driver.close()
    assert names(sdk) == ["ReleaseQHYCCDResource"]


def test_close_calls_closeqhyccd_when_enabled(
    sdk: FakeSdk, driver: QHYCCDDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QHYCCD_CALL_CLOSE", "1")
    driver.close()
    assert names(sdk) == ["CloseQHYCCD", "ReleaseQHYCCDResource"]


def test_close_error(sdk: FakeSdk, driver: QHYCCDDriver, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QHYCCD_CALL_CLOSE", "1")
    sdk.fail["CloseQHYCCD"] = 1
    with pytest.raises(ValueError, match="close"):
        driver.close()
    assert names(sdk)[-1] == "ReleaseQHYCCDResource"


def test_closed_camera_refuses_calls(driver: QHYCCDDriver) -> None:
    driver.close()
    with pytest.raises(ValueError, match="not open"):
        driver.get_mem_length()


def test_information(driver: QHYCCDDriver) -> None:
    assert driver.get_effective_area() == (36, 28, 4164, 2795)
    assert driver.get_chip_info() == (19.5, 13.2, 4164, 2822, 4.63, 4.63)
    assert driver.get_read_modes() == [(0, "11M MODE", 4164, 2822), (1, "47M MODE", 8336, 5648)]
    assert driver.get_status() == 7
    assert driver.get_time_remaining() == 42


def test_area_error(sdk: FakeSdk, driver: QHYCCDDriver) -> None:
    sdk.fail["GetQHYCCDEffectiveArea"] = 1
    with pytest.raises(ValueError, match="effective area"):
        driver.get_effective_area()
    sdk.fail["GetQHYCCDOverScanArea"] = 1
    with pytest.raises(ValueError, match="overscan"):
        driver.get_overscan_area()


def test_read_modes_empty_without_support(sdk: FakeSdk, driver: QHYCCDDriver) -> None:
    sdk.fail["GetQHYCCDNumberOfReadModes"] = 1
    assert driver.get_read_modes() == []


def test_param_limits(sdk: FakeSdk, driver: QHYCCDDriver) -> None:
    assert driver.get_param_limits(Control.CONTROL_GAIN) == (0.0, 3624.0, 1.0)
    sdk.fail["GetQHYCCDParamMinMaxStep"] = 1
    assert driver.get_param_limits(Control.CONTROL_GAIN) is None


def test_params(sdk: FakeSdk, driver: QHYCCDDriver) -> None:
    driver.set_param(Control.CONTROL_GAIN, 10)
    assert ("SetQHYCCDParam", 6, 10.0) in sdk.calls
    assert driver.get_param(Control.CONTROL_GAIN) == 10.0
    assert driver.is_control_available(Control.CONTROL_GAIN)
    sdk.fail["SetQHYCCDParam"] = 1
    with pytest.raises(ValueError, match="CONTROL_GAIN"):
        driver.set_param(Control.CONTROL_GAIN, 5)
    sdk.fail["IsQHYCCDControlAvailable"] = 1
    assert not driver.is_control_available(Control.CONTROL_GAIN)


def test_settings_errors(sdk: FakeSdk, driver: QHYCCDDriver) -> None:
    driver.set_temperature(-5.0)
    driver.set_resolution(1, 2, 3, 4)
    driver.set_bin_mode(2, 2)
    driver.set_bits_mode(16)
    assert driver.expose_single_frame() == 0
    driver.cancel_exposure()
    assert ("SetQHYCCDResolution", 1, 2, 3, 4) in sdk.calls
    for name, call, message in [
        ("ControlQHYCCDTemp", lambda: driver.set_temperature(0), "temperature"),
        ("SetQHYCCDResolution", lambda: driver.set_resolution(0, 0, 1, 1), "resolution"),
        ("SetQHYCCDBinMode", lambda: driver.set_bin_mode(1, 1), "binning"),
        ("SetQHYCCDBitsMode", lambda: driver.set_bits_mode(8), "bpp"),
        ("CancelQHYCCDExposingAndReadout", driver.cancel_exposure, "cancel"),
    ]:
        sdk.fail[name] = 1
        with pytest.raises(ValueError, match=message):
            call()


def test_single_frame_16_bit(sdk: FakeSdk, driver: QHYCCDDriver) -> None:
    sdk.frame = np.arange(6, dtype=np.uint16).reshape(2, 3) + 1000
    frame = driver.get_single_frame()
    assert frame.dtype == np.uint16
    assert frame.shape == (2, 3)
    np.testing.assert_array_equal(frame, sdk.frame)


def test_single_frame_8_bit(sdk: FakeSdk, driver: QHYCCDDriver) -> None:
    sdk.frame = np.arange(6, dtype=np.uint8).reshape(2, 3)
    sdk.bpp = 8
    frame = driver.get_single_frame()
    assert frame.dtype == np.uint8
    np.testing.assert_array_equal(frame, sdk.frame)


@pytest.mark.parametrize("dtype", [np.uint16, np.uint8])
def test_single_frame_all_zero_is_refused(sdk: FakeSdk, driver: QHYCCDDriver, dtype: Any) -> None:
    # the SDK reports success, but a hanging camera delivers only zeros
    sdk.frame = np.zeros((2, 3), dtype=dtype)
    sdk.bpp = 8 if dtype == np.uint8 else 16
    with pytest.raises(qhyccddriver.EmptyFrameError, match="unplug USB and power"):
        driver.get_single_frame()


def test_single_frame_with_one_nonzero_pixel_is_accepted(sdk: FakeSdk, driver: QHYCCDDriver) -> None:
    sdk.frame = np.zeros((2, 3), dtype=np.uint16)
    sdk.frame[1, 2] = 1
    np.testing.assert_array_equal(driver.get_single_frame(), sdk.frame)


def test_single_frame_error(sdk: FakeSdk, driver: QHYCCDDriver) -> None:
    sdk.fail["GetQHYCCDSingleFrame"] = 1
    with pytest.raises(ValueError, match="image data"):
        driver.get_single_frame()


def test_live(sdk: FakeSdk, driver: QHYCCDDriver) -> None:
    driver.begin_live()
    sdk.frame = np.arange(6, dtype=np.uint8).reshape(2, 3)
    sdk.bpp = 8
    buffer = np.zeros(driver.get_mem_length(), dtype=np.uint8)
    assert driver.get_live_frame(buffer) == (3, 2, 8, 1)
    np.testing.assert_array_equal(buffer[:6], np.arange(6))
    sdk.live_ready = False
    assert driver.get_live_frame(buffer) is None
    with pytest.raises(ValueError, match="too small"):
        driver.get_live_frame(np.zeros(2, dtype=np.uint8))
    with pytest.raises(ValueError, match="writable"):
        driver.get_live_frame(bytes(100))
    driver.stop_live()
    sdk.fail["BeginQHYCCDLive"] = 1
    with pytest.raises(ValueError, match="start live"):
        driver.begin_live()
    sdk.fail["StopQHYCCDLive"] = 1
    with pytest.raises(ValueError, match="stop live"):
        driver.stop_live()
