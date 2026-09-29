import asyncio
import logging
import threading
import time
from collections.abc import AsyncGenerator, Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pyobs.images import Image
from pyobs.interfaces import (
    Binning,
    BinningCapabilities,
    BinningState,
    ExposureTimeState,
    GainState,
    IBinning,
    IExposureTime,
    IGain,
    IImageFormat,
    ImageFormatCapabilities,
    ImageFormatState,
    IWindow,
    WindowCapabilities,
    WindowState,
)
from pyobs.modules.camera import BaseVideo, Frame
from pyobs.utils.enums import ImageFormat, ImageType

from .blocking import SDK_CALL_TIMEOUT, BlockingSdkMixin
from .qhyccddriver import Control, QHYCCDDriver, set_log_level  # type: ignore

log = logging.getLogger(__name__)

# image format -> bits per pixel
VIDEO_FORMATS = {
    ImageFormat.INT8: 8,
    ImageFormat.INT16: 16,
}

# GetQHYCCDLiveFrame() doesn't wait for a frame, so the reader thread polls it, sleeping this long
# (outside the driver lock) whenever no frame was ready
_POLL_INTERVAL = 0.005

# frames() warns if no frame arrived for this long, on top of the exposure time
_FRAME_WAIT_MARGIN = 30.0

# frames queued between the reader thread and the event loop; latest wins beyond that
_QUEUE_SIZE = 5


class QHYCCDVideo(BlockingSdkMixin, BaseVideo, IExposureTime, IGain, IWindow, IBinning, IImageFormat):
    """A pyobs module streaming video from QHYCCD cameras in live mode.

    The camera is opened in live mode for the lifetime of the module and exposes continuously while
    the module is active. For long single exposures, use :class:`~pyobs_qhyccd.QHYCCDCamera`
    instead; only one of them can hold the camera at a time.

    The SDK gives no per-frame timestamp in live mode, so exposure start times are estimated from
    the arrival time, the exposure time and the ``readout_time`` parameter of
    :class:`~pyobs.modules.camera.BaseVideo`, which should be set for the sensor in use.
    """

    __module__ = "pyobs_qhyccd"

    def __init__(
        self,
        device: str | None = None,
        exposure_time: float = 0.1,
        gain: float = 10,
        offset: float = 140,
        image_format: ImageFormat | str = ImageFormat.INT16,
        usb_traffic: int | None = 60,
        **kwargs: Any,
    ):
        """Initializes a new QHYCCDVideo.

        Args:
            device: ID of the camera to use, as listed by the SDK. None uses the first camera found.
            exposure_time: Initial exposure time in seconds, also restored by reset().
            gain: Initial gain, also restored by reset().
            offset: Initial offset, also restored by reset().
            image_format: Initial image format (int8 or int16), also restored by reset().
            usb_traffic: Value for the camera's USB traffic control, if it has one. Higher values
                lower the frame rate but make transfers more reliable. None leaves it untouched.
        """
        BaseVideo.__init__(self, **kwargs)

        self._device = device
        self._usb_traffic = usb_traffic
        self._driver: QHYCCDDriver | None = None
        self._buffer: NDArray[np.uint8] | None = None
        self._pixel_size: float | None = None
        self._has_gain = False
        self._has_offset = False
        self._has_bits = False

        self._default_exposure_time = exposure_time
        self._default_gain = gain
        self._default_offset = offset
        self._default_image_format = ImageFormat(image_format)
        if self._default_image_format not in VIDEO_FORMATS:
            raise ValueError(f"Unsupported image format: {image_format}")

        self._exposure_time = exposure_time
        self._gain = gain
        self._offset = offset
        self._image_format = self._default_image_format
        self._window = (0, 0, 0, 0)
        self._binning = (1, 1)

        # serializes all SDK calls, from _run_blocking() and from the reader thread in frames()
        self._driver_lock = threading.Lock()
        # generation bumps come from SDK threads (under _driver_lock) and from the event loop
        self._generation_lock = threading.Lock()
        # set while _apply_settings() waits for _driver_lock, so the reader thread lets it in
        self._settings_pending = threading.Event()
        # whether frames() has live mode running, so _apply_settings() knows to restart it
        self._capturing = False

    async def open(self) -> None:
        """Open module."""

        def _connect() -> tuple[QHYCCDDriver, tuple[Any, ...], list[Binning]]:
            set_log_level(0)

            devices = QHYCCDDriver.list_devices()
            if not devices:
                raise ValueError("No cameras found.")
            if self._device is None:
                device = devices[0]
            elif self._device.encode() in devices:
                device = self._device.encode()
            else:
                raise ValueError(f"Camera {self._device} not found, available: {devices}")

            driver = QHYCCDDriver(device)
            driver.open(live=True)

            if driver.is_control_available(Control.CAM_COLOR):
                raise ValueError("Color cams are not supported.")
            if self._usb_traffic is not None and driver.is_control_available(Control.CONTROL_USBTRAFFIC):
                driver.set_param(Control.CONTROL_USBTRAFFIC, self._usb_traffic)
            self._has_gain = driver.is_control_available(Control.CONTROL_GAIN)
            self._has_offset = driver.is_control_available(Control.CONTROL_OFFSET)
            self._has_bits = driver.is_control_available(Control.CONTROL_TRANSFERBIT)

            binnings = [
                Binning(x=b, y=b)
                for b, control in [
                    (1, Control.CAM_BIN1X1MODE),
                    (2, Control.CAM_BIN2X2MODE),
                    (3, Control.CAM_BIN3X3MODE),
                    (4, Control.CAM_BIN4X4MODE),
                ]
                if driver.is_control_available(control)
            ]

            return driver, driver.get_chip_info(), binnings

        self._driver, chip, binnings = await self._run_blocking_or_raise(_connect)
        log.info("Chip  size: %.3fx%.3f [mm]", chip[0], chip[1])
        log.info("Pixel size: %.3fx%.3f [um]", chip[4], chip[5])
        log.info("Image size: %dx%d", chip[2], chip[3])
        self._pixel_size = chip[4] / 1000.0
        self._window = (0, 0, chip[2], chip[3])
        await self._apply_settings()

        await BaseVideo.open(self)

        # publish capabilities
        await self.comm.set_capabilities(
            IWindow,
            WindowCapabilities(full_frame_x=0, full_frame_y=0, full_frame_width=chip[2], full_frame_height=chip[3]),
        )
        await self.comm.set_capabilities(IBinning, BinningCapabilities(binnings=binnings))
        formats: list[str] = list(VIDEO_FORMATS.keys()) if self._has_bits else [self._image_format]
        await self.comm.set_capabilities(IImageFormat, ImageFormatCapabilities(image_formats=formats))

        # publish initial states
        await self._publish_states()

        # start streaming
        await self.activate_camera()

    async def close(self) -> None:
        """Close the module."""
        await BaseVideo.close(self)

        driver, self._driver = self._driver, None
        if driver is not None:
            if not await self._run_blocking(driver.close):
                log.error("Timed out closing QHYCCD camera after %.1fs.", SDK_CALL_TIMEOUT)

    async def _publish_states(self) -> None:
        await self.comm.set_state(IExposureTime, ExposureTimeState(exposure_time=self._exposure_time))
        await self.comm.set_state(IGain, GainState(gain=self._gain, offset=self._offset))
        await self.comm.set_state(IWindow, WindowState(*self._window))
        await self.comm.set_state(IBinning, BinningState(x=self._binning[0], y=self._binning[1]))
        await self.comm.set_state(IImageFormat, ImageFormatState(image_format=self._image_format))

    def _new_generation(self) -> int:
        """Start a new settings generation, thread-safe (called from SDK threads, too)."""
        with self._generation_lock:
            return super()._new_generation()

    def _configure(self, driver: QHYCCDDriver) -> None:
        """Write the current settings to the camera. Called under the driver lock, with live mode stopped.

        The window is given in unbinned pixels and converted to binned ones for the SDK, after the
        bin mode is set. The frame buffer is re-allocated, since its required size depends on the
        settings.
        """
        bx, by = self._binning
        driver.set_bin_mode(bx, by)
        driver.set_resolution(
            self._window[0] // bx, self._window[1] // by, self._window[2] // bx, self._window[3] // by
        )
        if self._has_bits:
            driver.set_bits_mode(VIDEO_FORMATS[self._image_format])
        driver.set_param(Control.CONTROL_EXPOSURE, int(self._exposure_time * 1e6))
        if self._has_gain:
            driver.set_param(Control.CONTROL_GAIN, self._gain)
        if self._has_offset:
            driver.set_param(Control.CONTROL_OFFSET, self._offset)

        # the camera may round the exposure time
        self._exposure_time = float(driver.get_param(Control.CONTROL_EXPOSURE)) / 1e6
        self._buffer = np.empty(driver.get_mem_length(), dtype=np.uint8)
        self._new_generation()

    async def _apply_settings(self) -> None:
        """Write the current settings to the camera and start a new settings generation.

        Restarts a running live mode around it. Does nothing before open(), which applies the
        settings itself.

        Raises:
            TimeoutError: If the SDK didn't respond in time.
        """

        def _apply() -> None:
            driver = self._driver
            if driver is None:
                return
            if self._capturing:
                driver.stop_live()
            try:
                self._configure(driver)
            finally:
                if self._capturing:
                    driver.begin_live()

        self._settings_pending.set()
        try:
            await self._run_blocking_or_raise(_apply)
        finally:
            self._settings_pending.clear()

    @staticmethod
    def _to_image(buffer: NDArray[np.uint8], width: int, height: int, bpp: int) -> NDArray[Any]:
        """Copy a frame out of the (reused) live buffer into its own array."""
        dtype = np.uint16 if bpp > 8 else np.uint8
        return np.frombuffer(buffer, dtype=dtype, count=width * height).reshape((height, width)).copy()

    async def frames(self) -> AsyncGenerator[Frame, None]:
        """Start live mode and yield frames until BaseVideo closes the iterator.

        A single reader thread polls the SDK for the whole activation and hands frames to the event
        loop. Each frame is stamped with the settings generation and exposure time in effect when
        it was read, under the same lock that _apply_settings() holds while it restarts live mode,
        so the stamp is always right.
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Frame] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        stop = threading.Event()

        def _start() -> None:
            if self._driver is None:
                raise RuntimeError("Camera not connected.")
            self._driver.begin_live()
            self._capturing = True

        def _put(frame: Frame) -> None:
            # latest wins: a stalled event loop mustn't grow memory
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(frame)

        def _read() -> None:
            while not stop.is_set():
                # let a waiting setter take the lock first
                while self._settings_pending.is_set() and not stop.is_set():
                    time.sleep(_POLL_INTERVAL)

                frame: Frame | None = None
                with self._driver_lock:
                    driver, buffer = self._driver, self._buffer
                    if driver is None or buffer is None or not self._capturing:
                        return
                    info = driver.get_live_frame(buffer)
                    if info is not None:
                        width, height, bpp, _ = info
                        frame = Frame(
                            data=self._to_image(buffer, width, height, bpp),
                            exposure_time=self._exposure_time,
                            generation=self.generation,
                        )

                if frame is None:
                    time.sleep(_POLL_INTERVAL)
                    continue
                try:
                    loop.call_soon_threadsafe(_put, frame)
                except RuntimeError:
                    # event loop closed (shutdown)
                    return

        def _stop() -> None:
            self._capturing = False
            if self._driver is not None:
                self._driver.stop_live()

        await self._run_blocking_or_raise(_start)
        threading.Thread(target=_read, daemon=True).start()
        try:
            while True:
                timeout = self._exposure_time + _FRAME_WAIT_MARGIN
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=timeout)
                except TimeoutError:
                    log.warning("No frame from camera for %.1fs.", timeout)
                    continue
                yield frame
        finally:
            # don't join the reader: if it hangs in the SDK, it must not block deactivation
            stop.set()
            try:
                if not await self._run_blocking(_stop):
                    log.error("Timed out stopping live mode after %.1fs.", SDK_CALL_TIMEOUT)
            except Exception:
                log.exception("Error stopping live mode.")

    async def _finish_image(self, image: Image, broadcast: bool, image_type: ImageType) -> tuple[Image, str]:
        """Add settings headers, then finish up as usual."""
        image.header["XBINNING"] = image.header["DET-BIN1"] = (self._binning[0], "Binning factor used on X axis")
        image.header["YBINNING"] = image.header["DET-BIN2"] = (self._binning[1], "Binning factor used on Y axis")
        image.header["XORGSUBF"] = (self._window[0], "Subframe origin on X axis")
        image.header["YORGSUBF"] = (self._window[1], "Subframe origin on Y axis")
        image.header["GAIN"] = (self._gain, "Gain used for exposure")
        image.header["OFFSET"] = (self._offset, "Offset used for exposure")
        if self._pixel_size is not None:
            image.header["DET-PIXL"] = (self._pixel_size, "Size of detector pixels [mm]")
        return await super()._finish_image(image, broadcast, image_type)

    async def _set(self, update: Callable[[], None]) -> None:
        """Change settings via update(), write them to the camera and publish the new states.

        If the camera rejects the new settings, the old ones are restored.
        """
        old = self._settings()
        update()
        try:
            await self._apply_settings()
        except Exception:
            self._restore_settings(old)
            await self._apply_settings()
            raise
        finally:
            await self._publish_states()

    def _settings(self) -> tuple[Any, ...]:
        return self._exposure_time, self._gain, self._offset, self._window, self._binning, self._image_format

    def _restore_settings(self, settings: tuple[Any, ...]) -> None:
        (
            self._exposure_time,
            self._gain,
            self._offset,
            self._window,
            self._binning,
            self._image_format,
        ) = settings

    async def set_exposure_time(self, exposure_time: float, **kwargs: Any) -> None:
        """Set the exposure time in seconds.

        Args:
            exposure_time: Exposure time in seconds.

        Raises:
            ValueError: If exposure time is negative.
        """
        if exposure_time < 0:
            raise ValueError("Exposure time must not be negative.")
        log.info("Setting exposure time to %.3fs...", exposure_time)
        await self._set(lambda: setattr(self, "_exposure_time", exposure_time))

    async def set_gain(self, gain: float, **kwargs: Any) -> None:
        """Set the camera gain.

        Args:
            gain: New camera gain.
        """
        log.info("Setting gain to %s...", gain)
        await self._set(lambda: setattr(self, "_gain", gain))

    async def set_offset(self, offset: float, **kwargs: Any) -> None:
        """Set the camera offset.

        Args:
            offset: New camera offset.
        """
        log.info("Setting offset to %s...", offset)
        await self._set(lambda: setattr(self, "_offset", offset))

    async def set_window(self, left: int, top: int, width: int, height: int, **kwargs: Any) -> None:
        """Set the camera window, in unbinned pixels.

        Args:
            left: X offset of window.
            top: Y offset of window.
            width: Width of window.
            height: Height of window.
        """
        log.info("Setting window to %dx%d at %d,%d...", width, height, left, top)
        await self._set(lambda: setattr(self, "_window", (left, top, width, height)))

    async def set_binning(self, x: int, y: int, **kwargs: Any) -> None:
        """Set the camera binning.

        Args:
            x: X binning.
            y: Y binning.
        """
        log.info("Setting binning to %dx%d...", x, y)
        await self._set(lambda: setattr(self, "_binning", (x, y)))

    async def set_image_format(self, fmt: ImageFormat, **kwargs: Any) -> None:
        """Set the camera image format.

        Args:
            fmt: New image format.

        Raises:
            ValueError: If format is not supported.
        """
        if fmt not in VIDEO_FORMATS or (self._driver is not None and not self._has_bits and fmt != self._image_format):
            raise ValueError("Unsupported image format.")
        log.info("Setting image format to %s...", fmt)
        await self._set(lambda: setattr(self, "_image_format", fmt))

    async def reset(self, **kwargs: Any) -> None:
        """Reset image type, data pipeline, exposure time, gain, offset and image format to their defaults."""
        await BaseVideo.reset(self, **kwargs)

        def _update() -> None:
            self._exposure_time = self._default_exposure_time
            self._gain = self._default_gain
            self._offset = self._default_offset
            self._image_format = self._default_image_format

        await self._set(_update)


__all__ = ["QHYCCDVideo"]
