# QHY294PRO-M, serial number cfb85516525f0aced

This report describes what was measured on one QHY294PRO-M (monochrome, cooled CMOS camera) with the characterization
script of pyobs-qhyccd on 17 November 2026: bias, read noise versus gain and offset, readout time, pixel noise and dark
current down to -12 °C. The cooler stopped working below that, see
[Cooling collapse](#cooling-collapse-below-12-c). Notes that apply to every unit of the model are in the
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
- **Cooling:** the sensor follows the setpoint down to -12 °C at 66% drive level (ambient 20 °C). Below that the cooler
  stops working within one minute, with two different control methods (measured). Cause unknown.
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

## Cooling collapse below -12 °C

**What was seen (measured).** Two series reached -10 and -12 °C and then lost the cooling:

| Run | Control | What happened |
|---|---|---|
| 1 | SDK auto mode (`ControlQHYCCDTemp`, once per second) | Reached -10 °C at 55% drive level. At about -11.5 °C the sensor started to warm and ran to ambient, PWM near 100%. The script stopped the series. |
| 2 | PI controller on the manual PWM, cap 240 | Reached -10 and -12 °C at 66%. Within one minute after the -12 °C darks the sensor went from -11.9 °C to +2.4 °C (about 14 °C in 60 s) while the PWM rose to 240 (94%), then 10.6, 16.5 and 19.6 °C. The script stopped with "cooler at 94% and sensor at 11.7 degC, target -15 degC". |

- With the cooler still driven at 94%, the sensor did not recover; after switching the cooler off it returned to ambient
  (19.8 °C) within minutes.
- The PWM never exceeded 240 in run 2, so the PWM > 250 wrap that `QHYCCDCamera._update_cooling` works around cannot be
  the only cause (the workaround assumes the wrap, see the [model notes](../README.md#cooling)).
- The rate of 14 °C per minute is far faster than the cooling ever ran (about 1 °C per minute), so the cooler was most
  likely not producing any cooling at that moment rather than just being overloaded (inferred).
- Tim has seen the same behaviour on two different QHY cameras (reported, not measured here).

**Hypotheses, none tested:**

1. The firmware of the camera switches the cooler off when it sees a protection condition (current, temperature of the
   hot side, a maximum temperature difference). A stuck state until the cooler is set to 0 and back would fit.
2. The 12 V supply or the USB power cannot deliver the current at the drive level reached and the cooler drops out.
3. The hot side (heat sink and fan, or the camera's own heat exchange) saturates, so the temperature difference to the
   ambient is limited. This would make the sensor warm slowly, not 14 °C in a minute, and is the least likely.

## Next step: fixed PWM sweep

**Goal:** find out whether the collapse depends on the drive level or on the temperature, and what temperature each
drive level reaches in equilibrium. This separates the hypotheses and shows if the camera can stay below -12 °C at all.

**Plan (not done, waiting for the go-ahead):**

1. Camera at ambient with the cooler off (PWM 0), lens capped.
2. Add a `cooling` step to `tools/characterize.py` that sets a fixed PWM (no PI controller), for example 100, 140, 170,
   200, 220, 240 in this order, and logs sensor temperature and PWM every 5 s (as `templog.jsonl`).
3. Hold each level for 10 min or until the temperature changes by less than 0.1 °C in 3 min, whichever comes first.
4. Stop the step at once and set the PWM to 0 if the sensor warms by 1 °C or more while the PWM is held (collapse).
   Record the temperature, drive level and time at which it happens.
5. Between levels do not warm up; go to the next higher level. After a collapse, wait for the sensor to reach ambient
   and repeat that level once from ambient to see if it is reproducible.
6. Measure the supply voltage at the camera connector during the sweep with a multimeter, if possible (rating of the
   supply to be checked before).
7. Afterwards, test the camera's own regulation with `SetQHYCCDParam(CONTROL_COOLER, target)` in place of the manual
   PWM, with the same logging, to see whether it collapses at the same temperature.

**Cost and risk:** about 1 to 1.5 h. One or two more collapses are likely. The camera is not at risk (it returned to
ambient after both collapses), but nothing is known about long-term
stress on the cooler. The sweep stops at the first sign of warming.

**What each result would mean (inferred):**

- Collapse at a similar drive level (about 66% to 70%) regardless of the temperature: current or supply limit.
- Collapse at a similar temperature (about -12 °C) at higher drive levels only: a temperature-based protection.
- No collapse at fixed PWM but collapse with the PI controller: an effect of the changing PWM (for example the
  controller's steps), which the driver could avoid.
- No collapse with `CONTROL_COOLER`: change the driver to that mode instead of `ControlQHYCCDTemp` park-and-retry.

After the sweep, a separate proposal for the driver (`QHYCCDCamera._update_cooling`) follows. The driver was not
changed.

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
