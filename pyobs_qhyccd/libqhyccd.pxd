cdef extern from "/usr/include/libusb-1.0/libusb.h":
    struct libusb_device_handle


cdef extern from "../lib/usr/local/include/qhyccdstruct.h":
    cdef cppclass CONTROL_ID:
        pass


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