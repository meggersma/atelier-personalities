#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# monitor.sh  —  Check status of a running batch simulation.
#
# Usage:  ./monitor.sh [output-dir]   (default: ./output)
# ─────────────────────────────────────────────────────────────────────────────

OUT="${1:-./output}"
LOGFILE="$OUT/run.log"
PIDFILE="$OUT/run.pid"
CHECKPOINT="$OUT/checkpoint.json"

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo " Batch Simulation Monitor — $OUT"
echo "════════════════════════════════════════════════════════════════════════"

# ── Process status ────────────────────────────────────────────────────────────
if [[ -f "$PIDFILE" ]]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo " Status  : RUNNING (PID $PID)"
        echo " Stop    : kill $PID"
    else
        echo " Status  : NOT RUNNING (PID $PID — may have finished or crashed)"
    fi
else
    echo " Status  : No PID file found (not started yet, or cleaned up)"
fi

# ── Checkpoint progress ───────────────────────────────────────────────────────
if [[ -f "$CHECKPOINT" ]]; then
    python3 - <<'EOF' "$CHECKPOINT" "$LOGFILE"
import json, sys, re
from datetime import datetime, timedelta

checkpoint_path = sys.argv[1]
log_path = sys.argv[2]

data = json.load(open(checkpoint_path))
done = len(data)

# Total runs = witnesses * archetypes (infer from checkpoint keys)
witnesses = set(k.split("::")[0] for k in data)
archetypes = set(k.split("::")[1] for k in data)
# Use max observed counts (may be partial run)
total = len(witnesses) * len(archetypes) if witnesses and archetypes else "?"

print(f" Progress : {done} / {total} runs completed")

# Parse timestamps from log to estimate rate
timestamps = []
if log_path and __import__("os").path.exists(log_path):
    pattern = re.compile(r"\[(\d{2}:\d{2}:\d{2})\].*✓")
    today = datetime.now().date()
    for line in open(log_path, errors="replace"):
        m = pattern.search(line)
        if m:
            t = datetime.strptime(m.group(1), "%H:%M:%S").replace(
                year=today.year, month=today.month, day=today.day
            )
            timestamps.append(t)

if len(timestamps) >= 2 and isinstance(total, int) and done > 0:
    elapsed = (timestamps[-1] - timestamps[0]).total_seconds()
    rate = len(timestamps) / elapsed if elapsed > 0 else 0  # runs/sec
    remaining = total - done
    if rate > 0:
        eta_sec = remaining / rate
        eta_str = str(timedelta(seconds=int(eta_sec)))
        finish = datetime.now() + timedelta(seconds=eta_sec)
        print(f" Rate     : {rate * 60:.1f} runs/min")
        print(f" ETA      : ~{eta_str} remaining  (done ~{finish.strftime('%I:%M %p')})")
    else:
        print(" ETA      : calculating...")
else:
    print(" ETA      : not enough data yet")

print("")
print(" Last 10 completed runs:")
for entry in list(data)[-10:]:
    print(f"   ✓ {entry}")
EOF
fi

# ── Recent log output ─────────────────────────────────────────────────────────
if [[ -f "$LOGFILE" ]]; then
    SIZE=$(wc -l < "$LOGFILE" | tr -d ' ')
    echo ""
    echo " Log: $LOGFILE  ($SIZE lines)"
    echo ""
    echo " Last 20 log lines:"
    echo "────────────────────────────────────────────────────────────────────────"
    tail -20 "$LOGFILE"
    echo "────────────────────────────────────────────────────────────────────────"
    echo ""
    echo " Live tail: tail -f $LOGFILE"
fi

# ── Output files ──────────────────────────────────────────────────────────────
TRANSCRIPT_COUNT=$(find "$OUT" -name "*_transcript.txt" 2>/dev/null | wc -l | tr -d ' ')
DELTA_COUNT=$(find "$OUT" -name "*_deltas.json" 2>/dev/null | wc -l | tr -d ' ')
echo ""
echo " Output files:"
echo "   Transcripts : $TRANSCRIPT_COUNT"
echo "   Delta JSONs : $DELTA_COUNT"

echo "════════════════════════════════════════════════════════════════════════"
echo ""
