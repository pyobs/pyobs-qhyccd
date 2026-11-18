# QHY294PRO-M, serial number cfb85516525f0aced

This report describes what was measured on one QHY294PRO-M (monochrome, cooled CMOS camera) with the characterization
script of pyobs-qhyccd on 17 November 2026: bias, read noise versus gain and offset, readout time, pixel noise and dark
current down to -12 °C. The cooler stopped working at high drive on the first supply (1.5 A), see
[Cooling and the power supply](#cooling-and-the-power-supply). Notes that apply to every unit of the model are in the
[model notes](../README.md).

Each statement is marked as **measured** (own data, linked below), **inferred** (a conclusion from the data that was not
checked separately) or **from the SDK**. All numbers are for this unit.

## Summary

- **Bias noise** is 7.2 ADU at gain 10 and offset 140 (measured). It grows to 8.4 ADU at gain 400 and 10.5 ADU at gain
  800, falls back to 7.6 ADU at gain 1600 and is 19 ADU at gain 3000. Gain in e-/ADU and read noise in e- are not
  measured yet.
- **Dark current** is 0.045 ADU/s at 10 °C and halves about every 5 °C. Below -5 °C it is 0.003 to 0.004 ADU/s, close
  to what the method can resolve. There is no sign of amp glow in the mean (mean only; no images checked by eye).
- **Readout:** 0.6 s per full frame of the effective area, independent of binning (measured).
- **Cooling:** with the 1.5 A supply the cooler stopped working at 66% to 78% drive level (measured, twice). With a
  5 A supply it ran at full drive without trouble and reached -12.8 °C at 24.5 °C ambient (measured), which is about
  the limit of the cooler. The cause was probably the supply (inferred).
- **Not measured:** gain in e-/ADU, full well, linearity, short exposures, read mode 1.

## Setup

- Linux host, QHY SDK 25.9.29.10, camera on a USB 3.0 port, firmware loaded by the udev rule. Ambient about 20 °C.
- Read mode 0 ("11M MODE", 4164 x 2822), 16 bit, binning 1, USB traffic 60 unless stated otherwise, lens capped.
- Gain 10 and offset 140 for the dark and pixel runs (the pyobs-qhyccd defaults).
- Noise numbers come from the central 2048 x 2048 window; the pixel statistics use the whole effective area.
- All measurements were made with `tools/characterize.py` (see [Reproduce](../../README.md#reproduce)).
- Camera properties and controls as reported by the SDK: [meta.json](meta.json), summarised in the
  [model notes](../README.md#camera-properties).

## Bias and read noise (measured)

Pairs of bias frames (shortest exposure) at 21 °C, noise from the difference of each pair divided by the square root
of 2. Data: [bias.csv](bias.csv), plot: [images/bias.png](images/bias.png).

| Gain | Noise [ADU] | Clipped at offset 0 |
|---|---|---|
| 0 | 7.15 | 0.21% |
| 10 | 7.17 | 0.21% |
| 50 | 7.28 | 0.19% |
| 100 | 7.43 | 0.17% |
| 200 | 7.74 | 0.15% |
| 400 | 8.43 | 0.10% |
| 800 | 10.5 | 0.06% |
| 1600 | 7.58 | 0.39% |
| 3000 | 19 | 0.06% |

- The offset does not change the noise. The bias level is `offset * 64 + 24` ADU (24 ADU at offset 0 and 8984 ADU at
  offset 140 at gain 10 to 100) in read mode 0.
- With offset 10 and higher no pixel is clipped at zero.
- The bias level rises with gain from about gain 200 (8985 ADU at gain 200, 9000 at gain 800, 9039 at gain 3000, all at
  offset 140).
- The noise at gain 1600 is lower than at gain 800. A conversion gain switch would explain it (inferred, no photon
  transfer yet).

## Readout (measured)

Full effective area read at gain 10, offset 140. Data: [readout.csv](readout.csv).

| USB traffic | Bin 1 [s] | Bin 2 [s] | Bin 4 [s] |
|---|---|---|---|
| 0 | 0.62 | 0.64 | 0.59 |
| 60 | 0.60 | 0.63 | 0.60 |
| 150 | 0.71 | 0.75 | 0.73 |

- Binning is done on the sensor or in the SDK without a speed gain; the time is the same.
- At bin 2 the pixel values are the sum of four pixels (bias 35930 ADU, noise 14.5 ADU, twice the bin 1 noise).
- **Bin 4 is invalid:** the frames are all 65535 ADU, so its noise of 0.0 is not a measurement. Run again with a low
  offset.

## Pixels at 20 °C (measured)

60 bias frames (shortest exposure) at gain 10, offset 140, sensor at 20 °C (cooler off). Standard deviation per pixel over the
60 frames. Data: [pixels.csv](pixels.csv).

| Quantity | Value |
|---|---|
| Median per-pixel noise | 6.89 ADU |
| Mean per-pixel noise | 7.01 ADU |
| Pixels with noise above 1.25x the median | 2.2% |
| Pixels with noise above 3x the median | 0.21% |
| Pixels with noise above 5x the median | 0.05% |

There is a small tail of noisy pixels. The pyobs-asi camera has about 1% above 5x for comparison, so this camera shows
less salt-and-pepper noise (different sensor, different measurement date; inferred).

## Dark current and temperature (measured)

Ambient 20 °C. At each target the cooler was held for a few minutes, then a pair of 60 s darks and a pair of 300 s darks
were taken at gain 10, offset 140. The dark current is the mean of the pixels over time, in ADU/s (bias subtracted).
Data: [temperature.csv](temperature.csv), cooling log: [templog.csv](templog.csv), plot:
[images/temperature.png](images/temperature.png).

| Setpoint [°C] | Drive level | Dark 60 s [ADU/s] | Dark 300 s [ADU/s] | Bias noise [ADU] |
|---|---|---|---|---|
| 10 | 10% | 0.045 | 0.043 | 7.02 |
| 5 | 18% | 0.021 | 0.022 | 6.96 |
| 0 | 26% | 0.010 | 0.011 | 6.88 |
| -5 | 40% | 0.0038 | 0.0062 | 6.83 |
| -10 (SDK auto mode) | 55% | 0.0026 | 0.0038 | 6.76 |
| -10 (PI controller, sensor -10.7 to -11.0 °C) | 59% to 61% | 0.0042 | 0.0040 | 6.78 |
| -12 (PI controller, sensor -11.9 to -12.2 °C) | 65% to 66% | 0.0002 | 0.0028 | 6.74 |

- Above 0 °C the dark current halves every 5 °C (from 10 to 5 °C 0.045 to 0.021 ADU/s, from 5 to 0 °C to 0.010). The
  conversion to e- is missing until the gain is measured.
- The dark current flattens below -5 °C. The differences there (0.0002 to 0.006 ADU/s) are probably at the resolution
  of the method, since a 300 s dark collects only about 1 ADU per pixel (inferred).
- **Unexplained:** the 300 s darks give a higher rate than the 60 s darks at -5, -10 and -12 °C (for example 0.0028
  versus 0.0002 ADU/s at -12 °C), and the two -10 °C runs differ (0.0042 versus 0.0026 for 60 s). A residual bias
  drift (the bias is subtracted from a pair taken before the dark) or a warm-up in the first seconds of a long
  exposure would both fit. Neither was checked.
- The bias noise falls from 7.02 ADU at 10 °C to 6.74 ADU at -12 °C.

## Cooling and the power supply

**Cause of the earlier collapse (inferred): the 1.5 A supply.** On 17 November the cooler stopped working at about
-12 °C with two control methods (SDK auto mode and a PI controller on the manual PWM limited to 240), see the
[temperature table](#dark-current-and-temperature-measured). The sensor went from -11.9 °C to +2.4 °C within a minute
and then to ambient, with the PWM at 94%. On 18 November a sweep of fixed PWM levels from ambient showed the same with
the 1.5 A supply, and no collapse with a 5 A supply.

Fixed PWM, ascending levels, each held for up to 10 min or until the sensor moved less than 0.1 °C in 3 min. Data:
[cooling_1p5A_supply.jsonl](cooling_1p5A_supply.jsonl) and [cooling.jsonl](cooling.jsonl) (5 A). Ambient 23.3 °C (1.5 A)
and 24.5 °C (5 A), lens capped, no exposures.

| PWM | Drive level | 1.5 A supply, lowest [°C] | 5 A supply, lowest [°C] |
|---|---|---|---|
| 100 | 39% | -2.9 (not settled) | -2.0 (not settled) |
| 140 | 55% | -7.9 | -7.4 |
| 170 | 67% | -10.3 (settled for 10 min) | -9.8 |
| 200 | 78% | -10.1, then **warming to 29.9 °C within 10 min** | -11.5 |
| 220 | 86% | not run | -12.3 |
| 240 | 94% | not run | -12.8 |

- With the 1.5 A supply the sensor warmed above ambient (23 °C) at PWM 200 and kept the PWM reading of 200. With no
  supply connected at all (unplugged by mistake on 18 November) the sensor also warmed (23.3 to 24.7 °C in 150 s at
  PWM 100, measured), so the electronics alone heat it. The cooler had probably lost its power, not just been overloaded
  (inferred).
- Levels up to 170 gave the same temperatures on both supplies within 0.5 °C. The old supply only failed at the
  highest current. The first collapse was at about 66%, but after 20 min, with a warmer hot side (inferred: the
  current depends on the temperature difference as well as on the drive level).
- The 5 A supply is a different unit (voltage and polarity checked with a multimeter before connecting). The 1.5 A
  supply had a rating of 1.5 A; the current of the camera at full drive was not measured, and the rated current of the
  camera was not looked up.
- Full drive reaches only 37 °C below ambient (-12.8 °C at 24.5 °C ambient). Each step of 20 PWM above 170 gains less
  than 1 °C, so the cooler is near its limit (heat sink and fan, or the TEC itself). -15 °C needs a colder room or
  better heat removal (inferred).
- The qhyccd driver's workaround for "PWM above 250" (see the [model notes](../README.md#cooling)) was not tested
  here. Whether the other QHY cameras that stop cooling are also on too small supplies is open.

**Slow versus fast cooling.** The sweep jumped to each PWM level, so the sensor cooled at about 5 °C per minute at the start of a level. No collapse occurred on the 5 A supply, so the rate does not matter there.

**Bug found in the sweep script.** The collapse check first required a 2 °C drop from the start of the level, which
missed the failure at PWM 200 (the level started at -10.1 °C and never went lower), so the script ran the level for 10
min and started PWM 220 at 30 °C. It was interrupted by hand. The check now needs only a rise of 1 °C above the lowest
temperature of the level. The 1.5 A run in `cooling_1p5A_supply.jsonl` ends with the interrupted PWM 220 level.

## Not measured yet

- **Gain** (`gain` step, warm, about 1 h): e-/ADU, read noise in e- and full well per gain, including the step near
  gain 1600. Because dark current is so small, a flat field (`flat` step) is the more reliable source.
- **Flat and short** exposures (`flat`, `short`): need a uniform light source. Linearity and the real exposure time of
  short exposures.
- **Bin 4 readout** at a low offset, and the whole characterization in **read mode 1** (47M, `--read-mode 1`).
- **Temperature below -12 °C**, if the cooling collapse is solved.
- The long-exposure rate differences described under [Dark current](#dark-current-and-temperature-measured).

## Notes on the script

- `tools/characterize.py` talks to the SDK directly with ctypes, as the Cython driver does not expose min/max/step of the
  controls or the read modes.
- The temperature ramp starts from the sensor temperature if the cooler has no target or the sensor is more than 2 °C
  above the setpoint. The warm-up after a `CoolerLimit` stop used to fail with a second `CoolerLimit` from a stale
  target; fixed in this session (not tested on a camera that stopped cooling again).
- `frames/` holds FITS cutouts. pyobs-qhyccd has no `.gitignore` entry for them yet (pyobs-asi ignores `frames/` and
  `*.log` under `characterization/`); add one before committing.
