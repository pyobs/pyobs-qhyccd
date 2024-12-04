import asyncio
import logging
import math
import time
from datetime import datetime, timezone
from typing import Tuple, Any, Optional, Dict, List
import numpy as np

from pyobs.interfaces import ICamera, IWindow, IBinning, ICooling, IAbortable
from pyobs.modules.camera.basecamera import BaseCamera
from pyobs.images import Image
from pyobs.utils.enums import ExposureStatus
from pyobs.utils.parallel import event_wait

from .qhyccddriver import QHYCCDDriver, Control, set_log_level

log = logging.getLogger(__name__)


class QHYCCDCamera(BaseCamera, ICamera, IWindow, IBinning, IAbortable, ICooling):
    """A pyobs module for QHYCCD cameras."""

    __module__ = "pyobs_qhyccd"

    def __init__(self, setpoint: float=-10, **kwargs: Any):
        """Initializes a new QHYCCDCamera.
        """
        BaseCamera.__init__(self, **kwargs)

        self._driver: Optional[QHYCCDDriver] = None
        self._setpoint = setpoint
        self._window = (0, 0, 0, 0)
        self._binning = (1, 1)

    async def open(self) -> None:
        """Open module."""
        await BaseCamera.open(self)

        # disable logs
        set_log_level(0) #TODO:

        # get devices
        devices = QHYCCDDriver.list_devices()

        # open camera
        self._driver = QHYCCDDriver(devices[0])
        self._driver.open()

        # color cam?
        if self._driver.is_control_available(Control.CAM_COLOR):
            raise ValueError('Color cams are not supported.')

        # usb traffic?
        if self._driver.is_control_available(Control.CONTROL_USBTRAFFIC):
            self._driver.set_param(Control.CONTROL_USBTRAFFIC, 60)

        # gain?
        if self._driver.is_control_available(Control.CONTROL_GAIN):
            self._driver.set_param(Control.CONTROL_GAIN, 10)

        # offset?
        if self._driver.is_control_available(Control.CONTROL_OFFSET):
            self._driver.set_param(Control.CONTROL_OFFSET, 140)

        # bpp
        if self._driver.is_control_available(Control.CONTROL_TRANSFERBIT):
            self._driver.set_bits_mode(16)

        # get full window
        self._window = self._driver.get_effective_area()

        # set cooling
        if self._setpoint is not None:
            await self.set_cooling(True, self._setpoint)

    async def close(self) -> None:
        """Close the module."""
        await BaseCamera.close(self)

        if self._driver:
            self._driver.close()

    async def get_full_frame(self, **kwargs: Any) -> Tuple[int, int, int, int]:
        """Returns full size of CCD.

        Returns:
            Tuple with left, top, width, and height set.
        """
        if self._driver is None:
            raise ValueError("No camera driver.")
        return self._driver.get_effective_area()

    async def get_window(self, **kwargs: Any) -> Tuple[int, int, int, int]:
        """Returns the camera window.

        Returns:
            Tuple with left, top, width, and height set.
        """
        return self._window

    async def get_binning(self, **kwargs: Any) -> Tuple[int, int]:
        """Returns the camera binning.

        Returns:
            Tuple with x and y.
        """
        return self._binning

    async def set_window(self, left: int, top: int, width: int, height: int, **kwargs: Any) -> None:
        """Set the camera window.

        Args:
            left: X offset of window.
            top: Y offset of window.
            width: Width of window.
            height: Height of window.

        Raises:
            ValueError: If binning could not be set.
        """
        self._window = (left, top, width, height)
        log.info("Setting window to %dx%d at %d,%d...", width, height, left, top)

    async def set_binning(self, x: int, y: int, **kwargs: Any) -> None:
        """Set the camera binning.

        Args:
            x: X binning.
            y: Y binning.

        Raises:
            ValueError: If binning could not be set.
        """
        self._binning = (x, y)
        log.info("Setting binning to %dx%d...", x, y)

    async def list_binnings(self, **kwargs: Any) -> List[Tuple[int, int]]:
        """List available binnings.

        Returns:
            List of available binnings as (x, y) tuples.
        """

        binnings = []
        if self._driver.is_control_available(Control.CAM_BIN1X1MODE):
            binnings.append((1, 1))
        if self._driver.is_control_available(Control.CAM_BIN2X2MODE):
            binnings.append((2, 2))
        if self._driver.is_control_available(Control.CAM_BIN3X3MODE):
            binnings.append((3, 3))
        if self._driver.is_control_available(Control.CAM_BIN4X4MODE):
            binnings.append((4, 4))
        return binnings

    async def _prepare_driver_for_exposure(self, exposure_time) -> None:
        if self._driver is None:
            raise ValueError("No camera driver.")
        log.info("Set binning to %dx%d.", self._binning[0], self._binning[1])
        self._driver.set_bin_mode(*self._binning)

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
        self._driver.set_resolution(self._window[0], self._window[1], width, height)
        self._driver.set_param(Control.CONTROL_EXPOSURE, int(exposure_time * 1000.0 * 1000.0))

    async def _get_image_with_header(self, image_data, date_obs, exposure_time) -> Image:
        image = Image(image_data)
        image.header["DATE-OBS"] = (date_obs, "Date and time of start of exposure")
        image.header["EXPTIME"] = (exposure_time, "Exposure time [s]")
        image.header["DET-TEMP"] = (await self._get_ccd_temperature(), "CCD temperature [C]")
        image.header["DET-COOL"] = (await self._get_cooling_power(), "Cooler power [percent]")
        image.header["DET-TSET"] = (self._setpoint, "Cooler setpoint [C]")
        # image.header["INSTRUME"] = (self._driver.name, "Name of instrument")
        image.header["XBINNING"] = image.header["DET-BIN1"] = (self._binning[0], "Binning factor used on X axis")
        image.header["YBINNING"] = image.header["DET-BIN2"] = (self._binning[1], "Binning factor used on Y axis")
        image.header["XORGSUBF"] = (self._window[0], "Subframe origin on X axis")
        image.header["YORGSUBF"] = (self._window[1], "Subframe origin on Y axis")
        image.header["DATAMIN"] = (float(np.min(image_data)), "Minimum data value")
        image.header["DATAMAX"] = (float(np.max(image_data)), "Maximum data value")
        image.header["DATAMEAN"] = (float(np.mean(image_data)), "Mean data value")

        # biassec/trimsec
        # full = self._driver.get_visible_frame()
        # self.set_biassec_trimsec(image.header, *full)
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

        await self._prepare_driver_for_exposure(exposure_time)
        log.info("Starting exposure with %s shutter for %.2f seconds...", "open" if open_shutter else "closed", exposure_time)
        date_obs = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
        self._driver.expose_single_frame()
        await event_wait(abort_event, exposure_time-0.5)
        loop = asyncio.get_running_loop()
        image_data = await loop.run_in_executor(None, self._driver.get_single_frame)
        return await self._get_image_with_header(image_data, date_obs, exposure_time)

    async def _abort_exposure(self) -> None:
        """Abort the running exposure. Should be implemented by derived class.
        Raises:
            ValueError: If an error occured.
        """
        if self._driver is None:
            raise ValueError("No camera driver.")
        #self._driver.cancel_exposure()

    async def _get_cooling_power(self):
        return self._driver.get_param(Control.CONTROL_CURPWM) /256 * 100 # TODO:

    async def get_cooling(self, **kwargs: Any) -> Tuple[bool, float, float]:
        enabled = self._driver.is_control_available(Control.CONTROL_COOLER)
        setpoint = self._setpoint
        power = await self._get_cooling_power()
        return enabled, setpoint, power

    async def set_cooling(self, enabled: bool, setpoint: float, **kwargs: Any) -> None:
        #if not enabled:
        #    self._driver.set_param(Control.CONTROL_CURPWM, 0)  #TODO: einfach PWM auf 0?
        self._setpoint = setpoint
        await self._cool_stepwise(setpoint)

    async def _wait_for_reaching_temperature(self, target_temperature, wait_step=1):
        while await self._get_ccd_temperature() > target_temperature:
            print("Current temperature is", await self._get_ccd_temperature(), "Target temperature is", target_temperature)
            if await self._cooling_bug_occured():
                break
            await asyncio.sleep(wait_step)

    async def _cooling_bug_occured(self):
        return (self._driver.get_param(Control.CONTROL_CURPWM) > 250) & (await self._get_ccd_temperature() < 0)

    async def _get_ccd_temperature(self):
        return self._driver.get_param(Control.CONTROL_CURTEMP)

    async def _cool_stepwise(self, target_temperature, temperature_stepwidth=1):
        print("Start stepwise cooling to ", target_temperature)
        while await self._get_ccd_temperature() - target_temperature > temperature_stepwidth:
            intermediate_temperature = await self._get_ccd_temperature() - temperature_stepwidth
            print("Set temperature to", intermediate_temperature)
            self._driver.set_temperature(intermediate_temperature)
            await self._wait_for_reaching_temperature(intermediate_temperature)
            if await self._cooling_bug_occured():
                await self._handle_cooling_bug(intermediate_temperature)
                return
        print("Set temperature to", target_temperature)
        self._driver.set_temperature(target_temperature)
        print("End stepwise cooling to", target_temperature)

    async def _handle_cooling_bug(self, original_target_temperature, puffer=5, correction_step=1):
        print(f"Setpoint of {original_target_temperature:.2f} °C too low for cooler. Temporarily resetting it to {await self._get_ccd_temperature() + puffer:.2f} °C.")
        while await self._cooling_bug_occured():
            time.sleep(1)
            await self._cool_stepwise(await self._get_ccd_temperature() + puffer)
        print("Wait a minute")
        time.sleep(60)
        self._setpoint = original_target_temperature + correction_step
        print("Retry stepwise cooling with new setpoint of", self._setpoint)
        await self._cool_stepwise(self._setpoint)

    async def get_temperatures(self, **kwargs: Any) -> Dict[str, float]:
        return {"CCD": await self._get_ccd_temperature()}

__all__ = ["QHYCCDCamera"]
