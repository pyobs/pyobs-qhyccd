#!/bin/bash
# Alternate read mode 0/1 every cycle (one process each, one full-frame bias). On an empty frame, recover by opening
# the other mode and then the same mode again, log it, and go on; stop if the recovery fails.
# Usage: modeloop2.sh CALL_CLOSE SECONDS
# logs go to the current folder; the scripts run from the repository root
S=$(pwd)
H=$(dirname "$(readlink -f "$0")")
cd "$H/../../../../.."
L=$S/modeloop2.log
close=$1
end=$(( $(date +%s) + $2 ))
echo "START close=$close $(date +%T)" >> $L
run() {  # mode -> sets rc, out
    QHYCCD_CALL_CLOSE=$close timeout 300 uv run python $H/cycle_mode.py $1 > $S/mode2_last.out 2>&1
    rc=$?
    out=$(grep -E "^(OK|EMPTY|CYCLE|Traceback|[A-Za-z]+Error)" $S/mode2_last.out | tr '\n' ' ')
}
i=0
while [ $(date +%s) -lt $end ]; do
    i=$((i + 1))
    m=$(( i % 2 ))
    run $m
    echo "$i $(date +%T) close=$close mode=$m rc=$rc $out" >> $L
    if [ "$rc" != 0 ]; then
        echo "HANG close=$close mode=$m cycle=$i" >> $L
        o=$(( 1 - m ))
        run $o; echo "  recover other mode=$o rc=$rc $out" >> $L
        run $m; echo "  recover same mode=$m rc=$rc $out" >> $L
        if [ "$rc" != 0 ]; then echo "RECOVERY FAILED, stop" >> $L; exit 1; fi
    fi
done
echo "END close=$close $(date +%T) cycles=$i" >> $L
