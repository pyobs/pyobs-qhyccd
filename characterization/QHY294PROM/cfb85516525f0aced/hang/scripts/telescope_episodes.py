"""Find hang episodes in a pyobs log of the QHYCCD camera module.

Usage: telescope_episodes.py LOG

The old module did not check for empty frames, so a hang shows up as a readout that took 50 to 80 s longer than the
exposure. An episode is a run of such exposures; it ends with a normal exposure or a start of the module.
"""

import re
import sys
from datetime import datetime


def ts(line: str) -> datetime:
    return datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S,%f")


events = []  # (time, kind, info)
start = exp = None
for line in open(sys.argv[1], errors="replace"):
    if not re.match(r"\d{4}-", line):
        continue
    if "Creating module from class" in line:
        events.append((ts(line), "START", ""))
        continue
    if "Got signal" in line:
        events.append((ts(line), "STOP", ""))
        continue
    m = re.search(r"Starting exposure with (\w+) shutter for ([\d.]+)", line)
    if m:
        start, exp, shut = ts(line), float(m.group(2)), m.group(1)
        continue
    if "Readout finished" in line and start:
        extra = (ts(line) - start).total_seconds() - exp
        events.append((ts(line), "EXP", (exp, shut, extra)))
        start = None
    elif re.search(r"\[(ERROR|WARNING)\]", line):
        events.append((ts(line), "ERR", line[24:150].strip()))

# episodes: runs of consecutive bad exposures
eps, cur, since_start, last_start, last_ok = [], None, 0, None, None
for t, k, i in events:
    if k == "START":
        since_start, last_start = 0, t
        if cur:
            cur["end_by"] = "restart"
            eps.append(cur)
            cur = None
        continue
    if k != "EXP":
        continue
    since_start += 1
    bad = 50 < i[2] < 80
    if bad and cur is None:
        after_start = (t - last_start) if last_start else None
        cur = dict(t0=t, n=0, since=since_start, after_start=after_start, prev_ok=last_ok, first=i)
    if bad:
        cur["n"] += 1
        cur["t1"] = t
    if not bad:
        if cur:
            cur["end_by"] = f"ok exposure {t:%m-%d %H:%M}"
            eps.append(cur)
            cur = None
        last_ok = t
if cur:
    cur["end_by"] = "log end"
    eps.append(cur)

header = f"{'first bad':19} {'#bad':>5} {'exp# since start':>16} {'since start':>12} {'since last ok':>13}"
print(f"{header}  first(exp,shutter)  ended by")
for e in eps:
    ss = str(e["after_start"]).split(".")[0] if e["after_start"] else "?"
    po = str(e["t0"] - e["prev_ok"]).split(".")[0] if e["prev_ok"] else "?"
    row = f"{e['t0']:%Y-%m-%d %H:%M:%S} {e['n']:5} {e['since']:16} {ss:>12} {po:>13}"
    print(f"{row}  {e['first'][0]:6.2f} {e['first'][1]:6}  {e['end_by']}")
print(len(eps), "episodes,", sum(e["n"] for e in eps), "bad exposures")
