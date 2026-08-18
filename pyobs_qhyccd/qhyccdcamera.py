import asyncio
import logging
import math
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

import numpy as np
from pyobs.images import Image
from pyobs.interfaces import (
    Binning,
    BinningCapabilities,
    BinningState,
    CoolingState,
    GainState,
    IAbortable,
    IBinning,
    ICamera,
    ICooling,
    IGain,
    ITemperatures,
    IWindow,
    SensorReading,
    TemperaturesState,
    WindowCapabilities,
    WindowState,
)
from pyobs.modules.camera.basecamera import BaseCamera
from pyobs.utils.exceptions import AbortedError
from pyobs.utils.parallel import event_wait

from .qhyccddriver import Control, QHYCCDDriver, set_log_level  # type: ignore

log = logging.getLogger(__name__)

_T = TypeVar("_T")

# QHYCCD SDK calls are blocking and are made directly on the event loop thread (see
# _run_blocking). If the camera has gone unresponsive, they can hang indefinitely, so they're
# bounded with a timeout rather than let a single dead camera freeze the whole module.
_SDK_CALL_TIMEOUT = 5.0


class QHYCCDCamera(BaseCamera, ICamera, IWindow, IBinning, IAbortable, ICooling, IGain):
    """A pyobs module for QHYCCD cameras."""

    __module__ = "pyobs_qhyccd"

    def __init__(
        self,
        setpoint: float = -10,
        params: dict[str, float] | None = None,
        cooling_step: float = 1.0,
        cooling_wait: float = 60.0,
        **kwargs: Any,
    ):
        """Initializes a new QHYCCDCamera."""
        BaseCamera.__init__(self, **kwargs)

        self._driver: QHYCCDDriver | None = None
        self._driver_lock = threading.Lock()
        self._setpoint = setpoint
        self._window = (0, 0, 0, 0)
        self._binning = (1, 1)
        self._effective_area = (0, 0, 0, 0)
        self._params = params
        self._cooling_step = cooling_step
        self._cooling_wait = cooling_wait
        self._cooling_next: float | None = None
        self._current_temperature: float = 0.0

        self.add_background_task(self._update_cooling)

    async def _run_blocking(self, func: Callable[[], None], timeout: float = _SDK_CALL_TIMEOUT) -> bool:
        """Run a blocking QHYCCD SDK call in a daemon thread, so a hung call can't freeze the module.

        A plain executor isn't used here, since its worker threads are non-daemon and Python joins
        them on interpreter shutdown -- a hung call would then just move the freeze to process exit.

        Every SDK call is serialized behind self._driver_lock, so the helper threads and the 1s
        cooling poll never touch the driver handle concurrently. On timeout the worker is left
        running in the background; its result callback is guarded so it can't set_result on an
        already-cancelled future.

        Returns:
            True if func completed within timeout, False if it's still running in the background.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()

        def _set_result() -> None:
            if not future.done():
                future.set_result(None)

        def _wrapper() -> None:
            try:
                with self._driver_lock:
                    func()
            finally:
                loop.call_soon_threadsafe(_set_result)

        threading.Thread(target=_wrapper, daemon=True).start()
        try:
            await asyncio.wait_for(future, timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def _run_blocking_or_raise(self, func: Callable[[], _T], timeout: float = _SDK_CALL_TIMEOUT) -> _T:
        """Run a blocking QHYCCD SDK call in a thread, returning its result or re-raising what it raised.

        Unlike _run_blocking(), this also carries the callable's return value/exception back to the
        caller -- several QHYCCD calls here drive control flow via their return value or a raised
        ValueError (e.g. unsupported color cams), which a bare fire-and-forget thread call would
        otherwise silently lose.
        """
        outcome: list[Any] = []

        def _wrapper() -> None:
            try:
                outcome.append(func())
            except BaseException as e:
                outcome.append(e)

        if not await self._run_blocking(_wrapper, timeout=timeout):
            raise TimeoutError(f"Timed out waiting for QHYCCD SDK call after {timeout}s.")
        value = outcome[0]
        if isinstance(value, BaseException):
            raise value
        return cast(_T, value)

    async def open(self) -> None:
        """Open module."""
        await BaseCamera.open(self)

        def _connect() -> tuple[int, int]:
            set_log_level(0)

            devices = QHYCCDDriver.list_devices()
            self._driver = QHYCCDDriver(devices[0])
            self._driver.open()

            if self._driver.is_control_available(Control.CAM_COLOR):
                raise ValueError("Color cams are not supported.")

            if self._driver.is_control_available(Control.CONTROL_USBTRAFFIC):
                self._driver.set_param(Control.CONTROL_USBTRAFFIC, 60)

            if self._driver.is_control_available(Control.CONTROL_GAIN):
                self._driver.set_param(Control.CONTROL_GAIN, 10)

            if self._driver.is_control_available(Control.CONTROL_OFFSET):
                self._driver.set_param(Control.CONTROL_OFFSET, 140)

            if self._driver.is_control_available(Control.CONTROL_TRANSFERBIT):
                self._driver.set_bits_mode(16)

            chip = self._driver.get_chip_info()
            log.info("Chip  size:     %.3fx%.3f [mm]", chip[0], chip[1])
            log.info("Pixel size:     %.3fx %.3f [um]", chip[4], chip[5])
            log.info("Image size:     %dx%d", chip[2], chip[3])
            overscan = self._driver.get_overscan_area()
            log.info("Overscan Area:  %dx%d from %d,%d", overscan[2], overscan[3], overscan[0], overscan[1])
            effective = self._driver.get_effective_area()
            log.info("Effective Area: %dx%d from %d,%d", effective[2], effective[3], effective[0], effective[1])

            return chip[2], chip[3]

        full_width, full_height = await self._run_blocking_or_raise(_connect)
        self._window = (0, 0, full_width, full_height)

        # publish static capabilities
        await self.comm.set_capabilities(
            IWindow,
            WindowCapabilities(
                full_frame_x=0, full_frame_y=0, full_frame_width=full_width, full_frame_height=full_height
            ),
        )
        await self.comm.set_capabilities(IBinning, BinningCapabilities(binnings=await self._available_binnings()))

        # publish initial states
        await self.comm.set_state(IWindow, WindowState(x=0, y=0, width=full_width, height=full_height))
        await self.comm.set_state(IBinning, BinningState(x=self._binning[0], y=self._binning[1]))

        def _get_gain_offset() -> tuple[float, float]:
            assert self._driver is not None
            return float(self._driver.get_param(Control.CONTROL_GAIN)), float(
                self._driver.get_param(Control.CONTROL_OFFSET)
            )

        gain, offset = await self._run_blocking_or_raise(_get_gain_offset)
        await self.comm.set_state(IGain, GainState(gain=gain, offset=offset))

        if self._setpoint is not None:
            await self.set_cooling(True, self._setpoint)

        if self._params is not None:
            params = self._params

            def _set_custom_params() -> None:
                assert self._driver is not None
                for key, value in params.items():
                    p = "CONTROL_" + key.upper()
                    if hasattr(Control, p):
                        control_param = getattr(Control, p)
                        log.info("Setting %s to %s.", control_param, value)
                        self._driver.set_param(control_param, value)

            await self._run_blocking_or_raise(_set_custom_params)

    async def _available_binnings(self) -> list[Binning]:
        if self._driver is None:
            return []
        driver = self._driver

        def _get() -> list[Binning]:
            binnings = []
            if driver.is_control_available(Control.CAM_BIN1X1MODE):
                binnings.append(Binning(x=1, y=1))
            if driver.is_control_available(Control.CAM_BIN2X2MODE):
                binnings.append(Binning(x=2, y=2))
            if driver.is_control_available(Control.CAM_BIN3X3MODE):
                binnings.append(Binning(x=3, y=3))
            if driver.is_control_available(Control.CAM_BIN4X4MODE):
                binnings.append(Binning(x=4, y=4))
            return binnings

        return await self._run_blocking_or_raise(_get)

    async def close(self) -> None:
        """Close the module."""
        await BaseCamera.close(self)

        if self._driver:
            if not await self._run_blocking(self._driver.close):
                log.error("Timed out closing QHYCCD camera after %.1fs.", _SDK_CALL_TIMEOUT)

    async def set_window(self, left: int, top: int, width: int, height: int, **kwargs: Any) -> None:
        """Set the camera window.

        Args:
            left: X offset of window.
            top: Y offset of window.
            width: Width of window.
            height: Height of window.
        """
        self._window = (left, top, width, height)
        log.info("Setting window to %dx%d at %d,%d...", width, height, left, top)
        await self.comm.set_state(IWindow, WindowState(x=left, y=top, width=width, height=height))

    async def set_binning(self, x: int, y: int, **kwargs: Any) -> None:
        """Set the camera binning.

        Args:
            x: X binning.
            y: Y binning.
        """
        self._binning = (x, y)
        log.info("Setting binning to %dx%d...", x, y)
        await self.comm.set_state(IBinning, BinningState(x=x, y=y))

    async def _prepare_driver_for_exposure(self, exposure_time: float) -> None:
        if self._driver is None:
            raise ValueError("No camera driver.")
        driver = self._driver

        log.info("Set binning to %dx%d.", self._binning[0], self._binning[1])

        width = int(math.floor(self._window[2]) / self._binning[0])
        height = int(math.floor(self._window[3]) / self._binning[1])
        log.info(
            "Set window to %dx%d (binned %dx%d) at %d,%d.",
            self._window[2],
            self._window[3],
            width,
            height,
            self._window[0],
            self._window[1],
        )

        def _prepare() -> tuple[int, int, int, int]:
            driver.set_bin_mode(*self._binning)
            driver.set_resolution(self._window[0], self._window[1], width, height)
            driver.set_param(Control.CONTROL_EXPOSURE, int(exposure_time * 1000.0 * 1000.0))
            return driver.get_effective_area()

        eff = await self._run_blocking_or_raise(_prepare)
        self._effective_area = (eff[0], eff[1], eff[2] * self._binning[0], eff[3] * self._binning[1])

    async def _get_image_with_header(self, image_data: Any, date_obs: str, exposure_time: float) -> Image:
        image = Image(image_data)
        image.header["DATE-OBS"] = (date_obs, "Date and time of start of exposure")
        image.header["EXPTIME"] = (exposure_time, "Exposure time [s]")
        image.header["DET-TEMP"] = (self._current_temperature, "CCD temperature [C]")
        image.header["DET-COOL"] = (await self._get_cooling_power(), "Cooler power [percent]")
        image.header["DET-TSET"] = (self._setpoint, "Cooler setpoint [C]")
        image.header["XBINNING"] = image.header["DET-BIN1"] = (self._binning[0], "Binning factor used on X axis")
        image.header["YBINNING"] = image.header["DET-BIN2"] = (self._binning[1], "Binning factor used on Y axis")
        image.header["XORGSUBF"] = (self._window[0], "Subframe origin on X axis")
        image.header["YORGSUBF"] = (self._window[1], "Subframe origin on Y axis")
        image.header["DATAMIN"] = (float(np.min(image_data)), "Minimum data value")
        image.header["DATAMAX"] = (float(np.max(image_data)), "Maximum data value")
        image.header["DATAMEAN"] = (float(np.mean(image_data)), "Mean data value")

        self.set_biassec_trimsec(image.header, *self._effective_area)
        log.info("Readout finished.")
        return image

    async def _expose(self, exposure_time: float, open_shutter: bool, abort_event: asyncio.Event) -> Image:
        """Actually do the exposure, should be implemented by derived classes.

        Args:
            exposure_time: The requested exposure time in seconds.
            open_shutter: Whether to open the shutter.
            abort_event: Event that gets triggered when exposure should be aborted.

        Returns:
            The actual image.

        Raises:
            GrabImageError: If exposure was not successful.
        """
        if self._driver is None:
            raise ValueError("No camera driver.")
        driver = self._driver

        await self._prepare_driver_for_exposure(exposure_time)
        log.info(
            "Starting exposure with %s shutter for %.2f seconds...", "open" if open_shutter else "closed", exposure_time
        )
        date_obs = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")
        await self._run_blocking_or_raise(driver.expose_single_frame)
        aborted = await self._wait_exposure(abort_event, exposure_time, open_shutter)
        if aborted:
            # a cancelled exposure must not be read out (see cancel_exposure/_abort_exposure)
            raise AbortedError()
        loop = asyncio.get_running_loop()
        image_data = await loop.run_in_executor(None, driver.get_single_frame)
        return await self._get_image_with_header(image_data, date_obs, exposure_time)

    async def _wait_exposure(self, abort_event: asyncio.Event, exposure_time: float, open_shutter: bool) -> bool:
        """Wait for exposure to finish.

        Returns:
            True if the exposure was aborted, False if it ran to completion.
        """
        return await event_wait(abort_event, exposure_time - 0.5)

    async def _abort_exposure(self) -> None:
        """Abort the running exposure."""
        if self._driver is None:
            raise ValueError("No camera driver.")
        driver = self._driver
        if not await self._run_blocking(driver.cancel_exposure):
            log.error("Timed out cancelling QHYCCD exposure after %.1fs.", _SDK_CALL_TIMEOUT)

    async def _get_cooling_power(self) -> float:
        if self._driver is None:
            raise ValueError("No camera driver.")
        driver = self._driver

        def _get() -> float:
            return float(driver.get_param(Control.CONTROL_CURPWM)) / 255 * 100  # TODO:

        return await self._run_blocking_or_raise(_get)

    async def set_cooling(self, enabled: bool, setpoint: float, **kwargs: Any) -> None:
        if enabled:
            log.info("Enabling cooling with a set point of %.1f°C.", setpoint)
        else:
            log.info("Disabling cooling.")
        self._setpoint = setpoint
        power = round(await self._get_cooling_power()) if self._driver is not None else None
        await self.comm.set_state(
            ICooling, CoolingState(setpoint=setpoint if enabled else None, power=power, enabled=enabled)
        )

    async def _update_cooling(self) -> None:
        await asyncio.sleep(5)
        if self._driver is None:
            raise ValueError("No camera driver.")
        driver = self._driver

        start_time = 0.0
        while True:
            try:
                await asyncio.sleep(1.0)

                cooling_next = self._cooling_next

                def _poll() -> tuple[float, float, bool, bool]:
                    if cooling_next is not None:
                        driver.set_temperature(cooling_next)
                    current_temp = float(driver.get_param(Control.CONTROL_CURTEMP))
                    power_raw = float(driver.get_param(Control.CONTROL_CURPWM))
                    cooler_available = driver.is_control_available(Control.CONTROL_COOLER)
                    # bug: QHY PWM wraps above 250 -- checked with a fresh read, same as the
                    # separate driver.get_param() call the original code made for this check
                    pwm_over_250 = float(driver.get_param(Control.CONTROL_CURPWM)) > 250
                    return current_temp, power_raw, cooler_available, pwm_over_250

                self._current_temperature, power_raw, cooler_available, pwm_over_250 = (
                    await self._run_blocking_or_raise(_poll)
                )

                # publish live temperatures and cooling state
                await self.comm.set_state(
                    ITemperatures,
                    TemperaturesState(readings=[SensorReading(name="CCD", value=self._current_temperature)]),
                )
                power = round(power_raw / 255 * 100)
                await self.comm.set_state(
                    ICooling,
                    CoolingState(
                        setpoint=self._setpoint,
                        power=power,
                        enabled=cooler_available,
                    ),
                )

                if pwm_over_250:
                    self._cooling_next = self._current_temperature + 5.0
                    log.warning(
                        "Cooling power seems to be bugged. Setting temperature to %.2f°. "
                        "Current temperature is %.2f°C.",
                        self._cooling_next,
                        self._current_temperature,
                    )

                if self._cooling_next == self._setpoint:
                    continue

                if start_time > 0 and time.time() - start_time > self._cooling_wait:
                    start_time = 0.0

                if start_time == 0.0:
                    if self._cooling_next is None:
                        self._cooling_next = self._current_temperature

                    diff = self._setpoint - self._current_temperature
                    if abs(diff) < abs(self._cooling_step):
                        self._cooling_next = self._setpoint
                    else:
                        sign = np.sign(diff)
                        self._cooling_next += sign * min(self._cooling_step, abs(diff))

                    log.info(
                        "Next cooling step: %.2f°C. Current temperature is %.2f°C.",
                        self._cooling_next,
                        self._current_temperature,
                    )

                    start_time = time.time()

            except Exception:
                log.exception("Error updating cooling.")

    async def set_gain(self, gain: float, **kwargs: Any) -> None:
        """Set the camera gain.

        Args:
            gain: New camera gain.
        """
        if self._driver is None:
            raise ValueError("No camera driver.")
        driver = self._driver

        def _set() -> float:
            driver.set_param(Control.CONTROL_GAIN, gain)
            return float(driver.get_param(Control.CONTROL_OFFSET))

        offset = await self._run_blocking_or_raise(_set)
        await self.comm.set_state(IGain, GainState(gain=gain, offset=offset))

    async def set_offset(self, offset: float, **kwargs: Any) -> None:
        """Set the camera offset.

        Args:
            offset: New camera offset.
        """
        if self._driver is None:
            raise ValueError("No camera driver.")
        driver = self._driver

        def _set() -> float:
            driver.set_param(Control.CONTROL_OFFSET, offset)
            return float(driver.get_param(Control.CONTROL_GAIN))

        gain = await self._run_blocking_or_raise(_set)
        await self.comm.set_state(IGain, GainState(gain=gain, offset=offset))


__all__ = ["QHYCCDCamera"]
