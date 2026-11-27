# Hang tests, 26 and 27 Nov 2026

Results are in the [unit report](../README.md#camera-hang-with-empty-frames-open-problem). Run the scripts from the
repository root (they import `tools/characterize.py`); the shell scripts write their logs to the folder they are
started from, the Python scripts to the current folder.

- `scripts/cycle_one.py`, `cycleloop.sh`: open, one bias, close in mode 0, `CloseQHYCCD` every second cycle
  (`logs/cycleloop.log`).
- `scripts/cycle_mode.py`, `modeloop.sh`, `modeloop2.sh CALL_CLOSE SECONDS`: the same, alternating read mode 0 and 1;
  `modeloop2.sh` recovers via the other mode and goes on (`logs/modeloop.log`, `logs/modeloop2.log`).
- `scripts/coolstress.py DURATION [unlocked POLL_S]`: one process, cooler phases (`logs/coolstress_*.jsonl`).
- `scripts/longrun.py DURATION`: one process like the module at the telescope (`logs/longrun.jsonl`).
- `scripts/stress.py`, `calltime.py`: concurrent SDK calls during a readout; `usbtest.py`: `usbreset` tests.
- `scripts/telescope_episodes.py LOG`: finds slow readouts in a pyobs log; `telescope/episodes.txt` is its output
  for the frontend log (QHY lines only, from Feb 2025 to Mar 2026).
- `logs/hang_2026-11-26_1247/`: `lsusb`, kernel log and outputs of the first reproduced hang.
