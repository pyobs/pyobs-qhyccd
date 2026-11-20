QHYCCD module for *pyobs*
=========================

This is a [pyobs](https://www.pyobs.org) module for QHYCCD cameras.


QHYCCD SDK
----------
The module talks to the camera through the shared library of the QHYCCD SDK (`libqhyccd.so`) with ctypes. The
`lib/` folder holds the SDK 25.9.29.10 for Linux x86-64 as published by QHYCCD, with the firmware, the udev rules and an
install script (see https://www.qhyccd.com/ for the official download and newer versions). On Debian/Ubuntu, install
the dependencies of the SDK and the SDK itself (as root):

    sudo apt install libusb-1.0-0 libudev1
    cd lib && sudo ./install.sh

then reconnect the camera, so that the firmware is loaded by the udev rules. The library is expected at
`/usr/local/lib/libqhyccd.so`. Another path can be given in the environment variable `QHYCCD_SDK` or the `sdk`
parameter of the camera (see below).


Install *pyobs-qhyccd*
------------------------
Clone the repository:

    git clone https://github.com/pyobs/pyobs-qhyccd.git
    cd pyobs-qhyccd

Install it with [uv](https://docs.astral.sh/uv/):

    uv sync

Alternatively, with plain `venv`/`pip`:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install .


Configuration
-------------
The *QHYCCDCamera* class is derived from *BaseCamera* (see *pyobs* documentation) and adds a few new parameters:

    setpoint:
        The cooling temperature setpoint in degrees Celsius (default: -10).
    params:
        Optional dictionary of additional QHYCCD control values to set on connect.
    sdk:
        Path to libqhyccd.so of the QHYCCD SDK (default: environment variable QHYCCD_SDK, else
        /usr/local/lib/libqhyccd.so).
    cooling_rate_cool / cooling_rate_warm:
        Maximum rate in degC/min when lowering / raising the setpoint (default: 1.0 / 1.0). Warming up
        (raising the setpoint or switching cooling off) is ramped at cooling_rate_warm before the cooler is
        switched off. None means one step. See *CoolingRampMixin* in *pyobs-core* for the other cooling_* options.
    cooling_step, cooling_wait:
        Deprecated. They are converted to cooling_ramp_step and the two rates.

A basic module configuration would look like this:

    class: pyobs_qhyccd.QHYCCDCamera
    name: QHYCCD camera
    setpoint: -10


GUI
---
For testing a camera without a full *pyobs* setup, install the optional `gui` extra:

    uv sync --extra gui

and run:

    uv run qhyccd-gui [path/to/libqhyccd.so]


Dependencies
------------
* [pyobs-core](https://github.com/pyobs/pyobs-core) for the core functionality.
* [Astropy](http://www.astropy.org/) for FITS file handling.
* [NumPy](http://www.numpy.org/) for array handling.
