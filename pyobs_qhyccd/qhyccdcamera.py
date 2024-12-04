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


class QHYCCDCamera(BaseCamera, ICamera, IWindow, IBinning, IAbortable):
    """A pyobs module for QHYCCD cameras."""

    __module__ = "pyobs_qhyccd"

    def __init__(self, **kwargs: Any):
        """Initializes a new QHYCCDCamera.
        """
        BaseCamera.__init__(self, **kwargs)

        # driver
        self._driver: Optional[QHYCCDDriver] = None

        # window and binning
        self._window = (0, 0, 0, 0)
        self._binning = (1, 1)

    async def open(self) -> None:
        """Open module."""
        await BaseCamera.open(self)

        # disable logs
        set_log_level(0)

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
        #if self._temp_setpoint is not None:
        #    await self.set_cooling(True, self._temp_setpoint)

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
        return [(1, 1), (2, 2), (3, 3), (4, 4)]

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
        # check driver
        if self._driver is None:
            raise ValueError("No camera driver.")

        # set binning
        log.info("Set binning to %dx%d.", self._binning[0], self._binning[1])
        self._driver.set_bin_mode(*self._binning)

        # set window, divide width/height by binning, from libfli:
        # "Note that the given lower-right coordinate must take into account the horizontal and
        # vertical bin factor settings, but the upper-left coordinate is absolute."
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

        # exposure time
        self._driver.set_param(Control.CONTROL_EXPOSURE, int(exposure_time * 1000.0))

        # get date obs
        log.info(
            "Starting exposure with %s shutter for %.2f seconds...", "open" if open_shutter else "closed", exposure_time
        )
        date_obs = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")

        # expose
        print("before expose", time.time())
        self._driver.expose_single_frame()
        print("after expose", time.time())

        # wait for exposure
        if exposure_time > 0.5:
            await event_wait(abort_event, exposure_time - 0.5)
        #if abort_event.is_set():
        #    raise

        # get image
        print("before get", time.time())
        img = self._driver.get_single_frame()
        #loop = asyncio.get_running_loop()
        #img = await loop.run_in_executor(None, self._driver.get_single_frame)
        print("after get", time.time())

        # wait exposure
        await self._wait_exposure(abort_event, exposure_time, open_shutter)

        # create FITS image and set header
        image = Image(img)
        image.header["DATE-OBS"] = (date_obs, "Date and time of start of exposure")
        image.header["EXPTIME"] = (exposure_time, "Exposure time [s]")
        #image.header["DET-TEMP"] = (self._driver.get_temp(FliTemperature.CCD), "CCD temperature [C]")
        #image.header["DET-COOL"] = (self._driver.get_cooler_power(), "Cooler power [percent]")
        #image.header["DET-TSET"] = (self._temp_setpoint, "Cooler setpoint [C]")

        # instrument and detector
        #image.header["INSTRUME"] = (self._driver.name, "Name of instrument")

        # binning
        image.header["XBINNING"] = image.header["DET-BIN1"] = (self._binning[0], "Binning factor used on X axis")
        image.header["YBINNING"] = image.header["DET-BIN2"] = (self._binning[1], "Binning factor used on Y axis")

        # window
        image.header["XORGSUBF"] = (self._window[0], "Subframe origin on X axis")
        image.header["YORGSUBF"] = (self._window[1], "Subframe origin on Y axis")

        # statistics
        image.header["DATAMIN"] = (float(np.min(img)), "Minimum data value")
        image.header["DATAMAX"] = (float(np.max(img)), "Maximum data value")
        image.header["DATAMEAN"] = (float(np.mean(img)), "Mean data value")

        # biassec/trimsec
        #full = self._driver.get_visible_frame()
        #self.set_biassec_trimsec(image.header, *full)

        # return FITS image
        log.info("Readout finished.")
        return image

    async def _wait_exposure(self, abort_event: asyncio.Event, exposure_time: float, open_shutter: bool) -> None:
        """Wait for exposure to finish.

        Params:
            abort_event: Event that aborts the exposure.
            exposure_time: Exp time in sec.
        """

        """
        while True:
            # aborted?
            if abort_event.is_set():
                await self._change_exposure_status(ExposureStatus.IDLE)
                raise InterruptedError("Aborted exposure.")

            # is exposure finished?
            if self._driver.is_exposing():
                break
            else:
                # sleep a little
                await asyncio.sleep(0.01)
        """

    async def _abort_exposure(self) -> None:
        """Abort the running exposure. Should be implemented by derived class.

        Raises:
            ValueError: If an error occured.
        """
        if self._driver is None:
            raise ValueError("No camera driver.")
        #self._driver.cancel_exposure()


__all__ = ["QHYCCDCamera"]
