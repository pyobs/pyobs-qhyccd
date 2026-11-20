# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries for releases before this file existed were generated from commit subjects.

## [Unreleased]

- Cooling: the setpoint is written to `CONTROL_COOLER` (the camera regulates by itself) instead of calling
  `ControlQHYCCDTemp` once per ramp step. `cooling_control="temperature"` keeps the old SDK call and now repeats it
  every second, as the SDK asks. Cooling off writes PWM 0 to the manual PWM control.
- The park-and-ramp-back workaround for a cooler PWM above 250 is now off by default (`pwm_wrap_workaround=True` turns
  it on). On a QHY294PRO-M with a 5 A supply a PWM of 255 for minutes did no harm; the collapse seen earlier came
  from a 1.5 A supply. Use a supply that can deliver the current of the cooler.
- The camera's setpoint is read back (`GetQHYCCDParam(CONTROL_COOLER)`), so a ramp after a restart of the module
  starts from the real setpoint. The cooler drive level is clamped to 0 to 255, and on connect PWM 0 is written to an
  idle camera so that it reads a defined value (it reads garbage until a PWM was set).
- GUI: a read mode selector (the camera is opened again in the chosen mode; refused while the cooler is on), gain and
  offset spin boxes with the ranges from the SDK, and a cooler control with target, current temperature and drive level
  (setpoint written to `CONTROL_COOLER` and ramped at 1 degC/min, with a warm-up offer on close, like asi-gui). The window
  size follows the read mode (47M mode: 8336x5648).
- GUI: the pixel size is left out of the FITS header if the SDK returns garbage (QHY294PRO-M), and the header test now
  uses a pixel size in um as the SDK reports it.
- Driver: `QHYCCDDriver.open(read_mode=...)`, `get_read_modes()` and `get_param_limits()`.
- Driver: `QHYCCDDriver` is now written with ctypes and loads the shared library of the SDK
  (`/usr/local/lib/libqhyccd.so`, or the path in the environment variable `QHYCCD_SDK`, or the new `sdk` parameter of
  `QHYCCDCamera` and `QHYCCDVideo`; `qhyccd-gui` takes it as its first argument), like pyobs-asi. The Cython extension
  with the statically linked SDK is gone, and so are the CMake build, `cibuildwheel` and the system packages
  `libusb-1.0-0-dev` and `libcfitsio-dev` for building. The package is a pure Python wheel (hatchling) and needs the SDK
  installed on the machine (see the README). A missing library gives an error that says where it was looked for.
  `get_single_frame` returns 8 bit data in 8 bit mode, `close()` of a closed camera does nothing, and calls on a
  camera that is not open raise `ValueError` instead of passing a null handle to the SDK. The calls into the SDK are
  serialized by the driver (ctypes releases the GIL, the Cython code held it).
- Driver: `close()` no longer calls `CloseQHYCCD` (set `QHYCCD_CALL_CLOSE=1` to call it), only `ReleaseQHYCCDResource`.
  `CloseQHYCCD` of SDK 25.9.29.10 joins a thread handle that it never set, so it worked, hung or segfaulted depending on
  the heap contents (reproducible with `MALLOC_PERTURB_=165`); this was the hang when a module stopped and the freeze of
  the GUI when switching read mode. The handle is leaked until the process ends.
- Build: removed the unused `cython` development dependency and the static copy of the SDK (`lib/usr/local/lib/libqhyccd.a`,
  25 MB); the rest of `lib/` (SDK install script, firmware, udev rules, headers) stays as the source for installing the
  SDK, like `sdk/` in pyobs-asi, and is not part of the sdist.

## [2.3.0] - 2026-11-17

- The GUI writes a FITS header into the frames it saves (it was empty). `QHYCCDCamera`, `QHYCCDVideo` and the GUI build
  the header cards with `make_frame_header` from pyobs-core, so key names and comments are the same everywhere. Needs
  pyobs-core 2.28.0.
- Closing the camera warms up first (pyobs-core `CoolingRampMixin`). The time limit `cooling_close_timeout` is now estimated from the current setpoint and `cooling_rate_warm` instead of a fixed 300 s, so a deeply cooled camera is warmed up completely before it is closed. Needs pyobs-core 2.28.0.

## [2.2.0] - 2026-11-16

- Cooling is ramped by pyobs-core's `CoolingRampMixin` (needs pyobs-core 2.24.0). `set_cooling` returns at once and
  the setpoint is stepped in the background, also when warming up and when disabling cooling. The published
  `CoolingState` shows the commanded setpoint and the target. `cooling_step`/`cooling_wait` are deprecated in
  favour of `cooling_ramp_step` and `cooling_rate_warm`/`cooling_rate_cool`.
- The setpoint set via `set_cooling` no longer overwrites the configured `setpoint` used by `full_reset()`.
- `set_cooling(False)` still has no hardware switch-off (the wrapper has none): the setpoint is ramped up and
  only the published state changes.

## [2.1.3] - 2026-10-04

- Put the email on the copyright line of `LICENSE`, so that GitHub detects the MIT license.

## [2.1.2] - 2026-10-04

- Added `CONTRIBUTING.md` and this changelog, and the readme and project URLs to the package metadata.

## [2.1.1] - 2026-10-04

- Add MIT LICENSE

## [2.1.0] - 2026-09-29

- Add QHYCCDVideo module implementing IVideo via BaseVideo.frames()

## [2.0.3] - 2026-09-28

- Maintenance release (dependency and metadata updates only).

## [2.0.2] - 2026-09-28

- Add IResettable.reset()/full_reset() overrides, make gain/offset defaults configurable

## [2.0.1] - 2026-09-03

- Add GAIN/OFFSET FITS headers (#872)

## [2.0.0] - 2026-08-26

- Require stable pyobs-core>=2.0.0
- Gate auto-merge on the PR author, not the event actor
- Enable Dependabot auto-merge for patch/minor updates
- Camera driver/GUI split: make _run_blocking safe against timeout orphans (#66)
- Fix non-functional exposure abort, latent enum bug, gui.py handle leak (#59)
- tests: assert comm.set_state call shape in window/binning/cooling tests
- Add baseline test suite and CI (pytest, pyrefly), grouped Dependabot
- Disable uv cache in publish job (no deps installed there to cache)
- Pin cibuildwheel action to v4.2.0 (bare @v2 tag doesn't exist upstream)
- Build and publish manylinux wheels via cibuildwheel, drop Python 3.14 cap
- Require pyobs-core>=2.0.0.dev48
- Add dependabot.yml, targeting develop for PRs
- Run QHYCCD SDK calls through a background thread instead of the event loop
- Add Sphinx documentation
- Expand README with install, config, and GUI docs
- Use pyobs-core[gui] extra instead of separate Qt packages
- Refactor `main` to use `qasync.QEventLoop` with context manager.
- install libcfitsio-dev
- install libusb-1.0-0-dev
- Add `--no-sync` flag to ruff workflow command
- fixed path
- publish sdist only
- Update `pyobs-core` dependency to `v2.0.0.dev6`.
- Suppress import typing warning for PySide6 in `gui.py`.
- Standardized capability definitions by introducing `BinningCapabilities` and `WindowCapabilities` for consistent use in `IWindow` and `IBinning`.
- Refactored `_set_state` to improve readability by reformatting multiline method call.
- Add Ruff CI workflows for pyobs-qhyccd and pyobs-zaber
- Refactored state handling: replaced direct state definitions (e.g., `IWindow.State`) with standardized state classes (`WindowState`, `BinningState`, `GainState`, etc.). Modernized `_update_cooling()` and related methods to use these state classes consistently.
- Cleaned up dependencies: removed unused development tools (`flake8`, `pandas-stubs`, `pyside6-stubs`) and added `pyrefly`. Updated `pyobs-core` to `v2.0.0.dev3`.
- Removed DEVELOPMENT.md as it is no longer relevant for the current repository state.
- Added DEVELOPMENT.md documenting migration steps to pyobs 2.0, including tooling updates, API changes, GUI guidelines, testing setup, and repo checklist.
- Cleaned up dependencies: removed unused `flake8`, `pandas-stubs`, and `pyside6-stubs`.
- Replaced `flake8` with `ruff` for linting in pre-commit configuration.
- Removed `.flake8` configuration file.
- Refactored imports, improved logging formatting, and replaced `datetime.timezone.utc` with `datetime.UTC`.
- Updated dependencies and migrated to `pyobs-core` v2. Added new dependencies: `logging-journald`, `psutil`, `ruff`, and `tenacity`. Configured `ruff` for linting and updated build tools.
- - Removed all get_*/list_* methods: get_full_frame, get_window, get_binning, list_binnings, get_cooling, get_temperatures, get_gain, get_offset - Added _available_binnings() helper (sync, returns list[IBinning.State]) - open(): publishes set_capabilities for IWindow (full frame) and IBinning (available binnings), then set_state for initial window, binning, and gain/offset - set_window() / set_binning(): each calls comm.set_state after updating the internal value - set_cooling(): calls comm.set_state(ICooling.State(...)) - _update_cooling(): calls comm.set_state(ITemperatures.State(...)) and comm.set_state(ICooling.State(...)) each polling cycle; also fixed the bare except: to except Exception: - set_gain() / set_offset(): each calls comm.set_state(IGain.State(...)) after writing to the driver

## [1.6.0] - 2026-04-29

- pypi
- core version
- using widgets from pyobs-core
- using datadisplaywidget
- refactored code
- works with actual camera
- added widget for image format
- added widgets for windowing and binning
- mypy
- expose widget working
- format
- added mainwindow and first widget
- uv can build project
- using actual measured temp
- getting temp every second
- more logging, and handling step to setpoint
- added bug checking
- new slow cooling
- new qhyccd driver
- added possibility to set camera params in config
- added offset to IGain
- implement IGain
- log brightness and contrast
- log gain and offset
- effective area for trimsec
- revert
- width and height in unbinned coordinates
- trimsec
- use image size as full_frame, not effective area
- more logging
- using new qhyccd sdk sdk_linux64_25.06.16

## [1.5.1] - 2025-08-14

- Maintenance release (dependency and metadata updates only).

## [1.5.0] - 2025-08-14

- using new qhyccd sdk sdk_linux64_25.06.16

## [1.4.1] - 2025-07-09

- back to poetry for building cython...
- new lock file

## [1.4.0] - 2025-07-07

- migrated to uv
- fixed bug

## [1.3.0] - 2024-12-04

- Maintenance release (dependency and metadata updates only).

## [1.2.2] - 2024-12-04

- added _wait_exposure

## [1.2.1] - 2024-12-04

- no time.sleep

## [1.2.0] - 2024-12-04

- let cooling start with opening of the module
- added cooler values to header
- Implemented first approach to handle a bug that occurs, if the set temperature is too low for the cooler.
- implemented a stepwise cooling
- added the method to set the temperature in driver and actual camera module
- included ICooling interface and the corresponding methods
- implemented get_param method for the driver
- list_binnings method: get available binnings from driver
- removed unused _wait_exposure method
- outsourced creation of fits image and its header
- removed debug prints
- use running loop for getting image from camera
- outsource driver settings before exposure into own method
- corrected exposure time unit for the driver (needs microseconds not miliseconds)
- added the camera module to __init__.py

## [1.1.1] - 2024-12-04

- added import

## [1.1.0] - 2024-12-04

- datetime.utcnow() to datetime.utc(timezone.utc)

## [1.0.1] - 2024-06-17

- finishing up
- removed pyobs-core from requirements
- driver works
- added some methods to wrapper
- init cam
- removed file
- changed QHYCCD to 64bit
- initial commit
