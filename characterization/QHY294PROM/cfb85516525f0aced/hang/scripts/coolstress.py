"""Long-lived process like the pyobs module at the telescope, with the cooler working, to provoke the empty frames.

Usage: coolstress.py DURATION_S

Read mode 0, gain 10, offset 140, full frame, exposures log-uniform between 1 ms and 30 s. The camera regulates the
temperature itself (setpoint written to CONTROL_COOLER, like the module), and the cooler phase changes every few
minutes: setpoint -15 degC (full drive), 5 degC (partial), PWM 0 (off). A poller reads temperature and PWM once per
second; all SDK calls share one lock (like the pyobs driver). CloseQHYCCD is not called (default).

On an empty frame: log, then try to recover like the module (close, open again, same mode, one frame), then via the
other read mode, and go on if that worked. Stops if nothing helped.
"""

import json
import math
import random
import subprocess
import sys
import threading
import time

sys.path.insert(0, "tools")
import characterize as c  # noqa: E402

S = "."  # output folder (run from the repository root)
LIB = "/usr/local/lib/libqhyccd.so"
PHASES = [("cool", -15.0), ("cool", 5.0), ("off", None)]

duration = float(sys.argv[1])
# "unlocked POLL_S": no lock, and the poller writes the manual PWM of the phase every POLL_S, like the PI thread of
# characterize.py (phases: PWM 250, 100, 0)
UNLOCKED = len(sys.argv) > 2 and sys.argv[2] == "unlocked"
POLL_S = float(sys.argv[3]) if UNLOCKED and len(sys.argv) > 3 else 1.0
if UNLOCKED:
    PHASES = [("pwm", 250.0), ("pwm", 100.0), ("pwm", 0.0)]

lock = threading.RLock()
if not UNLOCKED:
    for name in ("get_param", "set_param", "set_roi", "expose"):
        orig = getattr(c.Camera, name)

        def wrapped(self, *a, _orig=orig, **k):
            with lock:
                return _orig(self, *a, **k)

        setattr(c.Camera, name, wrapped)

seed = int(time.time())
rng = random.Random(seed)
out = open(f"{S}/coolstress.jsonl", "a")


def log(**rec) -> None:
    rec["time"] = time.strftime("%F %T")
    out.write(json.dumps(rec) + "\n")
    out.flush()
    print(json.dumps(rec), flush=True)


state = {"phase": None, "temp": None, "pwm": None}
stop = threading.Event()


def set_phase(cam: c.Camera, phase: tuple[str, float | None]) -> None:
    kind, target = phase
    if kind == "cool":
        cam.set_param(c.CONTROL_COOLER, target)
    elif kind == "pwm":
        state["pwm_target"] = target  # written by the poller
    else:
        cam.set_param(c.CONTROL_MANULPWM, 0)
    state["phase"] = f"{kind} {target}"
    log(event="phase", phase=state["phase"], temp=state["temp"], pwm=state["pwm"])


def poller(cam_ref: list) -> None:
    while not stop.wait(POLL_S):
        cam = cam_ref[0]
        if cam is None:
            continue
        try:
            state["temp"], state["pwm"] = cam.temperature(), cam.power()
            if state.get("pwm_target") is not None:
                cam.set_param(c.CONTROL_MANULPWM, state["pwm_target"])
                state["writes"] = state.get("writes", 0) + 1
        except Exception as e:  # camera being reopened
            state["temp"] = f"error {e}"


def frame(cam: c.Camera, exposure: float) -> tuple[bool, float, float]:
    x0, y0, w, h = cam.info["EffectiveArea"]
    cam.set_param(c.CONTROL_GAIN, 10)
    cam.set_param(c.CONTROL_OFFSET, 140)
    cam.set_param(c.CONTROL_EXPOSURE, max(int(exposure * 1e6), cam.min_exposure_us))
    cam.set_roi(x0, y0, w // 8 * 8, h // 2 * 2)
    t = time.monotonic()
    try:
        a = cam.expose()
        return True, time.monotonic() - t, float(a.mean())
    except RuntimeError:
        return False, time.monotonic() - t, 0.0


def reopen(cam_ref: list, mode: int) -> c.Camera:
    old = cam_ref[0]
    cam_ref[0] = None
    with lock:
        old.close()
    cam = c.Camera(LIB, mode, c.DEFAULT_USB_TRAFFIC)
    cam_ref[0] = cam
    return cam


log(event="start", seed=seed, duration=duration, unlocked=UNLOCKED, poll_s=POLL_S)
cam_ref = [c.Camera(LIB, 0, c.DEFAULT_USB_TRAFFIC)]
threading.Thread(target=poller, args=(cam_ref,), daemon=True).start()
end = time.time() + duration
phase_i, next_phase = 0, 0.0
n = hangs = 0
try:
    while time.time() < end:
        cam = cam_ref[0]
        if time.time() >= next_phase:
            set_phase(cam, PHASES[phase_i % len(PHASES)])
            phase_i += 1
            next_phase = time.time() + rng.uniform(120, 480)
        n += 1
        exposure = math.exp(rng.uniform(math.log(0.001), math.log(30.0)))
        ok, dt, mean = frame(cam, exposure)
        log(
            event="frame",
            n=n,
            exp=round(exposure, 4),
            ok=ok,
            took=round(dt, 1),
            mean=round(mean, 1),
            phase=state["phase"],
            temp=state["temp"],
            pwm=state["pwm"],
            writes=state.get("writes", 0),
        )
        if ok:
            continue
        hangs += 1
        kern = subprocess.run(["journalctl", "-k", "--since", "-5min"], capture_output=True, text=True).stdout
        usb = subprocess.run(["lsusb"], capture_output=True, text=True).stdout
        log(
            event="hang",
            n=n,
            kernel_usb=[line for line in kern.splitlines() if "usb" in line.lower()][-10:],
            lsusb=[line for line in usb.splitlines() if "1618" in line],
        )
        recovered = None
        for how, mode in (("reopen same mode", 0), ("other mode", 1), ("back to mode 0", 0)):
            cam = reopen(cam_ref, mode)
            ok, dt, mean = frame(cam, 0.001)
            log(event="recover", how=how, mode=mode, ok=ok, took=round(dt, 1), mean=round(mean, 1))
            if ok and mode == 0:
                recovered = how
                break
        if recovered is None:
            log(event="stop", reason="recovery failed")
            sys.exit(3)
        next_phase = 0.0  # set the cooler again on the new handle
finally:
    stop.set()
    cam = cam_ref[0]
    if cam is not None:
        with lock:
            cam.set_param(c.CONTROL_MANULPWM, 0)
            cam.close()
    log(event="end", frames=n, hangs=hangs)
