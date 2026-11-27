#!/bin/bash
# Alternate the close variant each cycle; stop at the first empty frame or error. Usage: cycleloop.sh SECONDS
# logs go to the current folder; the scripts run from the repository root
S=$(pwd)
H=$(dirname "$(readlink -f "$0")")
cd "$H/../../../../.."
L=$S/modeloop.log
end=$(( $(date +%s) + $1 ))
echo "START $(date +%T)" > $L
i=0
while [ $(date +%s) -lt $end ]; do
    i=$((i + 1))
    v=$(( i % 2 ))   # read mode
    QHYCCD_CALL_CLOSE=1 timeout 300 uv run python $H/cycle_mode.py $v > $S/mode_last.out 2>&1
    rc=$?
    out=$(grep -E "^(OK|EMPTY|SLOW|CYCLE|Traceback|[A-Za-z]+Error)" $S/mode_last.out)
    [ "$rc" != 0 ] && cp $S/mode_last.out $S/mode_fail_$i.out
    echo "$i $(date +%T) mode=$v rc=$rc $(echo $out | tr '\n' ' ')" >> $L
    if [ "$rc" != 0 ]; then echo "STOP at cycle $i (previous cycle mode=$(( (i - 1) % 2 )))" >> $L; break; fi
done
echo "END $(date +%T) cycles=$i" >> $L
