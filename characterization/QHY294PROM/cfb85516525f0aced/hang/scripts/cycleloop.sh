#!/bin/bash
# Alternate the close variant each cycle; stop at the first empty frame or error. Usage: cycleloop.sh SECONDS
# logs go to the current folder; the scripts run from the repository root
S=$(pwd)
H=$(dirname "$(readlink -f "$0")")
cd "$H/../../../../.."
L=$S/cycleloop.log
end=$(( $(date +%s) + $1 ))
echo "START $(date +%T)" > $L
i=0
while [ $(date +%s) -lt $end ]; do
    i=$((i + 1))
    v=$(( i % 2 ))   # 1: CloseQHYCCD called, 0: skipped
    QHYCCD_CALL_CLOSE=$v timeout 300 uv run python $H/cycle_one.py > $S/cycle_last.out 2>&1
    rc=$?
    out=$(grep -E "^(OK|EMPTY|SLOW|CYCLE|Traceback|[A-Za-z]+Error)" $S/cycle_last.out)
    [ "$rc" != 0 ] && cp $S/cycle_last.out $S/cycle_fail_$i.out
    echo "$i $(date +%T) close=$v rc=$rc $(echo $out | tr '\n' ' ')" >> $L
    if [ "$rc" != 0 ]; then echo "STOP at cycle $i (previous cycle close=$(( (i - 1) % 2 )))" >> $L; break; fi
done
echo "END $(date +%T) cycles=$i" >> $L
