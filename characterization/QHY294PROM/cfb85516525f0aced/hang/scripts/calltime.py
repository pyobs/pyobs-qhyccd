import sys
import threading
import time

sys.path.insert(0, "tools")
import characterize as c

cam = c.Camera("/usr/local/lib/libqhyccd.so", 0, c.DEFAULT_USB_TRAFFIC)
x0, y0, w, h = cam.info["EffectiveArea"]
cam.set_param(c.CONTROL_EXPOSURE, 5_000_000)
cam.set_roi(x0, y0, w // 8 * 8, h // 2 * 2)
t0 = time.monotonic()
log = []


def poll():
    while time.monotonic() - t0 < 8:
        t = time.monotonic()
        cam.temperature()
        log.append((t - t0, time.monotonic() - t))
        time.sleep(0.1)


th = threading.Thread(target=poll)
th.start()
time.sleep(0.5)
ts = time.monotonic() - t0
cam.expose()
te = time.monotonic() - t0
th.join()
print(f"frame call {ts:.2f} to {te:.2f} s")
for start, d in log:
    if d > 0.05:
        print(f"  call at {start:.2f}s took {d:.2f}s")
print(f"calls={len(log)}")
cam.close()
