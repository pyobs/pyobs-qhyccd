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

    uv run qhyccd-gui


Dependencies
------------
* [pyobs-core](https://github.com/pyobs/pyobs-core) for the core functionality.
* [Astropy](http://www.astropy.org/) for FITS file handling.
* [NumPy](http://www.numpy.org/) for array handling.
