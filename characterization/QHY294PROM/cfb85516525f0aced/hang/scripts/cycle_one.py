"""One open/expose/close cycle. Exit 0 ok, 3 empty frame, other: error. Close variant from QHYCCD_CALL_CLOSE."""

import sys
import time

sys.path.insert(0, "tools")
import characterize as c  # noqa: E402

t0 = time.time()
cam = c.Camera("/usr/local/lib/libqhyccd.so", 0, c.DEFAULT_USB_TRAFFIC)
code = 0
try:
    for _ in range(2):
        t = time.time()
        a = cam.grab(0.001, 10, 140)
        if time.time() - t > 10:
            print(f"SLOW {time.time() - t:.1f}s", flush=True)
    print(f"OK mean={a.mean():.1f} std={a.std():.2f}", flush=True)
except RuntimeError as e:
    print(f"EMPTY {e}", flush=True)
    code = 3
finally:
    cam.close()
print(f"CYCLE {time.time() - t0:.1f}s", flush=True)
sys.exit(code)
