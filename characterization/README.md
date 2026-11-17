# Camera characterization

Measurements of QHY cameras run with pyobs-qhyccd. Each camera model has its own folder with notes that apply to every
unit of that model, and one subfolder per unit, named after its serial number, with the measurements.

| Model | Units |
|---|---|
| [QHY294PRO-M](QHY294PROM/README.md) | [cfb85516525f0aced](QHY294PROM/cfb85516525f0aced/README.md) |

## Layout

```
characterization/
  <model>/
    README.md          notes for the model: SDK, driver, recommended settings, open problems
    <serial number>/
      README.md        report of the measurements on this unit
      *.jsonl          raw records written by tools/characterize.py
      *.csv            the same data as tables
      meta.json        camera properties and controls as reported by the SDK, and the serial number
      images/          plots
      frames/          2048x2048 FITS cutouts (not kept in git)
```

The serial number is the part of the SDK camera ID after the model name (`QHY294PROM-cfb85516525f0aced`). It was not
checked against the label on the camera (inferred).

## Reproduce

`tools/characterize.py` runs the measurements through the QHY SDK with ctypes (no other program may use the camera). It
writes into `characterization/<model>/<serial number>/` of the connected camera (`_mode<N>` is appended for a read mode
other than 0). With the lens capped:

```bash
uv run python tools/characterize.py bias
uv run python tools/characterize.py readout
uv run python tools/characterize.py pixels --no-cooling
uv run python tools/characterize.py temperature --temperatures 10 5 0 -5 -10
uv run python tools/characterize.py gain --target-temp 10
```

With the lens open, pointed at a steady, defocused light source:

```bash
uv run python tools/characterize.py flat
uv run python tools/characterize.py short
```

The camera cools through a PI controller in the script that sets the PWM of the cooler directly (see the
[model notes](QHY294PROM/README.md#cooling)); `--no-cooling` leaves the cooler off. The `report` step needs no camera.
It redraws the plots in `images/` and writes a CSV file next to every `.jsonl` file:

```bash
uv run python tools/characterize.py report --folder characterization/QHY294PROM/cfb85516525f0aced
```

Not done yet for this camera: `gain`, `flat`, `short`, read mode 1 (`--read-mode 1`) and bin 4 at a low offset. See
the [unit report](QHY294PROM/cfb85516525f0aced/README.md#not-measured-yet).
