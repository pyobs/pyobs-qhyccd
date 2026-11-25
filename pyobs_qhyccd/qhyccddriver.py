"""ctypes wrapper for the QHYCCD SDK.

The driver used to be a Cython extension with the SDK linked in statically, and closing the camera hung or crashed.
That was not the extension: CloseQHYCCD of SDK 25.9.29.10 calls pthread_join on a thread handle that it never set
(reproduced with MALLOC_PERTURB_=165, where the handle is 0x5A5A5A5A5A5A5A5A and the process segfaults in
pthread_join). Whether it works, hangs or crashes depends on what the heap happens to hold, and importing other
libraries (for example pycares) changes that. close() therefore does not call CloseQHYCCD by default, only
ReleaseQHYCCDResource; the handle is leaked until the process ends. Set QHYCCD_CALL_CLOSE=1 to call CloseQHYCCD anyway
(for an SDK that fixed this).

The library is loaded on first use. It is looked for at the path given to set_sdk_path() or load_library(), else in the
environment variable QHYCCD_SDK, else at DEFAULT_SDK_PATH.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import threading
from enum import Enum
from typing import Any

import numpy as np
from numpy.typing import NDArray

DEFAULT_SDK_PATH = "/usr/local/lib/libqhyccd.so"
SDK_ENV_VAR = "QHYCCD_SDK"
CALL_CLOSE_ENV_VAR = "QHYCCD_CALL_CLOSE"

# A QHY294PRO-M was seen to get into a state where every frame comes back as zeros, about 60 s after the exposure
# should have ended, while GetQHYCCDSingleFrame still reports success. Only unplugging USB and power brought it back.
# A real frame is never all zero (the bias is hundreds of ADU at any sensible offset), so such a frame is refused.
EMPTY_FRAME_MESSAGE = (
    "The camera returned an empty frame (all pixels zero). It probably hangs: unplug USB and power of the camera."
)


class EmptyFrameError(ValueError):
    """The SDK reported success but delivered a frame of zeros."""


# the SDK reports success as 0
_SUCCESS = 0
# the SDK writes camera IDs like "QHY294PROM-cfb85516525f0aced" into this; the SDK header says 32 bytes, the buffer is
# bigger to be safe
_ID_BUFFER_SIZE = 64


class Control(Enum):
    """Control IDs of the SDK (CONTROL_ID in qhyccdstruct.h). The values are 1-tuples, use value[0] for the ID."""

    CONTROL_BRIGHTNESS = (0,)
    CONTROL_CONTRAST = (1,)
    CONTROL_WBR = (2,)
    CONTROL_WBB = (3,)
    CONTROL_WBG = (4,)
    CONTROL_GAMMA = (5,)
    CONTROL_GAIN = (6,)
    CONTROL_OFFSET = (7,)
    CONTROL_EXPOSURE = (8,)
    CONTROL_SPEED = (9,)
    CONTROL_TRANSFERBIT = (10,)
    CONTROL_CHANNELS = (11,)
    CONTROL_USBTRAFFIC = (12,)
    CONTROL_ROWNOISERE = (13,)
    CONTROL_CURTEMP = (14,)
    CONTROL_CURPWM = (15,)
    CONTROL_MANULPWM = (16,)
    CONTROL_CFWPORT = (17,)
    CONTROL_COOLER = (18,)
    CONTROL_ST4PORT = (19,)
    CAM_COLOR = (20,)
    CAM_BIN1X1MODE = (21,)
    CAM_BIN2X2MODE = (22,)
    CAM_BIN3X3MODE = (23,)
    CAM_BIN4X4MODE = (24,)
    CAM_MECHANICALSHUTTER = (25,)
    CAM_TRIGER_INTERFACE = (26,)
    CAM_TECOVERPROTECT_INTERFACE = (27,)
    CAM_SINGNALCLAMP_INTERFACE = (28,)
    CAM_FINETONE_INTERFACE = (29,)
    CAM_SHUTTERMOTORHEATING_INTERFACE = (30,)
    CAM_CALIBRATEFPN_INTERFACE = (31,)
    CAM_CHIPTEMPERATURESENSOR_INTERFACE = (32,)
    CAM_USBREADOUTSLOWEST_INTERFACE = (33,)
    CAM_8BITS = (34,)
    CAM_16BITS = (35,)
    CAM_GPS = (36,)
    CAM_IGNOREOVERSCAN_INTERFACE = (37,)
    QHYCCD_3A_AUTOEXPOSURE = (39,)
    QHYCCD_3A_AUTOFOCUS = (40,)
    CONTROL_AMPV = (41,)
    CONTROL_VCAM = (42,)
    CAM_VIEW_MODE = (43,)
    CONTROL_CFWSLOTSNUM = (44,)
    IS_EXPOSING_DONE = (45,)
    ScreenStretchB = (46,)
    ScreenStretchW = (47,)
    CONTROL_DDR = (48,)
    CAM_LIGHT_PERFORMANCE_MODE = (49,)
    CAM_QHY5II_GUIDE_MODE = (50,)
    DDR_BUFFER_CAPACITY = (51,)
    DDR_BUFFER_READ_THRESHOLD = (52,)
    DefaultGain = (53,)
    DefaultOffset = (54,)
    OutputDataActualBits = (55,)
    OutputDataAlignment = (56,)
    CAM_SINGLEFRAMEMODE = (57,)
    CAM_LIVEVIDEOMODE = (58,)
    CAM_IS_COLOR = (59,)
    hasHardwareFrameCounter = (60,)
    CONTROL_MAX_ID = (94,)
    CAM_HUMIDITY = (62,)


_u32 = ctypes.c_uint32
_pu32 = ctypes.POINTER(ctypes.c_uint32)
_pdouble = ctypes.POINTER(ctypes.c_double)
_handle = ctypes.c_void_p

# name -> (restype, argtypes) of the SDK functions used here
_PROTOTYPES: dict[str, tuple[Any, list[Any]]] = {
    "SetQHYCCDLogLevel": (None, [ctypes.c_uint8]),
    "InitQHYCCDResource": (_u32, []),
    "ReleaseQHYCCDResource": (_u32, []),
    "ScanQHYCCD": (_u32, []),
    "GetQHYCCDId": (_u32, [_u32, ctypes.c_char_p]),
    "OpenQHYCCD": (_handle, [ctypes.c_char_p]),
    "CloseQHYCCD": (_u32, [_handle]),
    "SetQHYCCDStreamMode": (_u32, [_handle, ctypes.c_uint8]),
    "SetQHYCCDReadMode": (_u32, [_handle, _u32]),
    "InitQHYCCD": (_u32, [_handle]),
    "IsQHYCCDControlAvailable": (_u32, [_handle, ctypes.c_int]),
    "GetQHYCCDEffectiveArea": (_u32, [_handle, _pu32, _pu32, _pu32, _pu32]),
    "GetQHYCCDOverScanArea": (_u32, [_handle, _pu32, _pu32, _pu32, _pu32]),
    "GetQHYCCDChipInfo": (_u32, [_handle, _pdouble, _pdouble, _pu32, _pu32, _pdouble, _pdouble, _pu32]),
    "GetQHYCCDNumberOfReadModes": (_u32, [_handle, _pu32]),
    "GetQHYCCDReadModeName": (_u32, [_handle, _u32, ctypes.c_char_p]),
    "GetQHYCCDReadModeResolution": (_u32, [_handle, _u32, _pu32, _pu32]),
    "GetQHYCCDParamMinMaxStep": (_u32, [_handle, ctypes.c_int, _pdouble, _pdouble, _pdouble]),
    "GetQHYCCDParam": (ctypes.c_double, [_handle, ctypes.c_int]),
    "SetQHYCCDParam": (_u32, [_handle, ctypes.c_int, ctypes.c_double]),
    "ControlQHYCCDTemp": (_u32, [_handle, ctypes.c_double]),
    "SetQHYCCDResolution": (_u32, [_handle, _u32, _u32, _u32, _u32]),
    "SetQHYCCDBinMode": (_u32, [_handle, _u32, _u32]),
    "SetQHYCCDBitsMode": (_u32, [_handle, _u32]),
    "ExpQHYCCDSingleFrame": (_u32, [_handle]),
    "CancelQHYCCDExposingAndReadout": (_u32, [_handle]),
    "GetQHYCCDMemLength": (_u32, [_handle]),
    "GetQHYCCDSingleFrame": (_u32, [_handle, _pu32, _pu32, _pu32, _pu32, ctypes.c_void_p]),
    "BeginQHYCCDLive": (_u32, [_handle]),
    "StopQHYCCDLive": (_u32, [_handle]),
    "GetQHYCCDLiveFrame": (_u32, [_handle, _pu32, _pu32, _pu32, _pu32, ctypes.c_void_p]),
    "GetQHYCCDExposureRemaining": (_u32, [_handle]),
    "GetQHYCCDCameraStatus": (_u32, [_handle, ctypes.POINTER(ctypes.c_uint8)]),
}

# The SDK is not meant to be called from several threads at once, and the old extension held the GIL during every
# call, so the calls were serialized. ctypes releases the GIL, so the wrapper does the serializing itself.
_sdk_lock = threading.RLock()


def _call_close() -> bool:
    """Whether close() calls CloseQHYCCD (off by default, see the module docstring)."""
    return os.environ.get(CALL_CLOSE_ENV_VAR, "0") == "1"


_lib: ctypes.CDLL | None = None
_lib_path: str | None = None
_requested_path: str | None = None


def sdk_path(path: str | None = None) -> str:
    """Path of the SDK library: the argument, else the environment variable QHYCCD_SDK, else the default."""
    return path or os.environ.get(SDK_ENV_VAR) or DEFAULT_SDK_PATH


def set_sdk_path(path: str | None) -> None:
    """Choose the SDK library before it is loaded. None changes nothing (the environment variable or the default).

    Raises:
        ValueError: If the library was already loaded from another path (it is loaded once per process).
    """
    global _requested_path
    with _sdk_lock:
        if path is not None and _lib is not None and sdk_path(path) != _lib_path:
            raise ValueError(f"The QHYCCD SDK is already loaded from {_lib_path}, cannot use {path}.")
        if path is not None:
            _requested_path = path


def load_library(path: str | None = None) -> ctypes.CDLL:
    """Load the SDK library (once per process) and declare the functions used here.

    Args:
        path: Path of libqhyccd.so. None uses the path of set_sdk_path(), the environment variable or the default.

    Raises:
        OSError: If the library cannot be loaded.
        ValueError: If the library was already loaded from another path.
    """
    global _lib, _lib_path
    with _sdk_lock:
        wanted = sdk_path(path or _requested_path)
        if _lib is not None:
            if path is not None and wanted != _lib_path:
                raise ValueError(f"The QHYCCD SDK is already loaded from {_lib_path}, cannot use {path}.")
            return _lib
        try:
            lib = ctypes.CDLL(wanted)
        except OSError as e:
            found = ctypes.util.find_library("qhyccd") if wanted == DEFAULT_SDK_PATH else None
            if found is None:
                raise OSError(
                    f"Could not load the QHYCCD SDK from {wanted} ({e}). Install libqhyccd.so (see the README), or set "
                    f"the environment variable {SDK_ENV_VAR} or the sdk parameter to its path."
                ) from e
            lib = ctypes.CDLL(found)
            wanted = found
        for name, (restype, argtypes) in _PROTOTYPES.items():
            function = getattr(lib, name)
            function.restype = restype
            function.argtypes = argtypes
        _lib, _lib_path = lib, wanted
        return lib


def set_log_level(log_level: int) -> None:
    """Set the log level of the SDK (0 is quiet), loading the library if necessary."""
    with _sdk_lock:
        load_library().SetQHYCCDLogLevel(log_level)


class QHYCCDDriver:
    """Wrapper for the QHYCCD driver."""

    @staticmethod
    def list_devices() -> list[bytes]:
        """List all QHYCCD USB cameras connected to this computer.

        Returns:
            List of camera IDs.
        """
        with _sdk_lock:
            lib = load_library()
            if lib.InitQHYCCDResource() != _SUCCESS:
                raise ValueError("Could not init QHYCCD resource.")
            cam_count = lib.ScanQHYCCD()
            cameras = []
            for i in range(cam_count):
                cam_id = ctypes.create_string_buffer(_ID_BUFFER_SIZE)
                if lib.GetQHYCCDId(i, cam_id) == _SUCCESS:
                    cameras.append(cam_id.value)
            return cameras

    def __init__(self, cam_id: bytes) -> None:
        """Create a new driver object for the given ID.

        Args:
            cam_id: ID of camera to initialize.
        """
        self._cam_id = bytes(cam_id)
        self._handle: ctypes.c_void_p | None = None

    @property
    def _lib(self) -> ctypes.CDLL:
        return load_library()

    def _device(self) -> ctypes.c_void_p:
        if not self._handle:
            raise ValueError("The camera is not open.")
        return self._handle

    def open(self, live: bool = False, read_mode: int | None = None) -> None:
        """Open driver.

        The read mode and the stream mode are set before InitQHYCCD, as in the SDK's own samples, so switching between
        single-frame and live mode or between read modes means closing and re-opening.

        Args:
            live: Open in live (video) mode instead of single-frame mode.
            read_mode: Index of the read mode to use, see get_read_modes(). None leaves the default (mode 0).

        Raises:
            ValueError: If opening failed.
        """
        with _sdk_lock:
            lib = self._lib
            handle = ctypes.c_void_p(lib.OpenQHYCCD(self._cam_id))
            if not handle:
                raise ValueError("Could not open camera.")
            self._handle = handle

            try:
                if live:
                    if lib.IsQHYCCDControlAvailable(handle, Control.CAM_LIVEVIDEOMODE.value[0]) != _SUCCESS:
                        raise ValueError("Camera does not support live mode.")
                    if lib.SetQHYCCDStreamMode(handle, 1) != _SUCCESS:
                        raise ValueError("Could not set live mode.")
                else:
                    if lib.IsQHYCCDControlAvailable(handle, Control.CAM_SINGLEFRAMEMODE.value[0]) != _SUCCESS:
                        raise ValueError("Camera does not support single frames.")
                    if lib.SetQHYCCDStreamMode(handle, 0) != _SUCCESS:
                        raise ValueError("Could not set single frame mode.")

                # read mode, before init
                if read_mode is not None and lib.SetQHYCCDReadMode(handle, read_mode) != _SUCCESS:
                    raise ValueError(f"Could not set read mode {read_mode}.")

                if lib.InitQHYCCD(handle) != _SUCCESS:
                    raise ValueError("Could not initialize camera.")
            except ValueError:
                # do not leave a half-open camera behind
                self._close_quietly()
                raise

    def _close_quietly(self) -> None:
        if self._handle:
            if _call_close():
                self._lib.CloseQHYCCD(self._handle)
            self._lib.ReleaseQHYCCDResource()
            self._handle = None

    def close(self) -> None:
        """Close driver. Closing a camera that is not open does nothing.

        Raises:
            ValueError: If closing failed.
        """
        with _sdk_lock:
            if not self._handle:
                return
            handle, self._handle = self._handle, None
            lib = self._lib
            # CloseQHYCCD joins an uninitialized thread handle, see the module docstring
            result = lib.CloseQHYCCD(handle) if _call_close() else _SUCCESS
            lib.ReleaseQHYCCDResource()
            if result != _SUCCESS:
                raise ValueError("Could not close device.")

    def is_control_available(self, control: Control) -> bool:
        with _sdk_lock:
            return bool(self._lib.IsQHYCCDControlAvailable(self._device(), int(control.value[0])) == _SUCCESS)

    def _area(self, function_name: str, error: str) -> tuple[int, int, int, int]:
        x, y, width, height = (_u32() for _ in range(4))
        with _sdk_lock:
            function = getattr(self._lib, function_name)
            if function(
                self._device(), ctypes.pointer(x), ctypes.pointer(y), ctypes.pointer(width), ctypes.pointer(height)
            ):
                raise ValueError(error)
        return x.value, y.value, width.value, height.value

    def get_effective_area(self) -> tuple[int, int, int, int]:
        return self._area("GetQHYCCDEffectiveArea", "Could not fetch effective area.")

    def get_overscan_area(self) -> tuple[int, int, int, int]:
        return self._area("GetQHYCCDOverScanArea", "Could not fetch overscan area.")

    def get_chip_info(self) -> tuple[float, float, int, int, float, float]:
        """Chip width and height in mm, image width and height in pixels, pixel width and height in um."""
        chipw, chiph, pixelw, pixelh = (ctypes.c_double() for _ in range(4))
        imagew, imageh, bpp = (_u32() for _ in range(3))
        with _sdk_lock:
            result = self._lib.GetQHYCCDChipInfo(
                self._device(),
                ctypes.pointer(chipw),
                ctypes.pointer(chiph),
                ctypes.pointer(imagew),
                ctypes.pointer(imageh),
                ctypes.pointer(pixelw),
                ctypes.pointer(pixelh),
                ctypes.pointer(bpp),
            )
        if result != _SUCCESS:
            raise ValueError("Could not fetch chip info.")
        return chipw.value, chiph.value, imagew.value, imageh.value, pixelw.value, pixelh.value

    def get_read_modes(self) -> list[tuple[int, str, int, int]]:
        """Read modes of the camera.

        Returns:
            List of (index, name, width, height). Empty if the camera does not report read modes.
        """
        count = _u32()
        with _sdk_lock:
            lib, handle = self._lib, self._device()
            if lib.GetQHYCCDNumberOfReadModes(handle, ctypes.pointer(count)) != _SUCCESS:
                return []
            modes = []
            for i in range(count.value):
                name = ctypes.create_string_buffer(_ID_BUFFER_SIZE)
                width, height = _u32(), _u32()
                if lib.GetQHYCCDReadModeName(handle, i, name) != _SUCCESS:
                    continue
                if (
                    lib.GetQHYCCDReadModeResolution(handle, i, ctypes.pointer(width), ctypes.pointer(height))
                    != _SUCCESS
                ):
                    continue
                modes.append((i, name.value.decode("utf-8", "replace"), width.value, height.value))
            return modes

    def get_param_limits(self, param: Control) -> tuple[float, float, float] | None:
        """Minimum, maximum and step of a control, or None if the SDK does not tell."""
        vmin, vmax, vstep = (ctypes.c_double() for _ in range(3))
        with _sdk_lock:
            result = self._lib.GetQHYCCDParamMinMaxStep(
                self._device(), param.value[0], ctypes.pointer(vmin), ctypes.pointer(vmax), ctypes.pointer(vstep)
            )
        if result != _SUCCESS:
            return None
        return vmin.value, vmax.value, vstep.value

    def get_param(self, param: Control) -> float:
        with _sdk_lock:
            return float(self._lib.GetQHYCCDParam(self._device(), param.value[0]))

    def set_param(self, param: Control, value: float) -> None:
        with _sdk_lock:
            if self._lib.SetQHYCCDParam(self._device(), param.value[0], float(value)) != _SUCCESS:
                raise ValueError(f"Could not set parameter {param} to {value}.")

    def set_temperature(self, temperature: float) -> None:
        with _sdk_lock:
            if self._lib.ControlQHYCCDTemp(self._device(), float(temperature)) != _SUCCESS:
                raise ValueError(f"Could not set temperature to {temperature} °C")

    def set_resolution(self, x: int, y: int, width: int, height: int) -> None:
        with _sdk_lock:
            if self._lib.SetQHYCCDResolution(self._device(), x, y, width, height) != _SUCCESS:
                raise ValueError(f"Could not set resolution to {width}x{height} at {x},{y}.")

    def set_bin_mode(self, x: int, y: int) -> None:
        with _sdk_lock:
            if self._lib.SetQHYCCDBinMode(self._device(), x, y) != _SUCCESS:
                raise ValueError(f"Could not set binning to {x}x{y}.")

    def set_bits_mode(self, bits: int) -> None:
        with _sdk_lock:
            if self._lib.SetQHYCCDBitsMode(self._device(), bits) != _SUCCESS:
                raise ValueError(f"Could not set bpp to {bits}.")

    def expose_single_frame(self) -> int:
        with _sdk_lock:
            return int(self._lib.ExpQHYCCDSingleFrame(self._device()))

    def cancel_exposure(self) -> None:
        """Force-stop a running exposure without reading out its (incomplete) data.

        Raises:
            ValueError: If cancelling failed.
        """
        with _sdk_lock:
            if self._lib.CancelQHYCCDExposingAndReadout(self._device()) != _SUCCESS:
                raise ValueError("Could not cancel exposure.")

    def get_mem_length(self) -> int:
        """Size in bytes of the buffer needed for a frame."""
        with _sdk_lock:
            return int(self._lib.GetQHYCCDMemLength(self._device()))

    def get_single_frame(self) -> NDArray[np.uint16] | NDArray[np.uint8]:
        """Read the frame of the last exposure as (height, width), 16 bit unsigned (8 bit in 8 bit mode)."""
        with _sdk_lock:
            buffer = np.zeros(self.get_mem_length(), dtype=np.uint8)
            width, height, bpp, channels = (_u32() for _ in range(4))
            result = self._lib.GetQHYCCDSingleFrame(
                self._device(),
                ctypes.pointer(width),
                ctypes.pointer(height),
                ctypes.pointer(bpp),
                ctypes.pointer(channels),
                buffer.ctypes.data_as(ctypes.c_void_p),
            )
        if result != _SUCCESS:
            raise ValueError("Could not fetch image data.")
        pixels = width.value * height.value * channels.value
        if bpp.value == 8:
            frame = buffer[:pixels].reshape((height.value, width.value)).copy()
        else:
            frame = buffer[: pixels * 2].view(np.uint16).reshape((height.value, width.value)).copy()
        if not frame.any():
            raise EmptyFrameError(EMPTY_FRAME_MESSAGE)
        return frame

    def begin_live(self) -> None:
        """Start continuous exposures in live mode.

        Raises:
            ValueError: If starting failed.
        """
        with _sdk_lock:
            if self._lib.BeginQHYCCDLive(self._device()) != _SUCCESS:
                raise ValueError("Could not start live mode.")

    def stop_live(self) -> None:
        """Stop continuous exposures in live mode.

        Raises:
            ValueError: If stopping failed.
        """
        with _sdk_lock:
            if self._lib.StopQHYCCDLive(self._device()) != _SUCCESS:
                raise ValueError("Could not stop live mode.")

    def get_live_frame(self, buffer: Any) -> tuple[int, int, int, int] | None:
        """Fetch the next live frame into buffer, if there is one. Doesn't wait for a frame.

        Args:
            buffer: Writable, contiguous buffer (e.g. a uint8 numpy array) of at least get_mem_length() bytes.

        Returns:
            (width, height, bpp, channels) of the frame now in buffer, or None if no frame was
            ready (the SDK doesn't tell that apart from other failures).
        """
        view = memoryview(buffer).cast("B")
        if view.readonly:
            raise ValueError("Buffer for live frame must be writable.")
        with _sdk_lock:
            if view.nbytes < self.get_mem_length():
                raise ValueError("Buffer too small for live frame.")
            width, height, bpp, channels = (_u32() for _ in range(4))
            data = (ctypes.c_ubyte * view.nbytes).from_buffer(view)
            try:
                result = self._lib.GetQHYCCDLiveFrame(
                    self._device(),
                    ctypes.pointer(width),
                    ctypes.pointer(height),
                    ctypes.pointer(bpp),
                    ctypes.pointer(channels),
                    ctypes.addressof(data),
                )
            finally:
                del data
        if result != _SUCCESS:
            return None
        return width.value, height.value, bpp.value, channels.value

    def get_time_remaining(self) -> int:
        with _sdk_lock:
            return int(self._lib.GetQHYCCDExposureRemaining(self._device()))

    def get_status(self) -> int:
        status = ctypes.c_uint8()
        with _sdk_lock:
            self._lib.GetQHYCCDCameraStatus(self._device(), ctypes.pointer(status))
        return status.value
