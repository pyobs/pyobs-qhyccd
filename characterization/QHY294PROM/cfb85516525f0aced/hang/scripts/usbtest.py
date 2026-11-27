"""Bias frames before/after a USB reset. Usage: usbtest.py [inproc]

Without argument: three 1 ms frames. With "inproc": a frame, usbreset while the camera is open, a frame on the old
handle, then close and reopen in the same process and a frame.
"""

import subprocess
import sys
import time

sys.path.insert(0, "tools")
import characterize as c  # noqa: E402

LIB = "/usr/local/lib/libqhyccd.so"


def frames(cam, n):
    for _ in range(n):
        t = time.time()
        try:
            a = cam.grab(0.001, 10, 140)
            print(f"  took {time.time() - t:5.1f}s mean={a.mean():8.1f} std={a.std():6.2f}", flush=True)
        except Exception as e:
            print(f"  took {time.time() - t:5.1f}s ERROR {type(e).__name__}: {e}", flush=True)


cam = c.Camera(LIB, 0, c.DEFAULT_USB_TRAFFIC)
frames(cam, 3 if len(sys.argv) == 1 else 1)
if len(sys.argv) > 1:
    print(
        "usbreset while open:", subprocess.run(["usbreset", "1618:c297"], capture_output=True, text=True).stdout.strip()
    )
    time.sleep(3)
    print("frame on old handle:")
    frames(cam, 1)
    try:
        cam.close()
    except Exception as e:
        print(f"close: {type(e).__name__}: {e}")
    print("reopen in same process:")
    try:
        cam = c.Camera(LIB, 0, c.DEFAULT_USB_TRAFFIC)
        frames(cam, 2)
    except Exception as e:
        print(f"reopen: {type(e).__name__}: {e}")
cam.close()
