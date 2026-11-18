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
| Read mode 1 | "47M MODE", 8336 x 5648 (not measured yet) |
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

Preliminary, from the warm bias and readout runs and the dark runs down to -12 °C of one unit:

- Offset 140 (the pyobs-qhyccd default) clips nothing at any gain tested (every offset from 10 up is clean). Offset 0
  clips about 0.2% of the pixels at gain 0 to 100 and 0.4% at gain 1600. Offset 200 leaves 12800 ADU of bias, which
  costs dynamic range for nothing.
- Gain 10 and offset 140 give a bias noise of 7.2 ADU. The noise rises slowly to 8.4 ADU at gain 400 and 10.5 ADU at
  gain 800, drops to 7.6 ADU at gain 1600 and jumps to 19 ADU at gain 3000. The step at gain 1600 looks like a switch
  of the conversion gain (inferred, not checked with photon transfer).
- Do not use bin 4 with offset 140 and gain 10: the frames are saturated at 65535. Bin 2 has a bias of 35930 ADU (the
  bins are added, not averaged) at the same offset. Use a lower offset when binning.
- A full read of the effective area takes 0.6 s with USB traffic 0 and 60, and 0.71 s with 150. Binning does not make
  it faster. USB traffic 60 costs nothing measurable here.
- Dark current is low enough to be hard to measure: 0.045 ADU/s at 10 °C, halving about every 5 °C, and about
  0.003 to 0.004 ADU/s below -5 °C (see the unit report).

## Cooling

Three ways to set the cooler exist in the SDK, and the pyobs-qhyccd driver uses the first:

1. `ControlQHYCCDTemp(handle, target)`: the SDK's own loop, which has to be called about once per second.
2. `SetQHYCCDParam(CONTROL_COOLER, target)`: the camera regulates (not tested here).
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

**Reach.** With the 5 A supply at ambient 24.5 °C the camera reached -12.8 °C at PWM 240; PWM 200 gave -11.5 °C and PWM
170 gave -9.8 °C.

**Characterization script.** `tools/characterize.py` drives the cooler with a PI controller on the PWM (1 Hz, gains
`PWM_KP` = 15, `PWM_KI` = 0.3 per second, PWM limited to 240, anti-windup). The target is stepped by 1 °C per minute
and the series stops with `CoolerLimit` if the cooler is above 90% for 2 minutes and the sensor is more than 1 °C from
the target. The auto mode of the SDK pegged the PWM at 255 for a large temperature error and warmed the sensor, which is
why the steps are small.

## Software notes

**Firmware.** The camera shows up as `1618:c296` (Cypress WestBridge) until the firmware is loaded and as `1618:c297`
afterwards. The udev rule loads `/lib/firmware/qhy/QHY294PRO.img` with `fxload` when the device is added. Reloading the
rules is not enough: replug the camera.

**SDK.** 25.9.29.10 (`/usr/local/lib/libqhyccd.so`). Frames block in `GetQHYCCDSingleFrame`. Reading the whole list of
controls through the Cython driver hung once; the script reads only the controls it needs, with timeouts. The Cython
driver (`QHYCCDDriver`) does not expose min/max/step of the controls or the read modes; the script uses ctypes for that.

**Not done yet:** the driver was not changed, and the read mode selection and the cooling workaround have not been
tested against the camera in this session.
