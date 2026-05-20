#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run_batch.sh  —  Launch the full batch simulation in the background.
#
# Usage:
#   ./run_batch.sh <input-file> [output-dir] [extra batch_sim.py flags]
#
# Input file can be:
#   - A .zip of deposition transcripts  (original mode)
#   - A .pdf or .txt case document      (document-first mode: auto-extracts
#                                        personas and generates questions)
#
# Examples:
#   ./run_batch.sh attorney_questions.zip
#   ./run_batch.sh attorney_questions.zip ./output --max-questions 30
#   ./run_batch.sh attorney_questions.zip ./output --witnesses "James Rausch" "Kate Neely"
#   ./run_batch.sh case_file.pdf ./output
#   ./run_batch.sh witness_statement.txt ./output --archetypes Neutral Combative
#
# The process runs detached from your terminal. You can close the terminal
# window safely. On macOS it uses `caffeinate` to prevent idle/system sleep
# while plugged into power — keep the power cable connected if you need it
# to run while you're away.
# ─────────────────────────────────────────────────────────────────────────────

set -eo pipefail

INPUT="${1:-}"
OUT="${2:-./output}"

if [[ -z "$INPUT" ]]; then
    echo "Usage: ./run_batch.sh <input-file> [output-dir] [extra flags...]"
    echo ""
    echo "  input-file can be:"
    echo "    *.zip   — deposition transcripts (original mode)"
    echo "    *.pdf   — case document (auto-extract personas + generate questions)"
    echo "    *.txt   — text document (auto-extract personas + generate questions)"
    exit 1
fi

# Collect any extra flags after INPUT and OUT
EXTRA_ARGS=()
if [[ $# -gt 2 ]]; then
    EXTRA_ARGS=("${@:3}")
fi

mkdir -p "$OUT"

LOGFILE="$OUT/run.log"
PIDFILE="$OUT/run.pid"

# ── Python / venv resolution ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$SCRIPT_DIR/backend/.venv/bin/python" ]]; then
    PYTHON="$SCRIPT_DIR/backend/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    PYTHON="python"
fi

# ── Detect input mode based on file extension ─────────────────────────────────
EXT="${INPUT##*.}"
EXT="$(echo "$EXT" | tr '[:upper:]' '[:lower:]')"

if [[ "$EXT" == "zip" ]]; then
    INPUT_FLAG="--questions-zip"
    # Print question manifest first (runs in foreground so you can see it)
    echo ""
    echo "════════════════════════════════════════════════════════════════════════"
    echo " Question manifest (which questions are assigned to each witness):"
    echo "════════════════════════════════════════════════════════════════════════"
    "$PYTHON" "$SCRIPT_DIR/batch_sim.py" \
        --questions-zip "$INPUT" \
        --out "$OUT" \
        --preview \
        "${EXTRA_ARGS[@]}"

    # If --preview was requested, stop here — don't launch background job
    for arg in "${EXTRA_ARGS[@]}"; do
        if [[ "$arg" == "--preview" ]]; then
            exit 0
        fi
    done
else
    INPUT_FLAG="--input-file"
    echo ""
    echo "════════════════════════════════════════════════════════════════════════"
    echo " Document-first mode: $INPUT"
    echo " Personas will be extracted from the document and questions generated"
    echo " automatically by Claude."
    echo "════════════════════════════════════════════════════════════════════════"
fi

# ── Launch detached background process ────────────────────────────────────────
echo "" > "$LOGFILE"   # truncate/create log

# caffeinate flags:
#   -i  prevent idle sleep (works on battery)
#   -s  prevent system sleep when on AC power
#   Together they keep the machine awake in as many conditions as possible.
#   NOTE: closing the laptop lid forces sleep regardless of caffeinate.
#         Keep the machine open or connected to an external display to be safe.

nohup caffeinate -i -s \
    "$PYTHON" "$SCRIPT_DIR/batch_sim.py" \
    "$INPUT_FLAG" "$INPUT" \
    --out "$OUT" \
    "${EXTRA_ARGS[@]}" \
    >> "$LOGFILE" 2>&1 &

BG_PID=$!
echo "$BG_PID" > "$PIDFILE"
disown "$BG_PID"

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo " Batch simulation started in background"
echo "   PID      : $BG_PID"
echo "   Log      : $LOGFILE"
echo "   Output   : $OUT"
echo ""
echo " Commands:"
echo "   Monitor  : ./monitor.sh $OUT"
echo "   Stop     : kill \$(cat $PIDFILE)"
echo "   Progress : grep '✓' $LOGFILE | tail -20"
echo "════════════════════════════════════════════════════════════════════════"
echo ""
echo "⚡  TIP: Keep your machine awake (power cable connected, lid open)"
echo "        for the most reliable background run."
echo ""
