"""One cycle: open in READ_MODE, one 1 ms full-frame bias, close (CloseQHYCCD per QHYCCD_CALL_CLOSE).

Exit 0 ok, 3 empty frame. Usage: cycle_mode.py READ_MODE
"""

import sys
import time

sys.path.insert(0, "tools")
import characterize as c  # noqa: E402

t0 = time.time()
cam = c.Camera("/usr/local/lib/libqhyccd.so", int(sys.argv[1]), c.DEFAULT_USB_TRAFFIC)
x0, y0, w, h = cam.info["EffectiveArea"]
code = 0
try:
    cam.set_param(c.CONTROL_GAIN, 10)
    cam.set_param(c.CONTROL_OFFSET, 140)
    cam.set_param(c.CONTROL_EXPOSURE, cam.min_exposure_us)
    cam.set_roi(x0, y0, w // 8 * 8, h // 2 * 2)
    t = time.time()
    a = cam.expose()
    print(f"OK {a.shape[1]}x{a.shape[0]} mean={a.mean():.1f} frame={time.time() - t:.1f}s", flush=True)
except RuntimeError as e:
    print(f"EMPTY {e}", flush=True)
    code = 3
finally:
    cam.close()
print(f"CYCLE {time.time() - t0:.1f}s", flush=True)
sys.exit(code)
