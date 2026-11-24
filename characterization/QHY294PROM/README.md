# QHY294PRO-M

Notes on the QHY294PRO-M (monochrome, cooled CMOS camera, IMX492-class sensor, SDK name `QHY294PROM`) that apply to
every unit of this model when driven by pyobs-qhyccd: SDK and driver behaviour, cooling and recommended settings. The
notes are based on one unit so far. The measurements are per unit:

| Serial number | Measured | Report |
|---|---|---|
| cfb85516525f0aced | November 2026 | [cfb85516525f0aced/README.md](cfb85516525f0aced/README.md) |

## Camera properties

From the SDK (full list in [meta.json](cfb85516525f0aced/meta.json)):

| Property | Value |
|---|---|
| Sensor | 19.5 x 13.2 mm, pixel 4.63 µm (pixel size not read from the SDK, see below), 16 bit |
| Read mode 0 | "11M MODE", 4164 x 2822 |
| Read mode 1 | "47M MODE", 8336 x 5648, effective area x 80, y 0, 8336 x 5622; about 3 times the bias noise of mode 0 at low gain, see [unit report](cfb85516525f0aced/README.md#read-mode-1-47m-mode) |
| Effective area | x 36, y 28, 4164 x 2795 (read mode 0) |
| Binning | 1, 2, 4 |
| Exposure | 1 µs to 3600 s |
| Gain | 0 to 3624 (pyobs-qhyccd default 10) |
| Offset | 0 to 200 (pyobs-qhyccd default 140) |
| USB traffic | 0 to 255 (pyobs-qhyccd default 60) |
| Manual PWM (cooler) | 0 to 255 |
| Speed | not available |

`GetQHYCCDChipInfo` returned garbage for the pixel size and image size in the ctypes script (the structure was
probably not filled for this model). The 4.63 µm is from the documentation, not from the SDK (not checked).

## Recommended use

Preliminary, from the warm bias and readout runs and the dark runs down to -12 °C of one unit (5 A supply for the
cooling numbers):

- Offset 140 (the pyobs-qhyccd default) clips nothing at any gain tested (every offset from 10 up is clean). Offset 0
  clips about 0.2% of the pixels at gain 0 to 100 and 0.4% at gain 1600. Offset 200 leaves 12800 ADU of bias, which
  costs dynamic range for nothing.
- Gain 10 and offset 140 give a bias noise of 7.2 ADU. The noise rises slowly to 8.4 ADU at gain 400 and 10.5 ADU at
  gain 800, drops to 7.6 ADU at gain 1600 and jumps to 19 ADU at gain 3000. The conversion gain is 1.03 e-/ADU at gain 0,
  0.83 at 400, 0.51 at 1000, 0.22 at 1600 and 0.068 at 3000, so the read noise is 7.2 e- up to gain 400 and 1.7 e- at gain
  1600: a switch of the conversion gain between gain 800 and 1600 (inferred from photon transfer, exact gain not found).
  For low noise use gain 1600 or higher, for dynamic range gain 0 to 100 (58 ke- above the bias, the ADC clips before
  the pixels saturate).
- Binning in the camera adds the pixels (bias 4x at bin 2, 16x at bin 4) and the read noise grows with the square root of
  the number of pixels, so it gives no noise advantage over software binning. With offset 140 and gain 10, bin 4 is
  saturated at 65535; use offset 10 or less when binning (bin 4 then has a bias of 10600 ADU and 30.6 ADU noise).
- A full read of the effective area takes 0.6 s with USB traffic 0 and 60, and 0.71 s with 150. Binning does not make
  it faster. USB traffic 60 costs nothing measurable here.
- Dark current is low enough to be hard to measure: 0.045 ADU/s at 10 °C, halving about every 5 °C, and about
  0.0037 ADU/s at -10 °C (900 s darks; see the unit report).
- Cooling target: about 10 °C below ambient is easy (55% drive level); the cooler reaches about 33 °C below ambient at
  full drive and gains less than 1 °C per 20 PWM above 170, so do not plan for more than about -10 to -12 °C in a room at
  about 20 °C.

## Cooling

Three ways to set the cooler exist in the SDK, and the pyobs-qhyccd driver uses the first:

1. `ControlQHYCCDTemp(handle, target)`: the SDK's own loop, which has to be called about once per second.
2. `SetQHYCCDParam(CONTROL_COOLER, target)`: the camera regulates (tested to -10 °C, ramp and jump).
3. `SetQHYCCDParam(CONTROL_MANULPWM, 0..255)`: a fixed cooler drive level. PWM 0 stops the cooling.

`GetQHYCCDParam(CONTROL_COOLER)` returns the last target that was set, so the setpoint can be read back.
`CONTROL_CURPWM` returns garbage until the first PWM was set after opening.

The "power" in the characterization logs is `PWM / 255 * 100`. It is the drive level, not an electrical power (the
documentation does not say whether it is a duty cycle; not checked).

**Power supply.** Use a supply that can deliver much more than the 1.5 A that failed on this unit. The cooler stopped
working at 66% to 78% drive level with a 1.5 A supply and held full drive with a 5 A supply. The rated current of the
camera was not looked up (check its label or manual before choosing a supply). Verify the polarity with a multimeter
before connecting a supply. See the [unit report](cfb85516525f0aced/README.md#cooling-and-the-power-supply).

**Possible cause of the cooling problem in the driver (unverified).** `QHYCCDCamera._update_cooling` works around a QHY
bug where the cooler stops when the PWM exceeds 250: it parks the setpoint 5 °C above the sensor and ramps back. Tim has
seen the same behaviour on two different QHY cameras. On this unit the collapse came at 78% or lower and went away with
a bigger supply, so a supply that is too small may explain at least part of what the workaround covers. Not tested on the
other cameras.

**Reach.** With the 5 A supply at an ambient of about 20 °C the camera reached -12.8 °C at PWM 240; PWM 200 gave -11.5 °C and PWM
170 gave -9.8 °C.

**Characterization script.** `tools/characterize.py` drives the cooler with a PI controller on the PWM (1 Hz, gains
`PWM_KP` = 15, `PWM_KI` = 0.3 per second, PWM limited to 240, anti-windup). The target is stepped by 1 °C per minute
and the series stops with `CoolerLimit` if the cooler is above 90% for 2 minutes and the sensor is more than 1 °C from
the target. The first runs of the SDK's own cooler control were flagged as a collapse by a wrong check in the script; the
repeats with the fixed check show that the SDK controls cool to -10 °C by ramp or jump and hold it (see the
[unit report](cfb85516525f0aced/README.md#sdk-cooling-control-5-a-supply)). The earlier statement that the SDK auto mode
warmed the sensor is not supported by these runs; the small steps of the script are kept.

## Software notes

**Firmware.** The camera shows up as `1618:c296` (Cypress WestBridge) until the firmware is loaded and as `1618:c297`
afterwards. The udev rule loads `/lib/firmware/qhy/QHY294PRO.img` with `fxload` when the device is added. Reloading the
rules is not enough: replug the camera.

**SDK.** 25.9.29.10 (`/usr/local/lib/libqhyccd.so`). Frames block in `GetQHYCCDSingleFrame`. Reading the whole list of
controls through the Cython driver hung once; the script reads only the controls it needs, with timeouts. The Cython
driver (`QHYCCDDriver`) does not expose min/max/step of the controls or the read modes; the script uses ctypes for that.

**Driver.** `QHYCCDDriver` is now written with ctypes (no Cython, SDK installed on the machine). `CloseQHYCCD` of SDK
25.9.29.10 joins a thread handle that it never sets (with `MALLOC_PERTURB_=165` the handle is 0x5A5A5A5A5A5A5A5A and the
process segfaults in `pthread_join`), so it worked, hung or crashed depending on the heap, and importing pycares
changed the heap enough to trigger it. The driver does not call it by default (`QHYCCD_CALL_CLOSE=1` does). Not yet
reported to QHY.
