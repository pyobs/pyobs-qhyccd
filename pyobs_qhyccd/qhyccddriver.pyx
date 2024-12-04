# distutils: language = c++

from collections import namedtuple
from enum import Enum
import numpy as np
cimport numpy as np
np.import_array()
from libc.string cimport strcpy, strlen

from pyobs_qhyccd.libqhyccd cimport *


class Control(Enum):
    CONTROL_BRIGHTNESS = CONTROL_ID.CONTROL_BRIGHTNESS,
    CONTROL_CONTRAST = CONTROL_ID.CONTROL_CONTRAST,
    CONTROL_WBR = CONTROL_ID.CONTROL_WBR,
    CONTROL_WBB = CONTROL_ID.CONTROL_WBB,
    CONTROL_WBG = CONTROL_ID.CONTROL_WBG,
    CONTROL_GAMMA = CONTROL_ID.CONTROL_GAMMA,
    CONTROL_GAIN = CONTROL_ID.CONTROL_GAIN,
    CONTROL_OFFSET = CONTROL_ID.CONTROL_OFFSET,
    CONTROL_EXPOSURE = CONTROL_ID.CONTROL_EXPOSURE,
    CONTROL_SPEED = CONTROL_ID.CONTROL_SPEED,
    CONTROL_TRANSFERBIT = CONTROL_ID.CONTROL_TRANSFERBIT,
    CONTROL_CHANNELS = CONTROL_ID.CONTROL_CHANNELS,
    CONTROL_USBTRAFFIC = CONTROL_ID.CONTROL_USBTRAFFIC,
    CONTROL_ROWNOISERE = CONTROL_ID.CONTROL_ROWNOISERE,
    CONTROL_CURTEMP = CONTROL_ID.CONTROL_CURTEMP,
    CONTROL_CURPWM = CONTROL_ID.CONTROL_CURPWM,
    CONTROL_MANULPWM = CONTROL_ID.CONTROL_MANULPWM,
    CONTROL_CFWPORT = CONTROL_ID.CONTROL_CFWPORT,
    CONTROL_COOLER = CONTROL_ID.CONTROL_COOLER,
    CONTROL_ST4PORT = CONTROL_ID.CONTROL_ST4PORT,
    CAM_COLOR = CONTROL_ID.CAM_COLOR,
    CAM_BIN1X1MODE = CONTROL_ID.CAM_BIN1X1MODE,
    CAM_BIN2X2MODE = CONTROL_ID.CAM_BIN2X2MODE,
    CAM_BIN3X3MODE = CONTROL_ID.CAM_BIN3X3MODE,
    CAM_BIN4X4MODE = CONTROL_ID.CAM_BIN4X4MODE,
    CAM_MECHANICALSHUTTER = CONTROL_ID.CAM_MECHANICALSHUTTER,
    CAM_TRIGER_INTERFACE = CONTROL_ID.CAM_TRIGER_INTERFACE,
    CAM_TECOVERPROTECT_INTERFACE = CONTROL_ID.CAM_TECOVERPROTECT_INTERFACE,
    CAM_SINGNALCLAMP_INTERFACE = CONTROL_ID.CAM_SINGNALCLAMP_INTERFACE,
    CAM_FINETONE_INTERFACE = CONTROL_ID.CAM_FINETONE_INTERFACE,
    CAM_SHUTTERMOTORHEATING_INTERFACE = CONTROL_ID.CAM_SHUTTERMOTORHEATING_INTERFACE,
    CAM_CALIBRATEFPN_INTERFACE = CONTROL_ID.CAM_CALIBRATEFPN_INTERFACE,
    CAM_CHIPTEMPERATURESENSOR_INTERFACE = CONTROL_ID.CAM_CHIPTEMPERATURESENSOR_INTERFACE,
    CAM_USBREADOUTSLOWEST_INTERFACE = CONTROL_ID.CAM_USBREADOUTSLOWEST_INTERFACE,

    CAM_8BITS = CONTROL_ID.CAM_8BITS,
    CAM_16BITS = CONTROL_ID.CAM_16BITS,
    CAM_GPS = CONTROL_ID.CAM_GPS,

    CAM_IGNOREOVERSCAN_INTERFACE = CONTROL_ID.CAM_IGNOREOVERSCAN_INTERFACE,

    QHYCCD_3A_AUTOBALANCE = CONTROL_ID.QHYCCD_3A_AUTOBALANCE,
    QHYCCD_3A_AUTOEXPOSURE = CONTROL_ID.QHYCCD_3A_AUTOEXPOSURE,
    QHYCCD_3A_AUTOFOCUS = CONTROL_ID.QHYCCD_3A_AUTOFOCUS,
    CONTROL_AMPV = CONTROL_ID.CONTROL_AMPV,
    CONTROL_VCAM = CONTROL_ID.CONTROL_VCAM,
    CAM_VIEW_MODE = CONTROL_ID.CAM_VIEW_MODE,

    CONTROL_CFWSLOTSNUM = CONTROL_ID.CONTROL_CFWSLOTSNUM,
    IS_EXPOSING_DONE = CONTROL_ID.IS_EXPOSING_DONE,
    ScreenStretchB = CONTROL_ID.ScreenStretchB,
    ScreenStretchW = CONTROL_ID.ScreenStretchW,
    CONTROL_DDR = CONTROL_ID.CONTROL_DDR,
    CAM_LIGHT_PERFORMANCE_MODE = CONTROL_ID.CAM_LIGHT_PERFORMANCE_MODE,

    CAM_QHY5II_GUIDE_MODE = CONTROL_ID.CAM_QHY5II_GUIDE_MODE,
    DDR_BUFFER_CAPACITY = CONTROL_ID.DDR_BUFFER_CAPACITY,
    DDR_BUFFER_READ_THRESHOLD = CONTROL_ID.DDR_BUFFER_READ_THRESHOLD,
    DefaultGain = CONTROL_ID.DefaultGain,
    DefaultOffset = CONTROL_ID.DefaultOffset,
    OutputDataActualBits = CONTROL_ID.OutputDataActualBits,
    OutputDataAlignment = CONTROL_ID.OutputDataAlignment,

    CAM_SINGLEFRAMEMODE = CONTROL_ID.CAM_SINGLEFRAMEMODE,
    CAM_LIVEVIDEOMODE = CONTROL_ID.CAM_LIVEVIDEOMODE,
    CAM_IS_COLOR = CONTROL_ID.CAM_IS_COLOR,
    hasHardwareFrameCounter = CONTROL_ID.hasHardwareFrameCounter,
    CONTROL_MAX_ID = CONTROL_ID.CONTROL_MAX_ID,
    CAM_HUMIDITY = CONTROL_ID.CAM_HUMIDITY


def set_log_level(log_level):
    SetQHYCCDLogLevel(log_level)

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
                cameras.append(cam_id)

        # return IDs
        return cameras

    """Storage for link to device."""
    cdef libusb_device_handle *_device
    cdef char _cam_id[32]

    def __init__(self, cam_id: bytes):
        """Create a new driver object for the given ID.

        Args:
            cam_id: ID of camera to initialize.
        """
        strcpy(self._cam_id, cam_id)

    def open(self):
        """Open driver.

        Raises:
            ValueError: If opening failed.
        """

        # to char[32]
        cdef char cam_id[32]
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
        if CloseQHYCCD(self._device) != 0:
            raise ValueError('Could not close device.')

        # release resource
        ReleaseQHYCCDResource()

    def is_control_available(self, control: Control):
        return IsQHYCCDControlAvailable(self._device, int(control.value[0])) == 0

    def get_effective_area(self):
        # get effective area
        cdef unsigned int x, y, width, height
        if GetQHYCCDEffectiveArea(self._device, &x, &y, &width, &height) != 0:
            raise ValueError('Could not fetch effective area.')
        return x, y, width, height

    def get_overscan_area(self):
        # get overscan area
        cdef unsigned int x, y, width, height
        if GetQHYCCDOverScanArea(self._device, &x, &y, &width, &height) != 0:
            raise ValueError('Could not fetch overscan area.')
        return x, y, width, height

    def get_chip_info(self):
        # get chip info
        cdef double chipw, chiph, pixelw, pixelh
        cdef unsigned int imagew, imageh, bpp
        if  GetQHYCCDChipInfo(self._device, &chipw, &chiph, &imagew, &imageh, &pixelw, &pixelh, &bpp) != 0:
            raise ValueError('Could not fetch chip info.')
        return chipw, chiph, imagew, imageh, pixelw, pixelh,

    def get_param(self, param: Control):
        return GetQHYCCDParam(self._device, param.value[0])

    def set_param(self, param: Control, value: float):
        if SetQHYCCDParam(self._device, param.value[0], value) != 0:
            raise ValueError('Could not set parameter %s to %f.' % (param, value))

    def set_temperature(self, temperature: float):
        if ControlQHYCCDTemp(self._device, temperature) != 0:
            raise ValueError("Could not set temperature to %f °C" % temperature)

    def set_resolution(self, x, y, width, height):
        if SetQHYCCDResolution(self._device, x, y, width, height) != 0:
            raise ValueError('Could not set resolution to %dx%d at %d,%d.' % (width, height, x, y))

    def set_bin_mode(self, x, y):
        if SetQHYCCDBinMode(self._device, x, y) != 0:
            raise ValueError('Could not set binning to %dx%d.' % (x, y))

    def set_bits_mode(self, bits):
        if SetQHYCCDBitsMode(self._device, bits) != 0:
            raise ValueError('Could not set bpp to %d.' % bits)

    def expose_single_frame(self):
        return ExpQHYCCDSingleFrame(self._device)

    def get_mem_length(self):
        return GetQHYCCDMemLength(self._device)

    def get_single_frame(self):
        # get memory length
        length = self.get_mem_length()

        # create numpy array of given dimensions
        cdef np.ndarray[unsigned short, ndim=1] img = np.zeros((length), dtype=np.ushort)

        # get pointer to data
        cdef unsigned char* img_data = <unsigned char*> img.data

        # call library
        cdef unsigned int roiSizeX, roiSizeY, bpp, channels;
        if GetQHYCCDSingleFrame(self._device, &roiSizeX, &roiSizeY, &bpp, &channels, img_data) != 0:
            raise ValueError('Could not fetch image data.')

        # return trimmed and reshaped image
        return img[:roiSizeX * roiSizeY].reshape((roiSizeY, roiSizeX))

    def get_time_remaining(self):
        return GetQHYCCDExposureRemaining(self._device)

    def get_status(self):
        cdef unsigned char status
        GetQHYCCDCameraStatus(self._device, &status)
        return status

