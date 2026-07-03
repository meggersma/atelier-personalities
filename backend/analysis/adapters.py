"""
On-ramps into the canonical transcript format.

Two adapters: live sessions (session_to_transcript) and uploaded
deposition/cross transcripts (parse_uploaded_transcript). Uploads carry
enrichment=None — the analyzer never assumes live-session metadata.
"""

import re

from .schemas import (
    CanonicalTranscript,
    Enrichment,
    Speaker,
    TranscriptSource,
    Turn,
)


def session_to_transcript(session: dict) -> CanonicalTranscript:
    """Map a live examination session onto the canonical format.

    session["messages"] alternates user (examiner) / assistant (witness).
    Per-message metadata (encoding, state_delta, scores) is carried in the
    enrichment block, not on turns — the analyzer contract keeps turns
    source-agnostic so uploaded transcripts are first-class.
    """
    turns: list[Turn] = []
    for i, msg in enumerate(session.get("messages", [])):
        speaker = Speaker.EXAMINER if msg["role"] == "user" else Speaker.WITNESS
        turns.append(Turn(turn_id=i, speaker=speaker, text=msg["content"]))

    persona = session.get("persona") or {}
    return CanonicalTranscript(
        source=TranscriptSource.LIVE_SESSION,
        session_id=session.get("session_id"),
        witness_name=persona.get("name"),
        mode=session.get("mode"),
        case_context=persona.get("case_context") or persona.get("summary"),
        turns=turns,
        enrichment=Enrichment(
            trajectory=session.get("trajectory"),
            scores_trajectory=session.get("scores_trajectory"),
        ),
    )


# ── Uploaded transcript adapter ──────────────────────────────────────────────

# Court reporters number every line; strip the number, keep the content.
_LINE_NUMBER = re.compile(r"^\s*\d{1,3}\s{2,}")

_Q_START = re.compile(r"^Q[.:]\s*")
_A_START = re.compile(r"^A[.:]\s*")
# THE WITNESS: / THE COURT: / MR. DOE: / MS. O'BRIEN-SMITH:
_SPEAKER_LABEL = re.compile(
    r"^(THE WITNESS|THE COURT|(?:MR|MS|MRS|DR)\.\s+[A-Z][A-Z.'\- ]*)\s*:\s*"
)
_JUNK = re.compile(
    r"^(\d{1,4}|Page\s+\d+.*|BY\s+(?:MR|MS|MRS|DR)\.\s+[A-Z][A-Z.'\- ]*:?|"
    r"\(.*\)|-+|\*+|_{3,})$",
    re.IGNORECASE,
)

# The name group uses [ \t] separators only — captions put dates and
# locations on the following lines, and \s+ would swallow them.
_WITNESS_CAPTION = re.compile(
    r"(?:DEPOSITION|(?:CROSS[- ])?EXAMINATION|TESTIMONY)\s+OF[: \t]+([A-Z][A-Za-z.'\-]+(?:[ \t]+[A-Z][A-Za-z.'\-]+){1,3})"
)


def _clean_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = _LINE_NUMBER.sub("", raw).strip()
        if not line or _JUNK.match(line):
            continue
        lines.append(line)
    return lines


def parse_qa_text(text: str) -> list[Turn]:
    """Deterministic parse of Q./A. court-reporter format.

    Q. → examiner, A. / THE WITNESS: → witness, THE COURT: and named
    counsel (objections, colloquy) → other. Unattributed lines continue
    the current turn; leading matter before the first label is dropped.
    """
    turns: list[Turn] = []
    speaker: Speaker | None = None
    buffer: list[str] = []

    def flush():
        nonlocal buffer
        if speaker is not None and buffer:
            turns.append(Turn(turn_id=len(turns), speaker=speaker, text=" ".join(buffer)))
        buffer = []

    for line in _clean_lines(text):
        q = _Q_START.match(line)
        a = _A_START.match(line)
        label = _SPEAKER_LABEL.match(line)
        if q:
            flush()
            speaker = Speaker.EXAMINER
            buffer = [line[q.end():].strip()]
        elif a:
            flush()
            speaker = Speaker.WITNESS
            buffer = [line[a.end():].strip()]
        elif label:
            flush()
            who = label.group(1).upper()
            speaker = Speaker.WITNESS if who == "THE WITNESS" else Speaker.OTHER
            buffer = [line[label.end():].strip()]
        elif speaker is not None:
            buffer.append(line)
    flush()
    return [t for t in turns if t.text]


def _llm_parse(text: str, client) -> list[Turn]:
    """Fallback for transcripts the deterministic parser can't read
    (prose-style, unusual labels, OCR noise)."""
    from .analyzer import MODEL, _parse_llm_json  # noqa: PLC0415 — avoids import cycle at module load

    prompt = f"""Below is a deposition or examination transcript in a non-standard
format. Segment it into turns.

TRANSCRIPT:
{text[:24000]}

Return ONLY a JSON object:
{{"turns": [{{"speaker": "examiner|witness|other", "text": "<verbatim text of the turn>"}}]}}

Rules:
- examiner = the questioning attorney; witness = the person answering;
  other = the court, objecting counsel, or colloquy.
- Preserve wording verbatim. Do not summarize or merge distinct turns.
- Skip captions, appearances pages, certifications, and index pages."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    parsed = _parse_llm_json(response.content[0].text)
    turns = []
    for t in parsed.get("turns", []):
        try:
            speaker = Speaker(t["speaker"])
        except (KeyError, ValueError):
            continue
        if t.get("text", "").strip():
            turns.append(Turn(turn_id=len(turns), speaker=speaker, text=t["text"].strip()))
    return turns


def extract_witness_name(text: str) -> str | None:
    m = _WITNESS_CAPTION.search(text[:4000])
    return m.group(1).title() if m else None


def parse_uploaded_transcript(
    text: str,
    client,
    witness_name: str | None = None,
    mode: str | None = None,
    case_context: str | None = None,
) -> CanonicalTranscript:
    """Second on-ramp: raw transcript text → CanonicalTranscript.

    Deterministic Q./A. parse first; if that yields too little structure
    to be a real examination, fall back to LLM segmentation.
    """
    turns = parse_qa_text(text)
    examiner_turns = sum(1 for t in turns if t.speaker == Speaker.EXAMINER)
    if len(turns) < 4 or examiner_turns < 2:
        turns = _llm_parse(text, client)

    return CanonicalTranscript(
        source=TranscriptSource.UPLOADED,
        session_id=None,
        witness_name=witness_name or extract_witness_name(text),
        mode=mode,
        case_context=case_context,
        turns=turns,
        enrichment=None,
    )
