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
    DONE=$(python3 -c "import json,sys; d=json.load(open('$CHECKPOINT')); print(len(d))" 2>/dev/null || echo "?")
    echo " Progress: $DONE runs completed (checkpoint)"

    echo ""
    echo " Last 10 completed runs:"
    python3 - <<'EOF' "$CHECKPOINT"
import json, sys
data = json.load(open(sys.argv[1]))
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
