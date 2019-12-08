# distutils: language = c++

from collections import namedtuple
from enum import Enum
import numpy as np
cimport numpy as np
np.import_array()
from libc.string cimport strcpy, strlen

from libqhyccd cimport *


cdef class QHYCCDDriver:
    """Wrapper for the QHYCCD driver."""

    @staticmethod
    def list_devices():
        """List all QHYCCD USB cameras connected to this computer.

        Returns:
            List of DeviceInfo tuples.
        """

        # init resource
        if InitQHYCCDResource() != 0:
            raise ValueError('Could not init QHYCCD resource.')

        # scan cameras
        cam_count = ScanQHYCCD()

        # get IDs
        cdef char cam_id[32]
        cameras = []
        for i in range(cam_count):
            if GetQHYCCDId(i, cam_id) == 0:
                print('Found camera %s', str(cam_id))
                cameras.append(str(cam_id))

        # return IDs
        return cameras

    """Storage for link to device."""
    cdef libusb_device_handle *_device

    def __init__(self, cam_id: str):
        """Create a new driver object for the given ID.

        Args:
            cam_id: ID of camera to initialize.
        """
        self._cam_id = cam_id

    def open(self):
        """Open driver.

        Raises:
            ValueError: If opening failed.
        """

        # to char[32]
        cdef char *cam_id
        strcpy(cam_id, self._cam_id)

        # open cam
        self._device = OpenQHYCCD(cam_id)

        # does it support single frames?
        if IsQHYCCDControlAvailable(self._device, CONTROL_ID.CAM_SINGLEFRAMEMODE) != 0:
            raise ValueError('Camera does not support single frames.')

        # set single frame mode
        if SetQHYCCDStreamMode(self._device, 0) != 0:
            raise ValueError('Could not set single frame mode.')

        # init camera
        if InitQHYCCD(self._device) != 0:
            raise ValueError('Could not initialize camera.')

    def close(self):
        """Close driver.

        Raises:
            ValueError: If closing failed.
        """

        # close camera
        if self._device is not None:
            if CloseQHYCCD(self._device) != 0:
                raise ValueError('Could not close device.')

        # release resource
        ReleaseQHYCCDResource()
