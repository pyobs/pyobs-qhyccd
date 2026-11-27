"""Full-frame exposures while other threads call the SDK, to provoke the empty-frame hang.

Usage: stress.py READ_MODE EXPOSURE_S POLL_S DURATION_S [locked]

The cooler runs on the script's PI controller (target 0 degC, 1 Hz SDK calls, as in characterize.py), and an extra
poller reads the temperature and PWM every POLL_S seconds. Without "locked", nothing serializes these calls against
GetQHYCCDSingleFrame (like characterize.py); with "locked", all SDK calls of the camera object share one lock (like
the pyobs driver). Stops at the first empty frame (exit 3). Prints one line per frame.
"""

import sys
import threading
import time

sys.path.insert(0, "tools")
import characterize as c  # noqa: E402

read_mode, exposure, poll_s, duration = int(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
locked = len(sys.argv) > 5 and sys.argv[5] == "locked"

if locked:
    lock = threading.RLock()
    for name in ("get_param", "set_param", "set_roi", "expose"):
        orig = getattr(c.Camera, name)

        def wrapped(self, *a, _orig=orig, **k):
            with lock:
                return _orig(self, *a, **k)

        setattr(c.Camera, name, wrapped)

cam = c.Camera("/usr/local/lib/libqhyccd.so", read_mode, c.DEFAULT_USB_TRAFFIC)
x0, y0, w, h = cam.info["EffectiveArea"]
w, h = w // 8 * 8, h // 2 * 2
stop = threading.Event()
in_frame = threading.Event()
calls = {"in_frame": 0, "total": 0}


def poller() -> None:
    while not stop.wait(poll_s):
        cam.temperature()
        cam.power()
        calls["total"] += 2
        if in_frame.is_set():
            calls["in_frame"] += 2


print(f"mode={read_mode} exp={exposure}s poll={poll_s}s locked={locked} frame={w}x{h}", flush=True)
code = 0
cam.set_cooler(True, 0)
threading.Thread(target=poller, daemon=True).start()
end = time.time() + duration
n = 0
try:
    while time.time() < end:
        n += 1
        cam.set_param(c.CONTROL_GAIN, 10)
        cam.set_param(c.CONTROL_OFFSET, 140)
        cam.set_param(c.CONTROL_EXPOSURE, int(exposure * 1e6))
        cam.set_roi(x0, y0, w, h)
        before = calls["in_frame"]
        t = time.monotonic()
        in_frame.set()
        try:
            frame = cam.expose()
        except RuntimeError as e:
            print(f"{n} {time.strftime('%T')} took {time.monotonic() - t:.1f}s EMPTY/ERROR {e}", flush=True)
            code = 3
            break
        finally:
            in_frame.clear()
        dt = time.monotonic() - t
        print(
            f"{n} {time.strftime('%T')} took {dt:.1f}s extra={dt - exposure:.1f}s mean={frame.mean():.1f} "
            f"T={cam.temperature():.1f} pwm={cam.power()}% calls_in_frame={calls['in_frame'] - before}",
            flush=True,
        )
finally:
    stop.set()
    if code == 0:
        cam.set_cooler(False)
        cam.close()
print(f"END frames={n} calls={calls['total']}", flush=True)
sys.exit(code)
