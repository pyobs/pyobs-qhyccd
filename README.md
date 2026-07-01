QHYCCD module for *pyobs*
=========================

This is a [pyobs](https://www.pyobs.org) module for QHYCCD cameras.


System dependencies
--------------------
On Debian/Ubuntu, plus the QHYCCD driver:

    sudo apt install build-essential python3-dev libusb-1.0-0-dev libcfitsio-dev


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
    cooling_step:
        Maximum change in setpoint per cooling adjustment, in degrees Celsius (default: 1.0).
    cooling_wait:
        Time to wait between cooling adjustments, in seconds (default: 60.0).

A basic module configuration would look like this:

    class: pyobs_qhyccd.QHYCCDCamera
    name: QHYCCD camera
    setpoint: -10


GUI
---
For testing a camera without a full *pyobs* setup, install the optional `gui` extra:

    uv sync --extra gui

and run:

    uv run qhyccd-gui


Dependencies
------------
* [pyobs-core](https://github.com/pyobs/pyobs-core) for the core functionality.
* [Astropy](http://www.astropy.org/) for FITS file handling.
* [NumPy](http://www.numpy.org/) for array handling.
