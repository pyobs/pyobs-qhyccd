cdef extern from "/usr/include/libusb-1.0/libusb.h":
    struct libusb_device_handle


cdef extern from "../lib/usr/local/include/qhyccdstruct.h":
    cdef enum CONTROL_ID:
        CONTROL_BRIGHTNESS,
        CONTROL_CONTRAST,
        CONTROL_WBR,
        CONTROL_WBB,
        CONTROL_WBG,
        CONTROL_GAMMA,
        CONTROL_GAIN,
        CONTROL_OFFSET,
        CONTROL_EXPOSURE,
        CONTROL_SPEED,
        CONTROL_TRANSFERBIT,
        CONTROL_CHANNELS,
        CONTROL_USBTRAFFIC,
        CONTROL_ROWNOISERE,
        CONTROL_CURTEMP,
        CONTROL_CURPWM,
        CONTROL_MANULPWM,
        CONTROL_CFWPORT,
        CONTROL_COOLER,
        CONTROL_ST4PORT,
        CAM_COLOR,
        CAM_BIN1X1MODE,
        CAM_BIN2X2MODE,
        CAM_BIN3X3MODE,
        CAM_BIN4X4MODE,
        CAM_MECHANICALSHUTTER,
        CAM_TRIGER_INTERFACE,
        CAM_TECOVERPROTECT_INTERFACE,
        CAM_SINGNALCLAMP_INTERFACE,
        CAM_FINETONE_INTERFACE,
        CAM_SHUTTERMOTORHEATING_INTERFACE,
        CAM_CALIBRATEFPN_INTERFACE,
        CAM_CHIPTEMPERATURESENSOR_INTERFACE,
        CAM_USBREADOUTSLOWEST_INTERFACE,

        CAM_8BITS,
        CAM_16BITS,
        CAM_GPS,

        CAM_IGNOREOVERSCAN_INTERFACE,

        QHYCCD_3A_AUTOBALANCE,
        QHYCCD_3A_AUTOEXPOSURE,
        QHYCCD_3A_AUTOFOCUS,
        CONTROL_AMPV,
        CONTROL_VCAM,
        CAM_VIEW_MODE,

        CONTROL_CFWSLOTSNUM,
        IS_EXPOSING_DONE,
        ScreenStretchB,
        ScreenStretchW,
        CONTROL_DDR,
        CAM_LIGHT_PERFORMANCE_MODE,

        CAM_QHY5II_GUIDE_MODE,
        DDR_BUFFER_CAPACITY,
        DDR_BUFFER_READ_THRESHOLD,
        DefaultGain,
        DefaultOffset,
        OutputDataActualBits,
        OutputDataAlignment,

        CAM_SINGLEFRAMEMODE,
        CAM_LIVEVIDEOMODE,
        CAM_IS_COLOR,
        hasHardwareFrameCounter,
        CONTROL_MAX_ID,
        CAM_HUMIDITY

cdef extern from "../lib/usr/local/include/qhyccd.h":
    unsigned int InitQHYCCDResource()
    unsigned int ScanQHYCCD()
    unsigned int GetQHYCCDId(unsigned int index, char *id)
    unsigned int ReleaseQHYCCDResource()
    libusb_device_handle *OpenQHYCCD(char *id)
    unsigned int IsQHYCCDControlAvailable(libusb_device_handle *handle, CONTROL_ID controlId)
    unsigned int SetQHYCCDStreamMode(libusb_device_handle *handle, unsigned char mode)
    unsigned int InitQHYCCD(libusb_device_handle *handle)
    unsigned int CloseQHYCCD(libusb_device_handle *handle)
    unsigned int GetQHYCCDEffectiveArea(libusb_device_handle *h, unsigned int *startX, unsigned int *startY,
                                        unsigned int *sizeX, unsigned int *sizeY)
    unsigned int GetQHYCCDOverScanArea(libusb_device_handle *h, unsigned int *startX, unsigned int *startY,
                                       unsigned int *sizeX, unsigned int *sizeY)
    unsigned int GetQHYCCDChipInfo(libusb_device_handle *h, double *chipw, double *chiph, unsigned int *imagew,
                                   unsigned int *imageh, double *pixelw, double *pixelh, unsigned int *bpp)
    unsigned int SetQHYCCDParam(libusb_device_handle *handle, CONTROL_ID controlId, double value)
    unsigned int SetQHYCCDBitsMode(libusb_device_handle *handle, unsigned int bits)
    double GetQHYCCDParam(libusb_device_handle *handle, CONTROL_ID controlId)
    unsigned int SetQHYCCDResolution(libusb_device_handle *handle, unsigned int x, unsigned int y,
                                     unsigned int xsize, unsigned int ysize);
    unsigned int SetQHYCCDBinMode(libusb_device_handle *handle, unsigned int wbin, unsigned int hbin)
    unsigned int ExpQHYCCDSingleFrame(libusb_device_handle *handle)
    unsigned int GetQHYCCDMemLength(libusb_device_handle *handle)
    unsigned int GetQHYCCDSingleFrame(libusb_device_handle *handle,unsigned int *w, unsigned int *h,
                                      unsigned int *bpp, unsigned int *channels, unsigned char *imgdata)
    unsigned int CancelQHYCCDExposingAndReadout(libusb_device_handle *handle)
    unsigned int GetQHYCCDExposureRemaining(libusb_device_handle *handle)
    unsigned int GetQHYCCDCameraStatus(libusb_device_handle *handle, unsigned char *buf);
    unsigned int ControlQHYCCDTemp(libusb_device_handle *handle, double targettemp);
    void SetQHYCCDLogLevel(unsigned int logLevel);
