"""Characterize a cooled QHY camera in the dark.

Run with the lens capped and without any other program using the camera, e.g.::

    uv run python tools/characterize.py bias
    uv run python tools/characterize.py gain
    uv run python tools/characterize.py temperature
    uv run python tools/characterize.py flat   # lens uncapped, pointed at a steady, defocused light source
    uv run python tools/characterize.py short  # same light source
    uv run python tools/characterize.py readout
    uv run python tools/characterize.py pixels --target-temp -5  # lens capped
    uv run python tools/characterize.py report

Steps (all on a central 2048x2048 window of the effective area, USB traffic as set by --usb-traffic):

* ``bias``: bias level, read noise and clipping vs. gain and offset.
* ``gain``: gain in ADU/e- from the shot noise of the dark current (photon transfer without light). Needs a warm
  sensor, so the cooler stays off (default) and the script waits until the temperature is stable.
* ``temperature``: read noise, dark current and hot pixels vs. sensor temperature. The cooler target is moved in steps
  of at most 1 degC/min and the camera is warmed up again afterwards.
* ``cooling``: fixed manual PWM levels from ambient, held in ascending order (``--pwms``), to find out where and why the
  cooler stops working. Logs the sensor temperature every 5 s to ``cooling.jsonl``, stops a level as soon as the sensor
  warms by 1 degC while the PWM is held, and repeats a level once from ambient.
* ``sdkcool``: the SDK's own cooler control instead of the PI controller: ``--sdk-mode temp`` calls
  ``ControlQHYCCDTemp`` once per second, ``--sdk-mode cooler`` sets ``CONTROL_COOLER`` once. The target
  (``--cool-target``) is reached in steps of 1 degC/min or, with ``--jump``, in one step. Logs the PWM the SDK chooses
  to ``sdkcool.jsonl`` and stops on a collapse (sensor 1 degC above its lowest value).
* ``driver``: the cooling procedure of the pyobs-qhyccd module (``QHYCCDCamera``) on the real camera: opens the
  module, ``set_cooling`` to ``--cool-target`` (the module ramps), holds ``--hold`` s, reads the setpoint and power
  back, switches cooling off and checks PWM 0. ``--sdk-mode`` chooses ``cooling_control`` (cooler/temp),
  ``--wrap-workaround`` the PWM > 250 workaround. Log: ``driver.jsonl``, the checks are in its last record.
* ``flat``: photon transfer curve from pairs of frames of a steady, roughly uniform light source (e.g. a wall): gain in
  e-/ADU, read noise in e-, saturation and linearity. The bias level comes from the fit of level vs. exposure time.
* ``short``: signal vs. exposure times from the minimum up to 100 ms with a steady light source, to find an offset in
  the exposure time or a nonlinearity for short exposures.
* ``readout``: time per frame for the full frame vs. binning and bit depth, for several USB traffic values, and the
  read noise for each.
* ``pixels``: temporal noise of every pixel from a stack of full-frame bias frames: the share of pixels with
  excess noise (random telegraph signal, "salt and pepper"), fixed offsets, and how many of the noisy ones flip between
  two levels. Use ``--target-temp`` to cool first, otherwise the sensor is measured warm.
* ``report``: plots (in ``images/``) and a CSV file for every JSON lines file, from the measured data. Needs no camera.

The QHY SDK is called directly through ctypes (``/usr/local/lib/libqhyccd.so``, see ``--sdk``). The SDK's own
temperature control (ControlQHYCCDTemp) lets the PWM run above 250, where it wraps and the cooler stops, so the script
holds the target itself with a PI controller on the manual PWM (limited to 240) and switches the cooler off with PWM 0.
The read mode of the camera is chosen with ``--read-mode`` (0 is the SDK default); results of a read mode other than 0
go to ``<serial number>_mode<N>``.

Results are appended to JSON lines files in ``characterization/<model>/<serial number>/``, so a run can be repeated or
resumed. See ``characterization/README.md``.
"""

import argparse
import csv
import ctypes
import json
import math
import sys
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits

# control IDs of the SDK (qhyccdstruct.h)
CONTROL_GAIN = 6
CONTROL_OFFSET = 7
CONTROL_EXPOSURE = 8
CONTROL_SPEED = 9
CONTROL_TRANSFERBIT = 10
CONTROL_USBTRAFFIC = 12
CONTROL_CURTEMP = 14
CONTROL_CURPWM = 15
CONTROL_MANULPWM = 16
CONTROL_COOLER = 18
CAM_BIN_MODES = {1: 21, 2: 22, 3: 23, 4: 24}
QHYCCD_ERROR = 0xFFFFFFFF

ROI = 2048
CUTOUT = 512
RAMP_STEP_C = 1.0
RAMP_STEP_S = 60.0  # together: 1 degC/min, as in the pyobs driver
MAX_POWER = 90
PWM_MAX = 240  # the SDK's PWM wraps above 250 and the cooler stops (known QHY bug), so never ask for more
PWM_KP = 15.0  # PWM per degC of error
PWM_KI = 0.3  # PWM per degC and second
STABLE_RANGE_C = 0.2
STABLE_TIME_S = 30.0
POLL_S = 5.0  # temperature readings while waiting for a stable sensor
LIMIT_TIME_S = 120.0  # the cooler must be above MAX_POWER for this long before the series stops
TARGET_JITTER_C = 1.2  # tolerance of the sensor reading while the cooler holds a target

GAINS = [0, 10, 50, 100, 200, 400, 800, 1600, 3000]
OFFSETS = [0, 10, 50, 140, 200]
GAIN_TEST_GAINS = [0, 100, 800]
GAIN_TEST_EXPOSURES = [30.0, 100.0, 300.0]
TEMPERATURES = [10, 5, 0, -5, -10, -15]
SWEEP_PWMS = [100, 140, 170, 200, 220, 240]
SWEEP_HOLD_S = 600.0  # longest hold of one fixed PWM level
SWEEP_MIN_S = 240.0  # shortest hold before the temperature may count as settled
SWEEP_SETTLE_S = 180.0  # the sensor counts as settled if it moved less than SWEEP_SETTLE_C in this time
SWEEP_SETTLE_C = 0.1
SWEEP_COLLAPSE_C = 1.0  # warming by this much above the lowest temperature of a level counts as a collapse
SWEEP_COLLAPSE_AFTER_S = 60.0  # ignore warming in the first seconds of a level
DARK_EXPOSURES = [60.0, 300.0]
DEFAULT_GAIN = 10  # as in pyobs-qhyccd
FULL_SCALE = 65535
FLAT_GAINS = [0, 100, 400, 1000, 2000]
FLAT_POINTS = 12
FLAT_RANGE = (0.03, 0.85)  # fractions of full scale covered by the exposure ladder
FLAT_MAX_EXPOSURE_S = 20.0
LINEAR_MAX_FRACTION = 0.6  # bias and rate are fitted below this level
FIT_MAX_FRACTION = 0.75  # the photon transfer fit uses signals below this fraction of full scale
DEFAULT_OFFSET = 140  # as in pyobs-qhyccd
DEFAULT_USB_TRAFFIC = 60  # as in pyobs-qhyccd
READOUT_USB_TRAFFICS = [0, 60, 150]
SHORT_EXPOSURES_S = [0.0, 0.00005, 0.0001, 0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1]
SHORT_REFERENCE_S = 0.01  # repeated between the points to follow the light source
SHORT_FRAMES = 5
SHORT_FIT_MIN_S = 0.001  # the exposure offset is fitted from exposures from here on
READOUT_FRAMES = 5
PIXEL_FRAMES = 60
PIXEL_SAMPLE = 100_000  # pixels whose full time series is kept to look for two-level (telegraph) behaviour
PIXEL_NOISY_FACTOR = 5.0  # a pixel is noisy if its temporal std is this many times the median


class CoolerLimit(Exception):
    """The cooler cannot reach the requested temperature."""


class Camera:
    """The QHY SDK through ctypes, for one camera in single-frame mode."""

    def __init__(self, sdk: str, read_mode: int = 0, usb_traffic: int = DEFAULT_USB_TRAFFIC) -> None:
        lib = ctypes.CDLL(sdk)
        lib.GetQHYCCDParam.restype = ctypes.c_double
        lib.GetQHYCCDParam.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.SetQHYCCDParam.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_double]
        lib.ControlQHYCCDTemp.argtypes = [ctypes.c_void_p, ctypes.c_double]
        lib.OpenQHYCCD.restype = ctypes.c_void_p
        lib.OpenQHYCCD.argtypes = [ctypes.c_char_p]
        lib.GetQHYCCDParamMinMaxStep.argtypes = [ctypes.c_void_p, ctypes.c_int] + [ctypes.POINTER(ctypes.c_double)] * 3
        self.lib = lib
        self.sdk = sdk
        self.read_mode = read_mode
        self._check(lib.InitQHYCCDResource(), "InitQHYCCDResource")
        if lib.ScanQHYCCD() == 0:
            raise SystemExit("No camera found.")
        cam_id = ctypes.create_string_buffer(64)
        self._check(lib.GetQHYCCDId(0, cam_id), "GetQHYCCDId")
        self.id = cam_id.value.decode()
        # the ID is <model>-<serial number>
        self.model, _, self.serial = self.id.partition("-")
        self.handle = ctypes.c_void_p(lib.OpenQHYCCD(cam_id.value))
        if not self.handle:
            raise SystemExit("Could not open the camera.")
        self.read_modes = self._read_modes()
        if read_mode >= len(self.read_modes):
            raise SystemExit(f"Read mode {read_mode} does not exist, there are {len(self.read_modes)}.")
        # as in the SDK samples: read mode and stream mode before InitQHYCCD
        self._check(lib.SetQHYCCDReadMode(self.handle, read_mode), "SetQHYCCDReadMode")
        self._check(lib.SetQHYCCDStreamMode(self.handle, ctypes.c_uint8(0)), "SetQHYCCDStreamMode")
        self._check(lib.InitQHYCCD(self.handle), "InitQHYCCD")
        self.set_param(CONTROL_TRANSFERBIT, 16)
        self.set_param(CONTROL_USBTRAFFIC, usb_traffic)
        self.usb_traffic = usb_traffic

        self.info = self._info()
        self.controls = {
            name: self.limits(cid)
            for name, cid in {
                "Gain": CONTROL_GAIN,
                "Offset": CONTROL_OFFSET,
                "Exposure": CONTROL_EXPOSURE,
                "USBTraffic": CONTROL_USBTRAFFIC,
                "Speed": CONTROL_SPEED,
                "TransferBit": CONTROL_TRANSFERBIT,
                "ManualPWM": CONTROL_MANULPWM,
            }.items()
        }
        self.min_exposure_us = int(self.controls["Exposure"]["min"])
        x0, y0, w, h = self.info["EffectiveArea"]
        self.left = x0 + (w - ROI) // 2 // 8 * 8
        self.top = y0 + (h - ROI) // 2 // 8 * 8
        self._cooler_on = False
        self._target: int | None = None
        self._stop = threading.Event()
        self._controller: threading.Thread | None = None
        self._pwm = 0
        # the temperature reads 0.0 until the first update arrives
        for _ in range(100):
            if self.temperature() != 0.0:
                break
            time.sleep(0.1)

    @staticmethod
    def _check(result: int, what: str) -> None:
        if result == QHYCCD_ERROR:
            raise RuntimeError(f"{what} failed.")

    def _read_modes(self) -> list[dict[str, Any]]:
        n = ctypes.c_uint32()
        self._check(self.lib.GetQHYCCDNumberOfReadModes(self.handle, ctypes.byref(n)), "GetQHYCCDNumberOfReadModes")
        modes = []
        for i in range(n.value):
            name, w, h = ctypes.create_string_buffer(64), ctypes.c_uint32(), ctypes.c_uint32()
            self.lib.GetQHYCCDReadModeName(self.handle, i, name)
            self.lib.GetQHYCCDReadModeResolution(self.handle, i, ctypes.byref(w), ctypes.byref(h))
            modes.append({"index": i, "name": name.value.decode(), "width": w.value, "height": h.value})
        return modes

    def _info(self) -> dict[str, Any]:
        d = [ctypes.c_double() for _ in range(4)]
        u = [ctypes.c_uint32() for _ in range(3)]
        self._check(
            self.lib.GetQHYCCDChipInfo(self.handle, *[ctypes.byref(v) for v in d], *[ctypes.byref(v) for v in u]),
            "GetQHYCCDChipInfo",
        )
        areas = {}
        for key, func in (
            ("EffectiveArea", self.lib.GetQHYCCDEffectiveArea),
            ("OverscanArea", self.lib.GetQHYCCDOverScanArea),
        ):
            v = [ctypes.c_uint32() for _ in range(4)]
            self._check(func(self.handle, *[ctypes.byref(x) for x in v]), key)
            areas[key] = tuple(x.value for x in v)
        return {
            "Name": self.model,
            "ID": self.id,
            "ChipWidthMM": d[0].value,
            "ChipHeightMM": d[1].value,
            "PixelWidthUM": d[2].value,
            "PixelHeightUM": d[3].value,
            "ImageWidth": u[0].value,
            "ImageHeight": u[1].value,
            "ReadMode": {**self.read_modes[self.read_mode]},
            "ReadModes": self.read_modes,
            "SupportedBins": [
                b for b, cid in CAM_BIN_MODES.items() if self.lib.IsQHYCCDControlAvailable(self.handle, cid) == 0
            ],
            **areas,
        }

    def limits(self, control: int) -> dict[str, Any]:
        lo, hi, step = ctypes.c_double(), ctypes.c_double(), ctypes.c_double()
        available = self.lib.IsQHYCCDControlAvailable(self.handle, control) == 0
        ok = self.lib.GetQHYCCDParamMinMaxStep(
            self.handle, control, ctypes.byref(lo), ctypes.byref(hi), ctypes.byref(step)
        )
        return {"available": available, "min": lo.value, "max": hi.value, "step": step.value, "result": int(ok)}

    def get_param(self, control: int) -> float:
        return float(self.lib.GetQHYCCDParam(self.handle, control))

    def set_param(self, control: int, value: float) -> None:
        self._check(self.lib.SetQHYCCDParam(self.handle, control, float(value)), f"SetQHYCCDParam({control})")

    def set_roi(self, x: int, y: int, width: int, height: int, bins: int = 1) -> None:
        """Window in unbinned x, y and binned width, height, like the pyobs driver."""
        self._check(self.lib.SetQHYCCDBinMode(self.handle, bins, bins), "SetQHYCCDBinMode")
        self._check(self.lib.SetQHYCCDResolution(self.handle, x, y, width, height), "SetQHYCCDResolution")

    def expose(self) -> np.ndarray:
        """Starts an exposure and waits for the frame (the SDK blocks until it is read out)."""
        lib = self.lib
        lib.ExpQHYCCDSingleFrame(self.handle)  # may return a positive status code that is not an error
        buf = np.zeros(lib.GetQHYCCDMemLength(self.handle), dtype=np.uint8)
        w, h, bpp, ch = (ctypes.c_uint32() for _ in range(4))
        self._check(
            lib.GetQHYCCDSingleFrame(
                self.handle,
                ctypes.byref(w),
                ctypes.byref(h),
                ctypes.byref(bpp),
                ctypes.byref(ch),
                buf.ctypes.data_as(ctypes.c_void_p),
            ),
            "GetQHYCCDSingleFrame",
        )
        if bpp.value != 16 or ch.value != 1:
            raise RuntimeError(f"Unexpected frame format: {bpp.value} bit, {ch.value} channels.")
        return buf[: w.value * h.value * 2].view(np.uint16).reshape(h.value, w.value).copy()

    def grab(self, exposure_s: float, gain: int, offset: int) -> np.ndarray:
        self.set_param(CONTROL_GAIN, gain)
        self.set_param(CONTROL_OFFSET, offset)
        self.set_param(CONTROL_EXPOSURE, max(int(exposure_s * 1e6), self.min_exposure_us))
        self.set_roi(self.left, self.top, ROI, ROI)
        return self.expose()

    def temperature(self) -> float:
        return self.get_param(CONTROL_CURTEMP)

    def power(self) -> int:
        """Cooler power in percent. The SDK gives the PWM as 0 to 255 (it was seen to read garbage above that)."""
        pwm = self.get_param(CONTROL_CURPWM)
        return int(round(min(max(pwm, 0.0), 255.0) / 255 * 100))

    def cooler_on(self) -> bool:
        return self._cooler_on

    def target(self) -> int | None:
        """The last target set by this script."""
        return self._target

    def _control_loop(self) -> None:
        """PI controller on the manual PWM, once per second.

        The SDK's own temperature control (ControlQHYCCDTemp) lets the PWM run above 250, where it wraps around and the
        cooler stops, so the sensor warms up quickly. Here the PWM is limited to PWM_MAX instead.
        """
        integral = 0.0
        while not self._stop.wait(1.0):
            target = self._target
            if target is None:
                continue
            error = self.temperature() - target  # positive: too warm, needs more cooling
            output = PWM_KP * error + integral
            if 0.0 < output < PWM_MAX or (output >= PWM_MAX and error < 0) or (output <= 0.0 and error > 0):
                integral = min(max(integral + PWM_KI * error, 0.0), PWM_MAX)  # no windup while saturated
            self._pwm = int(round(min(max(PWM_KP * error + integral, 0.0), PWM_MAX)))
            self.set_param(CONTROL_MANULPWM, self._pwm)

    def set_cooler(self, on: bool, target: int | None = None) -> None:
        """Cooler on with a target, or off (PWM 0). The target is held by a thread, see ``_control_loop``."""
        if on:
            if target is None:
                target = self._target
            if target is None:
                raise ValueError("No target given.")
            self._target = target
            if self._controller is None:
                self._stop.clear()
                self._controller = threading.Thread(target=self._control_loop, daemon=True)
                self._controller.start()
        else:
            self._target = None
            if self._controller is not None:
                self._stop.set()
                self._controller.join()
                self._controller = None
            self._pwm = 0
            self.set_param(CONTROL_MANULPWM, 0)
        self._cooler_on = on

    def close(self) -> None:
        if self._controller is not None:
            self.set_cooler(False)
        self.lib.CloseQHYCCD(self.handle)
        self.lib.ReleaseQHYCCDResource()


class Output:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        (folder / "frames").mkdir(parents=True, exist_ok=True)
        (folder / "images").mkdir(exist_ok=True)

    def write(self, name: str, record: dict[str, Any]) -> None:
        with open(self.folder / f"{name}.jsonl", "a") as f:
            f.write(json.dumps(record) + "\n")

    def read(self, name: str) -> list[dict[str, Any]]:
        path = self.folder / f"{name}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def save_cutout(self, name: str, data: np.ndarray, **header: Any) -> None:
        y, x = (data.shape[0] - CUTOUT) // 2, (data.shape[1] - CUTOUT) // 2
        hdu = fits.PrimaryHDU(data[y : y + CUTOUT, x : x + CUTOUT])
        for key, value in header.items():
            hdu.header[key[:8].upper()] = value
        hdu.writeto(self.folder / "frames" / f"{name}.fits", overwrite=True)


def pair_stats(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    """Noise from the difference of two frames (removes fixed pattern), mean level, clipping."""
    d = a.astype(np.float64) - b.astype(np.float64)
    mad = 1.4826 * float(np.median(np.abs(d - np.median(d))))
    return {
        "mean": float((a.mean() + b.mean()) / 2),
        "median": float((np.median(a) + np.median(b)) / 2),
        "noise_std_adu": float(d.std() / math.sqrt(2)),
        "noise_mad_adu": mad / math.sqrt(2),
        "clipped_frac": float(((a == 0).mean() + (b == 0).mean()) / 2),
    }


def bias_pair(cam: Camera, gain: int, offset: int) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    cam.grab(0.0, gain, offset)  # first frame after a setting change is discarded
    a = cam.grab(0.0, gain, offset)
    b = cam.grab(0.0, gain, offset)
    return a, b, pair_stats(a, b)


def wait_stable(cam: Camera, out: Output, target: int | None, label: str) -> None:
    """Wait until the sensor temperature stops changing (and has reached the target)."""
    history: deque[tuple[float, float]] = deque()
    high_since: float | None = None
    while True:
        now, temp = time.time(), cam.temperature()
        out.write("templog", {"time": now, "label": label, "temp": temp, "power": cam.power(), "target": target})
        history.append((now, temp))
        # keep slightly more than the required time, samples come every POLL_S
        while history and now - history[0][0] > STABLE_TIME_S + 5:
            history.popleft()
        temps = [t for _, t in history]
        full = now - history[0][0] >= STABLE_TIME_S * 0.9
        at_target = target is None or abs(float(np.mean(temps)) - target) <= 0.5
        # without a target (warm sensor) only a slow drift is needed, the dark signal is measured per frame pair
        tolerance = TARGET_JITTER_C if target is not None else 2.5 * STABLE_RANGE_C
        if full and at_target and max(temps) - min(temps) <= tolerance:
            return
        if target is None or cam.power() <= MAX_POWER or temp - target <= 1.0:
            high_since = None
        elif high_since is None:
            high_since = now
        if high_since is not None and now - high_since >= LIMIT_TIME_S:
            raise CoolerLimit(f"cooler at {cam.power()}% and sensor at {temp:.1f} degC, target {target} degC")
        print(f"  {label}: T={temp:.1f} degC power={cam.power()}% target={target}", flush=True)
        time.sleep(POLL_S)


def ramp_to(cam: Camera, out: Output, target: int) -> None:
    """Move the cooler target to the new value in steps, at most 1 degC/min.

    Raises CoolerLimit if the cooler stays at its maximum power while the sensor is more than 1 degC above the target.
    """
    target_now = cam.target()
    temp_now = round(cam.temperature())
    # start from the sensor if there is no target yet or the sensor cannot follow it (e.g. after CoolerLimit)
    current = temp_now if target_now is None or temp_now - target_now > 2 else target_now
    cam.set_cooler(True, current)
    high_since: float | None = None
    while current != target:
        current += int(math.copysign(RAMP_STEP_C, target - current))
        cam.set_cooler(True, current)
        step_start = time.time()
        while time.time() - step_start < RAMP_STEP_S:
            time.sleep(POLL_S)
            now, temp = time.time(), cam.temperature()
            if cam.power() <= MAX_POWER or temp - current <= 1.0:
                high_since = None
            elif high_since is None:
                high_since = now
            if high_since is not None and now - high_since >= LIMIT_TIME_S:
                raise CoolerLimit(f"cooler at {cam.power()}% and sensor at {temp:.1f} degC, target {current} degC")
        out.write(
            "templog",
            {"time": time.time(), "label": "ramp", "temp": cam.temperature(), "power": cam.power(), "target": current},
        )


def warm_up(cam: Camera, out: Output, ambient: int) -> None:
    print(
        f"Warming up to {ambient} degC at {RAMP_STEP_C / RAMP_STEP_S * 60:.0f} degC/min and switching the cooler off.",
        flush=True,
    )
    if cam.cooler_on():
        ramp_to(cam, out, ambient)
    cam.set_cooler(False)


def run_bias(cam: Camera, out: Output, gains: list[int], offsets: list[int]) -> None:
    for gain in gains:
        for offset in offsets:
            a, _, stats = bias_pair(cam, gain, offset)
            record = {"gain": gain, "offset": offset, "temp": cam.temperature(), "time": time.time(), **stats}
            out.write("bias", record)
            print(
                f"gain={gain:3d} offset={offset:3d} mean={stats['mean']:8.1f} noise={stats['noise_std_adu']:5.2f} ADU "
                f"clipped={stats['clipped_frac']:.4f}",
                flush=True,
            )
            if offset == DEFAULT_OFFSET:
                out.save_cutout(f"bias_g{gain}_o{offset}", a, gain=gain, offset=offset, temp=cam.temperature())


def run_gain(
    cam: Camera, out: Output, gains: list[int], exposures: list[float], offset: int, target_temp: int | None
) -> None:
    ambient = round(cam.temperature())
    try:
        if target_temp is None:
            if cam.cooler_on():
                print("Switching the cooler off and waiting for a stable sensor temperature.", flush=True)
                cam.set_cooler(False)
            wait_stable(cam, out, None, "warm")
        else:
            print(f"Cooling to {target_temp} degC ...", flush=True)
            ramp_to(cam, out, target_temp)
            wait_stable(cam, out, target_temp, f"stabilize {target_temp}")
        _gain_frames(cam, out, gains, exposures, offset)
    finally:
        if target_temp is not None:
            warm_up(cam, out, ambient)


def _gain_frames(cam: Camera, out: Output, gains: list[int], exposures: list[float], offset: int) -> None:
    for gain in gains:
        _, _, bias = bias_pair(cam, gain, offset)
        for exposure in exposures:
            cam.grab(exposure, gain, offset)  # discard the first frame after a setting change
            a = cam.grab(exposure, gain, offset)
            b = cam.grab(exposure, gain, offset)
            stats = pair_stats(a, b)
            record = {
                "gain": gain,
                "offset": offset,
                "exposure": exposure,
                "temp": cam.temperature(),
                "power": cam.power(),
                "time": time.time(),
                "bias_mean": bias["mean"],
                "signal_adu": stats["mean"] - bias["mean"],
                "variance_adu2": stats["noise_std_adu"] ** 2,
                "variance_mad_adu2": stats["noise_mad_adu"] ** 2,
            }
            out.write("gain", record)
            out.save_cutout(f"gain_g{gain}_t{int(exposure)}", a, gain=gain, offset=offset, exptime=exposure)
            print(
                f"gain={gain:3d} t={exposure:5.0f}s signal={record['signal_adu']:8.2f} ADU "
                f"variance={record['variance_adu2']:8.2f} ADU^2 T={record['temp']:.1f}",
                flush=True,
            )


def crop(data: np.ndarray) -> np.ndarray:
    y, x = (data.shape[0] - CUTOUT) // 2, (data.shape[1] - CUTOUT) // 2
    return data[y : y + CUTOUT, x : x + CUTOUT]


def flat_ladder(cam: Camera, gain: int, offset: int) -> list[float]:
    """Exposure times (s) that cover FLAT_RANGE of the full scale, from a probe of the light level."""
    guess = offset * 10.0  # bias level estimate, only used to set the ladder
    min_s = cam.min_exposure_us * 1e-6
    t, rate = 0.01, 0.0
    for _ in range(5):
        cam.grab(t, gain, offset)  # discard
        level = float(np.median(crop(cam.grab(t, gain, offset))))
        rate = (level - guess) / t
        if rate <= 0:
            raise SystemExit("No light on the sensor, check the lens cap and the light source.")
        if 0.2 * FULL_SCALE < level < 0.6 * FULL_SCALE:
            break
        t = float(np.clip(0.4 * (FULL_SCALE - guess) / rate, min_s, FLAT_MAX_EXPOSURE_S))
    levels = np.geomspace(*FLAT_RANGE, FLAT_POINTS) * (FULL_SCALE - guess)
    exposures = [round(float(level / rate), 6) for level in levels]
    usable = [e for e in exposures if min_s <= e <= FLAT_MAX_EXPOSURE_S]
    if len(usable) < FLAT_POINTS:
        print(f"  gain {gain}: only {len(usable)} of {FLAT_POINTS} exposures are within the camera limits.", flush=True)
    return usable


def run_flat(cam: Camera, out: Output, gains: list[int], offset: int) -> None:
    for gain in gains:
        ladder = flat_ladder(cam, gain, offset)
        if len(ladder) < 4:
            print(f"gain={gain:3d}: too few usable exposures, skipping.", flush=True)
            continue
        print(f"gain={gain:3d}: {len(ladder)} exposures from {ladder[0]:.6f} to {ladder[-1]:.4f} s", flush=True)
        pairs = []
        for exposure in ladder:
            cam.grab(exposure, gain, offset)  # discard the first frame after a setting change
            a, b = crop(cam.grab(exposure, gain, offset)), crop(cam.grab(exposure, gain, offset))
            pairs.append((exposure, a, b, cam.temperature(), time.time()))

        # level = bias + rate * exposure, fitted in the linear regime; the intercept is the bias without a cap
        exposures = np.array([p[0] for p in pairs])
        means = np.array([(p[1].mean() + p[2].mean()) / 2 for p in pairs])
        low = means < LINEAR_MAX_FRACTION * FULL_SCALE
        if low.sum() < 3:
            low = np.ones_like(low)
        rate, bias = np.polyfit(exposures[low], means[low], 1)

        for (exposure, a, b, temp, now), mean in zip(pairs, means, strict=True):
            ratio = (a.mean() - bias) / (b.mean() - bias)  # lamp drift between the two frames
            stats = pair_stats(a, (b.astype(np.float64) - bias) * ratio + bias)
            record = {
                "gain": gain,
                "offset": offset,
                "exposure": exposure,
                "temp": temp,
                "time": now,
                "bias_fit": float(bias),
                "rate_adu_s": float(rate),
                "signal_adu": float(mean - bias),
                "variance_adu2": stats["noise_std_adu"] ** 2,
                "variance_mad_adu2": stats["noise_mad_adu"] ** 2,
                "drift_pct": float((ratio - 1) * 100),
                "sat_frac": float(((a >= FULL_SCALE).mean() + (b >= FULL_SCALE).mean()) / 2),
                "max_adu": int(max(a.max(), b.max())),
                "nonlin_pct": float((mean - (bias + rate * exposure)) / (rate * exposure) * 100),
            }
            out.write("flat", record)
            print(
                f"  t={exposure:9.6f}s signal={record['signal_adu']:8.1f} ADU variance={record['variance_adu2']:9.1f} "
                f"drift={record['drift_pct']:+.2f}% nonlin={record['nonlin_pct']:+.2f}%",
                flush=True,
            )
        out.save_cutout(f"flat_g{gain}_low", pairs[0][1], gain=gain, offset=offset, exptime=pairs[0][0])
        out.save_cutout(f"flat_g{gain}_high", pairs[-1][1], gain=gain, offset=offset, exptime=pairs[-1][0])


def run_temperature(
    cam: Camera, out: Output, temperatures: list[int], gain: int, offset: int, exposures: list[float] | None = None
) -> None:
    ambient = round(cam.temperature())
    try:
        for target in temperatures:
            print(f"Cooling to {target} degC ...", flush=True)
            try:
                ramp_to(cam, out, target)
                wait_stable(cam, out, target, f"stabilize {target}")
            except CoolerLimit as e:
                print(f"Stopping the series: {e}", flush=True)
                out.write("temperature", {"time": time.time(), "target": target, "limit": str(e)})
                break
            _, _, bias = bias_pair(cam, gain, offset)
            for exposure in exposures or DARK_EXPOSURES:
                cam.grab(exposure, gain, offset)  # discard
                da = cam.grab(exposure, gain, offset)
                db = cam.grab(exposure, gain, offset)
                dark = pair_stats(da, db)
                signal_mean = dark["mean"] - bias["mean"]
                signal_median = dark["median"] - bias["median"]
                hot = float((da > np.median(da) + 20 * bias["noise_mad_adu"]).mean())
                record = {
                    "target": target,
                    "temp": cam.temperature(),
                    "power": cam.power(),
                    "time": time.time(),
                    "gain": gain,
                    "offset": offset,
                    "exposure": exposure,
                    "bias_noise_adu": bias["noise_std_adu"],
                    "bias_mean": bias["mean"],
                    "dark_noise_adu": dark["noise_std_adu"],
                    "dark_adu_per_s_mean": signal_mean / exposure,
                    "dark_adu_per_s_median": signal_median / exposure,
                    "hot_frac": hot,
                }
                out.write("temperature", record)
                out.save_cutout(f"dark_T{target}_t{int(exposure)}", da, temp=record["temp"], exptime=exposure)
                print(
                    f"T={record['temp']:.1f} t={exposure:.0f}s bias noise={bias['noise_std_adu']:.2f} ADU "
                    f"dark={record['dark_adu_per_s_mean']:.5f} ADU/s (mean) hot={hot:.5f}",
                    flush=True,
                )
    finally:
        warm_up(cam, out, ambient)


def sweep_level(cam: Camera, out: Output, pwm: int, hold_s: float) -> dict[str, Any]:
    """Hold a fixed PWM until the sensor settles, the time is up or the sensor warms up (collapse)."""
    cam.set_param(CONTROL_MANULPWM, pwm)
    start = time.time()
    history: deque[tuple[float, float]] = deque()
    lowest = cam.temperature()
    result: dict[str, Any] = {"pwm": pwm, "start_temp": lowest, "outcome": "time"}
    while True:
        now, temp = time.time(), cam.temperature()
        elapsed = now - start
        out.write(
            "cooling",
            {
                "time": now,
                "label": f"pwm {pwm}",
                "pwm_set": pwm,
                "pwm_read": cam.get_param(CONTROL_CURPWM),
                "temp": temp,
            },
        )
        lowest = min(lowest, temp)
        history.append((now, temp))
        while history and now - history[0][0] > SWEEP_SETTLE_S + 5:
            history.popleft()
        if elapsed > SWEEP_COLLAPSE_AFTER_S and temp - lowest >= SWEEP_COLLAPSE_C:
            result["outcome"] = "collapse"
            break
        temps = [t for _, t in history]
        if (
            elapsed >= SWEEP_MIN_S
            and now - history[0][0] >= SWEEP_SETTLE_S * 0.9
            and max(temps) - min(temps) < SWEEP_SETTLE_C
        ):
            result["outcome"] = "settled"
            break
        if elapsed >= hold_s:
            break
        print(f"  pwm {pwm}: T={temp:.1f} degC lowest={lowest:.1f} t={elapsed:.0f}s", flush=True)
        time.sleep(POLL_S)
    result.update(
        {"time": time.time(), "end_temp": cam.temperature(), "lowest_temp": lowest, "elapsed_s": time.time() - start}
    )
    return result


def sweep_warm_up(cam: Camera, out: Output, ambient: float, timeout_s: float = 1500.0, log: str = "cooling") -> None:
    """PWM 0 and wait until the sensor is within 3 degC of the ambient temperature."""
    cam.set_param(CONTROL_MANULPWM, 0)
    start = time.time()
    while time.time() - start < timeout_s:
        temp = cam.temperature()
        out.write(
            log,
            {
                "time": time.time(),
                "label": "warm",
                "pwm_set": 0,
                "pwm_read": cam.get_param(CONTROL_CURPWM),
                "temp": temp,
            },
        )
        if temp >= ambient - 3:
            return
        time.sleep(POLL_S)


def run_cooling(cam: Camera, out: Output, pwms: list[int], hold_s: float) -> None:
    """Fixed PWM levels in ascending order from ambient. A level that collapses is repeated once from ambient; a second
    collapse ends the sweep."""
    ambient = cam.temperature()
    print(f"Ambient {ambient:.1f} degC, levels {pwms}", flush=True)
    try:
        for pwm in pwms:
            for attempt in (1, 2):
                print(f"PWM {pwm} ({pwm / 255 * 100:.0f}%), attempt {attempt}", flush=True)
                result = sweep_level(cam, out, pwm, hold_s)
                result["attempt"] = attempt
                out.write("cooling", {"label": "result", **result})
                print(
                    f"  -> {result['outcome']}: lowest {result['lowest_temp']:.1f} degC, "
                    f"end {result['end_temp']:.1f} degC after {result['elapsed_s']:.0f} s",
                    flush=True,
                )
                if result["outcome"] != "collapse":
                    break
                sweep_warm_up(cam, out, ambient)
            else:
                print("Second collapse at the same level, stopping the sweep.", flush=True)
                return
    finally:
        sweep_warm_up(cam, out, ambient)


def run_sdkcool(
    cam: Camera, out: Output, mode: str, target: int, jump: bool, ambient: float, hold_s: float = 900.0
) -> None:
    """Cool with the SDK's own control ("temp": ControlQHYCCDTemp once per second, "cooler": CONTROL_COOLER once per
    change of the target). Stops on a collapse (sensor warms by 1 degC above its lowest value)."""
    run = f"{mode}_{'jump' if jump else 'ramp'}_{target}"
    print(f"SDK cooling {run}", flush=True)
    cam.set_param(CONTROL_MANULPWM, 0)
    time.sleep(2)
    start = time.time()
    lowest = cam.temperature()
    current = target if jump else round(lowest)
    last_step, hold_start, last_log = start, None, 0.0
    outcome = "time"

    def apply(value: int) -> None:
        if mode == "temp":
            cam.lib.ControlQHYCCDTemp(cam.handle, float(value))
        else:
            cam.set_param(CONTROL_COOLER, float(value))

    try:
        apply(current)
        while True:
            now = time.time()
            if mode == "temp":
                apply(current)
            if not jump and current > target and now - last_step >= RAMP_STEP_S:
                current -= 1
                last_step = now
                apply(current)
            if current <= target and hold_start is None:
                hold_start = now
            temp = cam.temperature()
            lowest = min(lowest, temp)
            if now - last_log >= POLL_S:
                last_log = now
                out.write(
                    "sdkcool",
                    {
                        "time": now,
                        "run": run,
                        "label": "cool",
                        "target": current,
                        "temp": temp,
                        "pwm_read": cam.get_param(CONTROL_CURPWM),
                        "cooler_param": cam.get_param(CONTROL_COOLER),
                    },
                )
                print(f"  {run}: T={temp:.1f} target={current} pwm={cam.get_param(CONTROL_CURPWM):.0f}", flush=True)
            if now - start > 60 and temp - lowest >= SWEEP_COLLAPSE_C and temp - current >= SWEEP_COLLAPSE_C:
                outcome = "collapse"
                break
            if hold_start is not None and now - hold_start >= hold_s:
                break
            time.sleep(1.0)
    finally:
        out.write(
            "sdkcool",
            {
                "time": time.time(),
                "run": run,
                "label": "result",
                "outcome": outcome,
                "lowest_temp": lowest,
                "end_temp": cam.temperature(),
                "elapsed_s": time.time() - start,
            },
        )
        print(f"  -> {outcome}: lowest {lowest:.1f} degC, end {cam.temperature():.1f} degC", flush=True)
        cam.set_param(CONTROL_MANULPWM, 0)
        time.sleep(5)
        out.write(
            "sdkcool",
            {
                "time": time.time(),
                "run": run,
                "label": "off",
                "pwm_read": cam.get_param(CONTROL_CURPWM),
                "temp": cam.temperature(),
            },
        )
        sweep_warm_up(cam, out, ambient, log="sdkcool")


def run_driver(
    cooling_control: str, wrap: bool, target: int, hold_s: float, ambient: float, out_root: Path, folder: Path | None
) -> None:
    """Test the cooling procedure of the pyobs-qhyccd module (QHYCCDCamera), not the SDK through ctypes.

    Opens the module like pyobs does, switches cooling on with ``set_cooling`` (the module ramps the setpoint), holds
    ``hold_s`` seconds, reads the setpoint and power back through the module, switches cooling off (ramp up, PWM 0)
    and checks the result. Everything is logged to ``driver.jsonl``; the checks are in the last record.
    """
    import asyncio

    from pyobs_qhyccd.qhyccddriver import Control, QHYCCDDriver  # type: ignore[import-untyped]

    from pyobs_qhyccd import QHYCCDCamera  # type: ignore[import-untyped]

    devices = QHYCCDDriver.list_devices()
    if not devices:
        raise SystemExit("No camera found.")
    cam_id = devices[0].decode() if isinstance(devices[0], bytes) else str(devices[0])
    model, _, serial = cam_id.partition("-")
    out = Output(folder or Path(out_root) / model / serial)
    run = f"driver_{cooling_control}_{'wrap_' if wrap else ''}{target}"
    published: dict[str, Any] = {}

    async def set_state(interface: Any, state: Any, *args: Any, **kwargs: Any) -> None:
        published[interface.__name__] = state

    async def main_async() -> None:
        camera = QHYCCDCamera(cooling_control=cooling_control, pwm_wrap_workaround=wrap)
        camera.comm.set_state = set_state  # type: ignore[method-assign]
        checks: dict[str, Any] = {"run": run}
        start = time.time()

        async def sample(label: str) -> dict[str, Any]:
            driver = camera._driver
            hw_enabled, hw_setpoint, hw_power = await camera._get_cooling_hardware()
            state = published.get("ICooling")
            record = {
                "time": time.time(),
                "run": run,
                "label": label,
                "temp": camera._current_temperature,
                "pwm_read": float(driver.get_param(Control.CONTROL_CURPWM)),
                "pwm_set": float(driver.get_param(Control.CONTROL_CURPWM)),
                "cooler_param": float(driver.get_param(Control.CONTROL_COOLER)),
                "commanded": camera._cooling_commanded,
                "ramping": camera.cooling_ramping,
                "hw_enabled": hw_enabled,
                "hw_setpoint": hw_setpoint,
                "hw_power": hw_power,
                "state_setpoint": getattr(state, "setpoint", None),
                "state_power": getattr(state, "power", None),
                "state_enabled": getattr(state, "enabled", None),
                "state_target": getattr(state, "target", None),
            }
            out.write("driver", record)
            return record

        await camera.open()
        try:
            await asyncio.sleep(8)  # the cooling task starts after 5 s
            first = await sample("open")
            checks["idle_after_open"] = {
                "hw": [first["hw_enabled"], first["hw_setpoint"], first["hw_power"]],
                "pwm_read": first["pwm_read"],
                "ok": first["hw_setpoint"] is None and first["pwm_read"] == 0.0,
            }
            lowest = camera._current_temperature
            await camera.set_cooling(True, target)
            hold_start: float | None = None
            outcome = "time"
            last = time.time()
            while True:
                await asyncio.sleep(1.0)
                if time.time() - last < POLL_S:
                    continue
                last = time.time()
                rec = await sample("cool")
                lowest = min(lowest, rec["temp"])
                print(
                    f"  {run}: T={rec['temp']:.1f} commanded={rec['commanded']} pwm={rec['pwm_read']:.0f} "
                    f"hw setpoint={rec['hw_setpoint']} ramping={rec['ramping']}",
                    flush=True,
                )
                if not rec["ramping"] and hold_start is None:
                    hold_start = time.time()
                commanded = rec["commanded"] if rec["commanded"] is not None else target
                if (
                    time.time() - start > 120
                    and rec["temp"] - lowest >= SWEEP_COLLAPSE_C
                    and (rec["temp"] - commanded >= SWEEP_COLLAPSE_C)
                ):
                    outcome = "collapse"
                    break
                if hold_start is not None and time.time() - hold_start >= hold_s:
                    break
            rec = await sample("hold_end")
            checks["cooling"] = {
                "outcome": outcome,
                "end_temp": rec["temp"],
                "reached_target": abs(rec["temp"] - target) <= 1.0,
                "readback_setpoint": rec["hw_setpoint"],
                "readback_ok": rec["hw_setpoint"] is not None and abs(rec["hw_setpoint"] - target) <= 0.5,
                "power": rec["hw_power"],
                "state_power": rec["state_power"],
                "state_enabled": rec["state_enabled"],
            }
            print(f"  cooling: {checks['cooling']}", flush=True)

            await camera.set_cooling(False, target)
            warm_start = time.time()
            last = 0.0
            while time.time() - warm_start < 3000:
                await asyncio.sleep(1.0)
                if time.time() - last < POLL_S:
                    continue
                last = time.time()
                rec = await sample("warm")
                print(f"  {run}: warming T={rec['temp']:.1f} pwm={rec['pwm_read']:.0f}", flush=True)
                if not rec["ramping"] and rec["temp"] >= ambient - 3:
                    break
            await asyncio.sleep(10)
            rec = await sample("off")
            checks["off"] = {
                "pwm_read": rec["pwm_read"],
                "state_enabled": rec["state_enabled"],
                "hw_enabled": rec["hw_enabled"],
                "temp": rec["temp"],
                "ok": rec["pwm_read"] == 0.0 and not rec["state_enabled"],
            }
            print(f"  off: {checks['off']}", flush=True)
        finally:
            checks["elapsed_s"] = time.time() - start
            out.write("driver", {"time": time.time(), "run": run, "label": "checks", **checks})
            await camera.close()

    asyncio.run(main_async())


def run_short(cam: Camera, out: Output, gain: int, offset: int, reference_s: float = SHORT_REFERENCE_S) -> None:
    """Mean level of the central window vs. exposure time for short exposures, with a reference exposure between."""
    min_s = cam.min_exposure_us * 1e-6
    # bias level from frames at the minimum exposure, the signal level is relative to that
    cam.grab(min_s, gain, offset)
    bias = float(np.mean([crop(cam.grab(min_s, gain, offset)).mean() for _ in range(SHORT_FRAMES)]))
    cam.grab(reference_s, gain, offset)
    ref0 = float(crop(cam.grab(reference_s, gain, offset)).mean())
    if ref0 - bias <= 20:
        raise SystemExit("Too little light on the sensor, check the lens cap and the light source.")
    rate = (ref0 - bias) / reference_s
    for exposure in SHORT_EXPOSURES_S:
        exposure = max(exposure, min_s)
        if bias + rate * exposure > 0.85 * FULL_SCALE:
            print(f"  t={exposure:.6f}s skipped, would saturate", flush=True)
            continue
        cam.grab(exposure, gain, offset)  # discard the first frame after a setting change
        levels = [float(crop(cam.grab(exposure, gain, offset)).mean()) for _ in range(SHORT_FRAMES)]
        cam.grab(reference_s, gain, offset)
        ref = float(crop(cam.grab(reference_s, gain, offset)).mean())
        record = {
            "gain": gain,
            "offset": offset,
            "exposure": exposure,
            "time": time.time(),
            "temp": cam.temperature(),
            "level": float(np.mean(levels)),
            "level_std": float(np.std(levels)),
            "level_min_exposure": bias,
            "ref_level": ref,
        }
        out.write("short", record)
        print(
            f"  t={exposure:9.6f}s level={record['level']:9.2f} +- {record['level_std']:.2f} ADU "
            f"reference={ref - bias:8.1f} ADU",
            flush=True,
        )


def _timed_frames(cam: Camera, width: int, height: int, bins: int, gain: int, offset: int) -> list:
    cam.set_param(CONTROL_GAIN, gain)
    cam.set_param(CONTROL_OFFSET, offset)
    cam.set_param(CONTROL_EXPOSURE, cam.min_exposure_us)
    cam.set_roi(0, 0, width, height, bins=bins)
    frames = []
    for i in range(READOUT_FRAMES + 1):  # the first frame after a setting change is discarded
        t0 = time.time()
        data = cam.expose()  # exposure and download cannot be told apart, the SDK blocks until the frame is read
        t1 = time.time()
        if i > 0:
            frames.append((t1 - t0, data))
    return frames


def run_readout(cam: Camera, out: Output, gain: int, offset: int) -> None:
    """Time per frame of the full effective area vs. binning and USB traffic, and the read noise for each."""
    x0, y0, eff_w, eff_h = cam.info["EffectiveArea"]
    for traffic in READOUT_USB_TRAFFICS:
        cam.set_param(CONTROL_USBTRAFFIC, traffic)
        for bins in cam.info["SupportedBins"]:
            width = eff_w // bins // 8 * 8
            height = eff_h // bins // 2 * 2
            try:
                frames = _timed_frames(cam, width, height, bins, gain, offset)
            except RuntimeError as e:
                print(f"  usb_traffic={traffic} bin={bins} {width}x{height}: {e}", flush=True)
                continue
            frame_s = float(np.median([f[0] for f in frames]))
            a, b = frames[0][1], frames[1][1]
            noise = pair_stats(crop(a), crop(b)) if min(a.shape) >= CUTOUT else None
            record = {
                "time": time.time(),
                "usb_traffic": traffic,
                "bins": bins,
                "type": "RAW16",
                "width": a.shape[1],
                "height": a.shape[0],
                "gain": gain,
                "offset": offset,
                "frame_s": frame_s,
                "noise_adu": None if noise is None else noise["noise_std_adu"],
                "bias_mean": None if noise is None else noise["mean"],
            }
            out.write("readout", record)
            print(
                f"  usb_traffic={traffic} bin={bins} {a.shape[1]}x{a.shape[0]}: {frame_s:.3f} s per frame, "
                f"noise={record['noise_adu']}",
                flush=True,
            )
    cam.set_param(CONTROL_USBTRAFFIC, cam.usb_traffic)


def pixel_stats(
    sample: np.ndarray, s: np.ndarray, s2: np.ndarray, lo: np.ndarray, hi: np.ndarray, first: np.ndarray, n: int
) -> dict[str, Any]:
    """Statistics of the temporal noise of every pixel, from sums over ``n`` frames.

    ``sample`` has the time series (frames x pixels) of a random subset of pixels, ``first`` is the first frame.
    """
    mean = s / n
    std = np.sqrt(np.maximum((s2 - n * mean**2) / (n - 1), 0.0))
    level, med_std = float(np.median(mean)), float(np.median(std))
    record: dict[str, Any] = {
        "frames": n,
        "level": level,
        "std_median": med_std,
        "std_mean": float(std.mean()),
        "std_rms": float(np.sqrt((std**2).mean())),
        "std_percentiles": {str(q): float(v) for q, v in zip((1, 50, 99, 99.9), np.percentile(std, (1, 50, 99, 99.9)))},
        "noisy_frac": {str(k): float((std > k * med_std).mean()) for k in (1.25, 1.5, 2, 3, 5)},
        "offset_high": {str(a): int((mean > level + a).sum()) for a in (10, 20, 40)},
        "offset_low": {str(a): int((mean < level - a).sum()) for a in (10, 20, 40)},
    }
    # tails of a single frame, with a robust sigma (a Gaussian would give a few pixels at 5 sigma)
    sigma = 1.4826 * float(np.median(np.abs(first - np.median(first))))
    record["single_frame_tails"] = {
        str(k): {
            "high": int((first > np.median(first) + k * sigma).sum()),
            "low": int((first < np.median(first) - k * sigma).sum()),
        }
        for k in (5, 8, 20)
    }
    # noisy pixels of the sample: do they sit on two levels?
    sample_std = sample.std(axis=0, ddof=1)
    noisy = sample[:, sample_std > PIXEL_NOISY_FACTOR * med_std].astype(np.float64)
    two_level = 0
    for series in noisy.T:
        split = (series.min() + series.max()) / 2
        up, down = series[series > split], series[series <= split]
        share = min(len(up), len(down)) / len(series)
        if share < 0.1 or len(up) < 2 or len(down) < 2:
            continue
        pooled = math.sqrt((up.var(ddof=1) * (len(up) - 1) + down.var(ddof=1) * (len(down) - 1)) / (len(series) - 2))
        if pooled > 0 and (up.mean() - down.mean()) / pooled > 3:
            two_level += 1
    record["sample_noisy"] = int(noisy.shape[1])
    record["sample_noisy_two_level"] = two_level
    record["range_over_45adu"] = int(((hi.astype(np.int64) - lo) > 45).sum())
    return record


def run_pixels(
    cam: Camera, out: Output, gain: int, offset: int, target_temp: int | None, frames: int = PIXEL_FRAMES
) -> None:
    ambient = round(cam.temperature())
    try:
        if target_temp is None:
            if cam.cooler_on():
                print("Switching the cooler off and waiting for a stable sensor temperature.", flush=True)
                cam.set_cooler(False)
            wait_stable(cam, out, None, "warm")
        else:
            print(f"Cooling to {target_temp} degC ...", flush=True)
            ramp_to(cam, out, target_temp)
            wait_stable(cam, out, target_temp, f"stabilize {target_temp}")

        x0, y0, width, height = cam.info["EffectiveArea"]
        cam.set_param(CONTROL_GAIN, gain)
        cam.set_param(CONTROL_OFFSET, offset)
        cam.set_param(CONTROL_EXPOSURE, cam.min_exposure_us)
        cam.set_roi(x0, y0, width, height)
        rng = np.random.default_rng(1)
        index = rng.choice(width * height, PIXEL_SAMPLE, replace=False)
        s, s2 = np.zeros((height, width)), np.zeros((height, width))
        lo, hi = np.full((height, width), 65535, np.uint16), np.zeros((height, width), np.uint16)
        sample, first = [], None
        temp0 = cam.temperature()
        for i in range(frames + 1):  # the first frame after a setting change is discarded
            data = cam.expose()
            if i == 0:
                continue
            x = data.astype(np.float64)
            s += x
            s2 += x * x
            lo, hi = np.minimum(lo, data), np.maximum(hi, data)
            sample.append(data.reshape(-1)[index])
            if first is None:
                first = x
        assert first is not None
        record: dict[str, Any] = {
            "time": time.time(),
            "target": target_temp,
            "temp": cam.temperature(),
            "temp_start": temp0,
            "power": cam.power(),
            "gain": gain,
            "offset": offset,
            **pixel_stats(np.array(sample), s, s2, lo, hi, first, frames),
        }
        out.write("pixels", record)
        print(
            f"T={record['temp']:.1f} degC: median pixel noise {record['std_median']:.2f} ADU, "
            f"rms {record['std_rms']:.2f}, "
            f"noisy (>{PIXEL_NOISY_FACTOR:.0f}x): {record['noisy_frac']['5']:.2e}, two-level in sample: "
            f"{record['sample_noisy_two_level']} of {record['sample_noisy']}",
            flush=True,
        )
    finally:
        if target_temp is not None:
            warm_up(cam, out, ambient)


def fit_gain(records: list[dict[str, Any]], gain: int, weighted: bool = False) -> dict[str, float] | None:
    """Fit variance = read_noise^2 + g * signal. The slope g is ADU per electron.

    The variance of a variance estimate grows with the variance itself, so ``weighted`` uses weights of 1/variance.
    Without it a wide signal range makes the intercept (read noise) meaningless.
    """
    rows = [r for r in records if r["gain"] == gain]
    if len(rows) < 3:
        return None
    s = np.array([r["signal_adu"] for r in rows])
    v = np.array([r["variance_adu2"] for r in rows])
    w = 1.0 / v if weighted else np.ones_like(v)
    slope, intercept = np.polyfit(s, v, 1, w=w)
    residual = (v - (slope * s + intercept)) * w
    s_mean = np.sum(w**2 * s) / np.sum(w**2)
    err = float(np.sqrt(np.sum(residual**2) / max(len(s) - 2, 1) / np.sum(w**2 * (s - s_mean) ** 2)))
    return {
        "adu_per_e": float(slope),
        "e_per_adu": float(1.0 / slope) if slope > 0 else float("nan"),
        "slope_err": err,
        "read_noise_adu": float(math.sqrt(max(intercept, 0.0))),
        "signal_max_adu": float(s.max()),
    }


def export_csv(folder: Path) -> list[Path]:
    """Writes every JSON lines file in the folder as a CSV file of the same name.

    Nested values are flattened into columns named ``<key>_<subkey>``, lists are joined with spaces, and a ``utc``
    column is added in front if the records have a ``time``.
    """

    def flat(record: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, dict):
                out.update(flat(value, f"{prefix}{key}_"))
            elif isinstance(value, list):
                out[f"{prefix}{key}"] = " ".join(str(v) for v in value)
            else:
                out[f"{prefix}{key}"] = value
        return out

    written = []
    for path in sorted(folder.glob("*.jsonl")):
        rows = [flat(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]
        keys: list[str] = []
        for row in rows:
            if "time" in row:
                row["utc"] = datetime.fromtimestamp(row["time"], UTC).strftime("%Y-%m-%dT%H:%M:%S")
            keys += [k for k in row if k not in keys]
        if "utc" in keys:
            keys.remove("utc")
            keys.insert(0, "utc")
        csv_path = path.with_suffix(".csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(rows)
        written.append(csv_path)
    return written


def make_report(out: Output) -> None:
    """Draws the plots into ``images/`` and writes the CSV files, from the measured data."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    images = out.folder / "images"
    written: list[Path] = []

    def save(fig: Any, name: str) -> None:
        fig.savefig(images / name, dpi=110)
        plt.close(fig)
        written.append(images / name)

    bias, gain, temp = out.read("bias"), out.read("gain"), out.read("temperature")
    temp = [r for r in temp if "bias_noise_adu" in r]
    short = out.read("short")

    if bias:
        offsets = sorted({r["offset"] for r in bias})
        fig, axs = plt.subplots(1, 3, figsize=(15, 4))
        for o in offsets:
            rows = [r for r in bias if r["offset"] == o]
            axs[0].plot([r["gain"] for r in rows], [r["mean"] for r in rows], "o-", label=f"offset {o}")
            axs[1].plot([r["gain"] for r in rows], [r["noise_std_adu"] for r in rows], "o-", label=f"offset {o}")
            axs[2].plot([r["gain"] for r in rows], [r["clipped_frac"] for r in rows], "o-", label=f"offset {o}")
        for ax, label in zip(axs, ["bias level [ADU]", "read noise [ADU]", "clipped pixel fraction"], strict=True):
            ax.set_xlabel("gain")
            ax.set_ylabel(label)
            ax.grid(alpha=0.3)
        axs[0].set_yscale("log")
        axs[1].set_yscale("log")
        axs[0].legend()
        fig.tight_layout()
        save(fig, "bias.png")

    if gain:
        fig, ax = plt.subplots(figsize=(6, 4.5))
        for g in sorted({r["gain"] for r in gain}):
            rows = [r for r in gain if r["gain"] == g]
            s = [r["signal_adu"] for r in rows]
            ax.plot(s, [r["variance_adu2"] for r in rows], "o", label=f"gain {g}")
            fit = fit_gain(gain, g)
            if fit:
                xs = np.linspace(0, max(s), 20)
                ax.plot(xs, fit["adu_per_e"] * xs + fit["read_noise_adu"] ** 2, "-", alpha=0.5)
        ax.set_xlabel("dark signal [ADU]")
        ax.set_ylabel("noise variance of one frame [ADU^2]")
        ax.legend()
        ax.grid(alpha=0.3)
        fig.tight_layout()
        save(fig, "gain.png")

    flat = out.read("flat")
    if flat:
        fig, axs = plt.subplots(1, 2, figsize=(12, 4.5))
        for g in sorted({r["gain"] for r in flat}):
            rows = [r for r in flat if r["gain"] == g]
            good = [r for r in rows if r["sat_frac"] == 0 and 0 < r["signal_adu"] <= FIT_MAX_FRACTION * FULL_SCALE]
            (line,) = axs[0].loglog(
                [max(r["signal_adu"], 0.1) for r in rows], [r["variance_adu2"] for r in rows], "o", label=f"gain {g}"
            )
            axs[1].semilogx(
                [max(r["signal_adu"], 0.1) for r in rows], [r["nonlin_pct"] for r in rows], "o-", color=line.get_color()
            )
            fit = fit_gain(good, g, weighted=True)
            if fit is None:
                continue
            xs = np.geomspace(min(r["signal_adu"] for r in good), max(r["signal_adu"] for r in good), 20)
            axs[0].loglog(
                xs, fit["adu_per_e"] * xs + fit["read_noise_adu"] ** 2, "-", color=line.get_color(), alpha=0.5
            )
        axs[0].set_xlabel("signal [ADU]")
        axs[0].set_ylabel("noise variance of one frame [ADU^2]")
        axs[1].set_xlabel("signal [ADU]")
        axs[1].set_ylabel("deviation from linear in exposure time [%]")
        for ax in axs:
            ax.grid(alpha=0.3)
        axs[0].legend()
        fig.tight_layout()
        save(fig, "flat.png")

    if temp:
        fig, axs = plt.subplots(1, 3, figsize=(15, 4))
        ts = sorted({r["target"] for r in temp})
        axs[0].plot(ts, [np.mean([r["bias_noise_adu"] for r in temp if r["target"] == t]) for t in ts], "o-")
        axs[0].set_ylabel("read noise [ADU]")
        for e in sorted({r["exposure"] for r in temp}):
            rows = [r for r in temp if r["exposure"] == e]
            axs[1].plot(
                [r["temp"] for r in rows],
                [max(r["dark_adu_per_s_mean"], 1e-6) for r in rows],
                "o-",
                label=f"{e:.0f} s",
            )
            axs[2].plot([r["temp"] for r in rows], [r["hot_frac"] for r in rows], "o-", label=f"{e:.0f} s")
        axs[1].set_yscale("log")
        axs[1].set_ylabel("dark signal, mean [ADU/s/pixel]")
        axs[2].set_yscale("log")
        axs[2].set_ylabel("hot pixel fraction")
        for ax in axs:
            ax.set_xlabel("sensor temperature [degC]" if ax is not axs[0] else "target [degC]")
            ax.grid(alpha=0.3)
        axs[1].legend()
        fig.tight_layout()
        save(fig, "temperature.png")

    cooling_sets = [(n, out.read(n)) for n in sorted(f.stem for f in out.folder.glob("cooling*.jsonl"))]
    cooling_sets = [(n, [r for r in rows if "temp" in r and "pwm_set" in r]) for n, rows in cooling_sets]
    for source in ("sdkcool", "driver"):
        sdk_rows = out.read(source)
        for run in dict.fromkeys(r["run"] for r in sdk_rows):
            rows = [
                dict(r, pwm_set=r["pwm_read"]) for r in sdk_rows if r["run"] == run and "temp" in r and "pwm_read" in r
            ]
            cooling_sets.append((f"{source} {run}", rows))
    cooling_sets = [(n, rows) for n, rows in cooling_sets if rows]
    if cooling_sets:
        fig, axs = plt.subplots(len(cooling_sets), 1, figsize=(10, 3.5 * len(cooling_sets)), squeeze=False)
        for ax, (name, rows) in zip(axs[:, 0], cooling_sets):
            t0 = rows[0]["time"]
            minutes = [(r["time"] - t0) / 60 for r in rows]
            ax.plot(minutes, [r["temp"] for r in rows], "-", color="C0")
            ax.set_ylabel("sensor temperature [degC]", color="C0")
            ax.set_xlabel("time [min]")
            ax.set_title(name)
            ax.grid(alpha=0.3)
            ax2 = ax.twinx()
            ax2.step(minutes, [r["pwm_set"] for r in rows], where="post", color="C1")
            ax2.set_ylabel("PWM set", color="C1")
        fig.tight_layout()
        save(fig, "cooling.png")

    if short:
        rows = [r for r in short if r["exposure"] >= SHORT_FIT_MIN_S]
        t = np.array([r["exposure"] for r in short])
        level = np.array([r["level"] for r in short])
        rate, level0 = np.polyfit([r["exposure"] for r in rows], [r["level"] for r in rows], 1)
        # bias of the same gain and offset from the bias step, if there is one
        match = [b["mean"] for b in bias if b["gain"] == short[0]["gain"] and b["offset"] == short[0]["offset"]]
        if match:
            print(f"Short exposures: exposure offset {(level0 - match[0]) / rate * 1e6:+.0f} us")
        fig, ax = plt.subplots(figsize=(6, 4.5))
        ax.loglog(t * 1000, level - (match[0] if match else level0), "o-", label="measured")
        ax.loglog(t * 1000, rate * t + level0 - (match[0] if match else level0), "--", label="line from >= 1 ms")
        ax.set_xlabel("exposure time [ms]")
        ax.set_ylabel("level above bias [ADU]")
        ax.grid(alpha=0.3, which="both")
        ax.legend()
        fig.tight_layout()
        save(fig, "short.png")

    written += export_csv(out.folder)
    for path in written:
        print(f"Wrote {path}")


def find_report_folder(root: Path) -> Path:
    """The single unit folder (``<model>/<serial number>``) below ``root`` that has a ``meta.json``."""
    folders = sorted(p.parent for p in root.glob("*/*/meta.json"))
    if len(folders) != 1:
        found = ", ".join(str(f) for f in folders) or "none"
        raise SystemExit(f"Expected exactly one camera folder in {root}, found: {found}. Use --folder.")
    return folders[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "step",
        choices=[
            "bias",
            "gain",
            "temperature",
            "cooling",
            "sdkcool",
            "driver",
            "flat",
            "short",
            "readout",
            "pixels",
            "report",
        ],
    )
    parser.add_argument("--sdk", default="/usr/local/lib/libqhyccd.so", help="path of libqhyccd.so")
    parser.add_argument("--read-mode", type=int, default=0, help="read mode of the camera, see meta.json")
    parser.add_argument("--usb-traffic", type=int, default=DEFAULT_USB_TRAFFIC)
    parser.add_argument("--out", default="characterization", help="root folder, results go to <out>/<model>/<serial>")
    parser.add_argument("--folder", type=Path, help="unit folder for the report step, if there is more than one")
    parser.add_argument("--gains", type=int, nargs="+", help="gains for the bias or gain step")
    parser.add_argument("--offsets", type=int, nargs="+", help="offsets for the bias step")
    parser.add_argument(
        "--exposures", type=float, nargs="+", help="exposure times in s for the gain or temperature step"
    )
    parser.add_argument("--temperatures", type=int, nargs="+", default=TEMPERATURES)
    parser.add_argument("--pwms", type=int, nargs="+", default=SWEEP_PWMS, help="PWM levels (0 to 255), cooling step")
    parser.add_argument(
        "--sdk-mode",
        choices=["temp", "cooler"],
        default="temp",
        help="sdkcool step; driver step: temp = ControlQHYCCDTemp",
    )
    parser.add_argument("--cool-target", type=int, default=-10, help="target in degC, sdkcool step")
    parser.add_argument("--wrap-workaround", action="store_true", help="driver step: turn the PWM > 250 workaround on")
    parser.add_argument("--jump", action="store_true", help="sdkcool step: go to the target in one step")
    parser.add_argument("--ambient", type=float, default=20.0, help="ambient temperature in degC, sdkcool step")
    parser.add_argument("--frames", type=int, default=PIXEL_FRAMES, help="frames for the pixels step")
    parser.add_argument("--hold", type=float, default=SWEEP_HOLD_S, help="longest hold of one level in s, cooling step")
    parser.add_argument("--gain", type=int, default=DEFAULT_GAIN, help="gain for the temperature step")
    parser.add_argument("--offset", type=int, default=DEFAULT_OFFSET)
    parser.add_argument(
        "--target-temp",
        type=int,
        default=None,
        help="cooler target for the gain and pixels step in degC, default: cooler off",
    )
    parser.add_argument(
        "--reference", type=float, default=SHORT_REFERENCE_S, help="reference exposure in s, short step"
    )
    parser.add_argument("--no-cooling", action="store_true", help="gain and pixels step with the cooler off (default)")
    args = parser.parse_args()

    if args.step == "report":
        # no camera needed, use the saved data
        make_report(Output(args.folder or find_report_folder(Path(args.out))))
        return

    if args.step == "driver":
        # the pyobs-qhyccd module opens the camera itself
        run_driver(
            "temperature" if args.sdk_mode == "temp" else "cooler",
            args.wrap_workaround,
            args.cool_target,
            args.hold,
            args.ambient,
            Path(args.out),
            args.folder,
        )
        return

    cam = Camera(args.sdk, args.read_mode, args.usb_traffic)
    name = str(cam.info["Name"]).replace(" ", "_")
    unit = (cam.serial or "unknown_serial") + (f"_mode{args.read_mode}" if args.read_mode else "")
    out = Output(Path(args.out) / name / unit)
    meta = {
        "info": {k: v for k, v in cam.info.items()},
        "serial": cam.serial,
        "sdk": cam.sdk,
        "controls": cam.controls,
        "usb_traffic": cam.usb_traffic,
    }
    (out.folder / "meta.json").write_text(json.dumps(meta, indent=1, default=str))

    try:
        if args.step == "bias":
            run_bias(cam, out, args.gains or GAINS, args.offsets or OFFSETS)
        elif args.step == "gain":
            target = None if args.no_cooling else args.target_temp
            run_gain(
                cam, out, args.gains or GAIN_TEST_GAINS, args.exposures or GAIN_TEST_EXPOSURES, args.offset, target
            )
        elif args.step == "flat":
            run_flat(cam, out, args.gains or FLAT_GAINS, args.offset)
        elif args.step == "short":
            run_short(cam, out, args.gain, args.offset, args.reference)
        elif args.step == "readout":
            run_readout(cam, out, args.gain, args.offset)
        elif args.step == "pixels":
            target = None if args.no_cooling else args.target_temp
            run_pixels(cam, out, args.gain, args.offset, target, args.frames)
        elif args.step == "temperature":
            run_temperature(cam, out, args.temperatures, args.gain, args.offset, args.exposures)
        elif args.step == "sdkcool":
            run_sdkcool(cam, out, args.sdk_mode, args.cool_target, args.jump, args.ambient)
        elif args.step == "cooling":
            run_cooling(cam, out, args.pwms, args.hold)
    finally:
        cam.set_param(CONTROL_MANULPWM, 0)  # never leave the cooler driven when the script ends
        cam.close()


if __name__ == "__main__":
    sys.exit(main())
