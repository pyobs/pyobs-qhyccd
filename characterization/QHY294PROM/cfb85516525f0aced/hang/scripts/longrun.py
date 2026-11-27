"""Long-lived process like the pyobs module at the telescope, to provoke the mid-session hang.

Usage: longrun.py DURATION_S

One process, read mode 0, CloseQHYCCD never called while running. Full frame (ImageWidth x ImageHeight at 0,0, like
"4212x2850" at the telescope), binning 2x2 (75 %), 4x4 (23 %), 1x1 (2 %). Exposure times from the telescope mix but
weighted to short ones to get many frames. Cooler regulated by the camera (setpoint -5 degC on CONTROL_COOLER), a
poller reads temperature and PWM every second; all SDK calls share one lock (like the module).

A frame is bad if it is all zeros, its readout took > 30 s longer than the exposure, or its mean < 100 ADU. On a bad
frame: log stats, save the frame, then recover step by step (reopen same mode, then other mode, then mode 0) and go on.
Stops if nothing helped.
"""

import json
import random
import subprocess
import sys
import threading
import time

import numpy as np

sys.path.insert(0, "tools")
import characterize as c  # noqa: E402

S = "."  # output folder (run from the repository root)
LIB = "/usr/local/lib/libqhyccd.so"
EXPOSURES = [(0.0, 15), (1.0, 25), (5.0, 15), (10.0, 20), (15.0, 10), (30.0, 12), (45.0, 3)]
BINNINGS = [(2, 75), (4, 23), (1, 2)]
SETPOINT = -5.0

duration = float(sys.argv[1])
lock = threading.RLock()
for name in ("get_param", "set_param", "set_roi", "expose"):
    orig = getattr(c.Camera, name)

    def wrapped(self, *a, _orig=orig, **k):
        with lock:
            return _orig(self, *a, **k)

    setattr(c.Camera, name, wrapped)

seed = int(time.time())
rng = random.Random(seed)
out = open(f"{S}/longrun.jsonl", "a")


def log(**rec) -> None:
    rec["time"] = time.strftime("%F %T")
    out.write(json.dumps(rec) + "\n")
    out.flush()


def pick(choices):
    return rng.choices([c_ for c_, _ in choices], [w for _, w in choices])[0]


state = {"temp": None, "pwm": None}
stop = threading.Event()


def poller(cam_ref: list) -> None:
    while not stop.wait(1.0):
        cam = cam_ref[0]
        if cam is None:
            continue
        try:
            state["temp"], state["pwm"] = cam.temperature(), cam.power()
        except Exception as e:
            state["temp"] = f"error {e}"


def frame(cam: c.Camera, exposure: float, bins: int) -> dict:
    w, h = cam.info["ReadMode"]["width"], cam.info["ReadMode"]["height"]
    cam.set_param(c.CONTROL_GAIN, 10)
    cam.set_param(c.CONTROL_OFFSET, 140)
    cam.set_param(c.CONTROL_EXPOSURE, max(int(exposure * 1e6), cam.min_exposure_us))
    cam.set_roi(0, 0, w // bins, h // bins, bins)
    t = time.monotonic()
    try:
        a = cam.expose()
    except RuntimeError as e:
        return dict(ok=False, why=str(e)[:60], took=round(time.monotonic() - t, 1), mean=0.0)
    took = time.monotonic() - t
    mean = float(a.mean())
    rec = dict(ok=True, took=round(took, 1), mean=round(mean, 1), shape=list(a.shape))
    if took - exposure > 30 or mean < 100:
        rows = np.flatnonzero(a.any(axis=1))
        rec.update(
            ok=False,
            why="late" if took - exposure > 30 else "low mean",
            zeros=int((a == 0).sum()),
            size=int(a.size),
            min=int(a.min()),
            max=int(a.max()),
            nonzero_rows=len(rows),
            first_rows=rows[:10].tolist(),
        )
        np.save(f"{S}/longrun_bad_{time.strftime('%m%d_%H%M%S')}.npy", a)
    return rec


def reopen(cam_ref: list, mode: int) -> c.Camera:
    old = cam_ref[0]
    cam_ref[0] = None
    with lock:
        old.close()
    cam = c.Camera(LIB, mode, c.DEFAULT_USB_TRAFFIC)
    cam.set_param(c.CONTROL_COOLER, SETPOINT)
    cam_ref[0] = cam
    return cam


log(event="start", seed=seed, duration=duration)
cam_ref = [c.Camera(LIB, 0, c.DEFAULT_USB_TRAFFIC)]
cam_ref[0].set_param(c.CONTROL_COOLER, SETPOINT)
log(event="info", read_mode=cam_ref[0].info["ReadMode"])
threading.Thread(target=poller, args=(cam_ref,), daemon=True).start()
end = time.time() + duration
n = bad = 0
try:
    while time.time() < end:
        n += 1
        exposure, bins = pick(EXPOSURES), pick(BINNINGS)
        rec = frame(cam_ref[0], exposure, bins)
        log(event="frame", n=n, exp=exposure, bin=bins, temp=state["temp"], pwm=state["pwm"], **rec)
        if rec["ok"]:
            continue
        bad += 1
        kern = subprocess.run(["journalctl", "-k", "--since", "-5min"], capture_output=True, text=True).stdout
        usb = subprocess.run(["lsusb"], capture_output=True, text=True).stdout
        log(
            event="hang",
            n=n,
            kernel_usb=[line for line in kern.splitlines() if "usb" in line.lower()][-10:],
            lsusb=[line for line in usb.splitlines() if "1618" in line],
        )
        recovered = None
        for how, mode in (
            ("retry same handle", None),
            ("reopen same mode", 0),
            ("other mode", 1),
            ("back to mode 0", 0),
        ):
            cam = cam_ref[0] if mode is None else reopen(cam_ref, mode)
            r = frame(cam, 0.0, 2)
            log(event="recover", how=how, mode=mode, **r)
            if r["ok"] and mode in (None, 0):
                recovered = how
                break
        if recovered is None:
            log(event="stop", reason="recovery failed")
            sys.exit(3)
finally:
    stop.set()
    cam = cam_ref[0]
    if cam is not None:
        with lock:
            cam.set_param(c.CONTROL_MANULPWM, 0)
            cam.close()
    log(event="end", frames=n, bad=bad)
