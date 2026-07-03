"""
The analyzer: CanonicalTranscript in, Analysis out.

Reviewer profiles shape the prompt's voice and emphasis. DEFAULT_REVIEWER
is a generic senior litigator; partner twins (Sarah Park, David Chen)
plug in here later as additional profiles with distinct emphasis text.
"""

import json
import re
import uuid
from datetime import datetime, timezone

from .schemas import (
    Analysis,
    Annotation,
    CanonicalTranscript,
    LLMAnalysis,
    Pattern,
    Span,
    Speaker,
)

MODEL = "claude-sonnet-4-6"

DEFAULT_REVIEWER = {
    "reviewer_id": "default_senior_litigator",
    "name": "Senior Litigator",
    "blurb": "Balanced review across form, strategy, control, and the record.",
    "emphasis": (
        "You are an experienced trial lawyer reviewing a junior associate's "
        "examination. Balance form, strategy, control, and the record. Be "
        "direct and specific — every note should name what happened and why "
        "it matters. Praise genuinely strong sequences; do not pad."
    ),
}

REVIEWERS = {
    DEFAULT_REVIEWER["reviewer_id"]: DEFAULT_REVIEWER,
    "sarah_park": {
        "reviewer_id": "sarah_park",
        "name": "Sarah Park",
        "blurb": "Form-strict. Question construction and the cleanliness of the record above all.",
        "emphasis": (
            "You are Sarah Park, a litigation partner known for being unforgiving "
            "on question form. Your core belief: control is lost one compound "
            "question at a time, and the record is the only thing that survives "
            "the trial. Scrutinize every question's construction — flag compound, "
            "vague, and assumption-laden questions even when the witness happened "
            "to answer cleanly, because next time she won't. Almost every form "
            "note should carry a suggested_rewrite; rewrites are how associates "
            "learn. You are sparing with praise — reserve it for sequences that "
            "are genuinely airtight. Your notes are clipped and precise; you "
            "quote the offending words back before explaining the failure. "
            "Severity calibration: form errors that create record ambiguity are "
            "major, not minor. Strategy commentary is not your focus — note only "
            "the strategic errors too large to ignore."
        ),
    },
    "david_chen": {
        "reviewer_id": "david_chen",
        "name": "David Chen",
        "blurb": "Strategy-focused. Sequencing, witness control arcs, and how the record plays to a jury.",
        "emphasis": (
            "You are David Chen, a litigation partner who reviews examinations "
            "the way a jury hears them: as a story unfolding. Your core belief: "
            "a technically imperfect question that lands is worth more than a "
            "perfect one asked in the wrong order. Focus on sequencing, exit "
            "strategy, and the control arc — where the examiner built momentum, "
            "where they surrendered it, and what the factfinder believes at each "
            "beat. You are forgiving of minor form slips (flag them as minor, "
            "briefly) but merciless about strategic errors: revealing the "
            "destination early, pressing past a won point, entering lines with "
            "no exit. Your notes read like a colleague talking through the "
            "moment — what the jury saw, what the witness was handed. You praise "
            "generously when momentum was built and banked, because associates "
            "repeat what gets named. Most of your notes are comment-only; you "
            "suggest rewrites only when the fix is structural."
        ),
    },
}

TAXONOMY = """\
FORM (question construction — usually warrants a suggested_rewrite):
- compound_question: two or more questions in one; answer is ambiguous on the record
- vague_question: imprecise terms the witness can reinterpret
- assumes_facts: embeds a fact not yet established
- calls_for_narrative: open invitation for the witness to talk at length (on cross)
- unintended_leading: leading on direct, or losing the leading form on cross

STRATEGY (judgment calls — often comment-only, no rewrite):
- one_question_too_many: had the admission, asked for the conclusion, gave it back
- missed_impeachment: prior inconsistent statement available but unused
- failure_to_pin: moved on without locking the witness to a specific answer
- sequencing_error: revealed the destination before closing the exits
- no_exit: entered a line of questioning with no safe way out

CONTROL / STYLE:
- lost_control: witness took over the exchange
- tone_drift: register slipped (argumentative, apologetic, casual)
- telegraphing: signaled where the examination was going
- controlled_sequence: PRAISE — a tight, controlled sequence worth repeating

THE RECORD:
- objection_drawn: question form invited an objection
- objection_sustained: objection made and sustained
- answer_over_question: witness's answer outran the question, uncorrected
- exhibit_mishandled: foundation or handling error with an exhibit"""

SEVERITY = """\
- critical: cost you the point — the error changed what the record shows
- major: weakened the record or ceded control
- minor: polish — worth fixing, didn't hurt this time
- praise: keep doing this"""


def distill_reviewer(name: str, materials: str, client) -> dict:
    """Turn samples of a real partner's feedback (redline comments, memos,
    emails about associates' examinations) into a reviewer profile."""
    prompt = f"""Below are samples of feedback written by {name}, a litigation
partner, about examinations and depositions. Study how they review: what they
fixate on, what they let slide, how harsh their calibration is, whether they
rewrite questions or comment strategically, their voice and phrasing habits.

FEEDBACK SAMPLES:
{materials[:12000]}

Return ONLY a JSON object:
{{
  "blurb": "<one line, under 15 words, describing their reviewing style>",
  "emphasis": "<a second-person briefing that makes an AI reviewer produce feedback indistinguishable from {name}'s: 'You are {name}, ...' — their core beliefs about examination, what they always flag, what they ignore, their severity calibration, whether and when they suggest rewrites, their tone and phrasing habits. Quote their characteristic expressions where the samples show them. 150-250 words.>"
}}"""
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    profile = _parse_llm_json(response.content[0].text)
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return {
        "reviewer_id": f"custom_{slug}",
        "name": name,
        "blurb": profile["blurb"],
        "emphasis": profile["emphasis"],
        "custom": True,
    }


def _transcript_block(transcript: CanonicalTranscript) -> str:
    lines = []
    for t in transcript.turns:
        label = {
            Speaker.EXAMINER: "EXAMINER",
            Speaker.WITNESS: "WITNESS",
            Speaker.OTHER: "OTHER",
        }[t.speaker]
        lines.append(f"[{t.turn_id}] {label}: {t.text}")
    return "\n".join(lines)


def _build_prompt(transcript: CanonicalTranscript, reviewer: dict) -> str:
    context_bits = []
    if transcript.witness_name:
        context_bits.append(f"Witness: {transcript.witness_name}")
    if transcript.mode:
        context_bits.append(f"Examination type: {transcript.mode}")
    if transcript.case_context:
        context_bits.append(f"Case context: {transcript.case_context}")
    context = "\n".join(context_bits) or "No case context provided."

    return f"""{reviewer["emphasis"]}

{context}

TRANSCRIPT (turn ids in brackets):
{_transcript_block(transcript)}

ANNOTATION CATEGORIES (use only these values):
{TAXONOMY}

SEVERITY LEVELS:
{SEVERITY}

Return ONLY a JSON object, no markdown fences, matching exactly:
{{
  "summary": {{
    "scores": {{"witness_control": 0-100, "question_form": 0-100, "sequencing": 0-100, "impeachment_discipline": 0-100}},
    "memo": "one cover paragraph, your voice, the headline of this performance",
    "try_next": ["2-3 concrete drills for the next session"]
  }},
  "annotations": [
    {{
      "turn_id": <int, an examiner turn unless the note is about handling the witness's answer>,
      "quote": "<exact verbatim substring of that turn's text the note attaches to, or null for whole-turn notes>",
      "category": "<one of the category values above>",
      "severity": "<critical|major|minor|praise>",
      "ai_note": "why this matters, specific to this exchange",
      "suggested_rewrite": "<the question as it should have been asked, or null for strategy/comment-only notes>"
    }}
  ],
  "patterns": [
    {{
      "label": "short_handle_like_leading_erosion",
      "turn_ids": [<turns where the pattern shows>],
      "note": "what keeps happening across these turns"
    }}
  ]
}}

Rules:
- quote must be copied verbatim from the named turn's text — no paraphrase, no ellipses.
- Annotate genuine issues and genuine strengths; a typical examination yields 5-15 annotations.
- Patterns require at least 2 turns; return [] if nothing recurs.
- Every annotation's category and severity must be values from the lists above."""


def _parse_llm_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in analyzer response: {raw[:200]}")
    return json.loads(text[start : end + 1])


def _resolve_span(quote: str | None, turn_text: str) -> Span | None:
    """Exact match first, then case-insensitive. Unresolved quotes keep
    the text with null offsets — the views render those comment-only."""
    if not quote:
        return None
    idx = turn_text.find(quote)
    if idx == -1:
        idx = turn_text.lower().find(quote.lower())
    if idx == -1:
        return Span(quote=quote, start=None, end=None)
    return Span(quote=turn_text[idx : idx + len(quote)], start=idx, end=idx + len(quote))


def analyze_transcript(
    transcript: CanonicalTranscript,
    client,
    reviewer: dict | None = None,
) -> Analysis:
    reviewer = reviewer or DEFAULT_REVIEWER
    prompt = _build_prompt(transcript, reviewer)

    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    llm = LLMAnalysis.model_validate(_parse_llm_json(response.content[0].text))

    turn_text = {t.turn_id: t.text for t in transcript.turns}
    annotations = []
    for a in llm.annotations:
        if a.turn_id not in turn_text:
            continue
        annotations.append(
            Annotation(
                annotation_id=f"ann_{uuid.uuid4().hex[:10]}",
                turn_id=a.turn_id,
                span=_resolve_span(a.quote, turn_text[a.turn_id]),
                category=a.category,
                severity=a.severity,
                ai_note=a.ai_note,
                suggested_rewrite=a.suggested_rewrite,
                reviewer_id=reviewer["reviewer_id"],
            )
        )

    patterns = [
        Pattern(
            pattern_id=f"pat_{uuid.uuid4().hex[:10]}",
            label=p.label,
            turn_ids=[tid for tid in p.turn_ids if tid in turn_text],
            note=p.note,
        )
        for p in llm.patterns
    ]

    return Analysis(
        analysis_id=f"ana_{uuid.uuid4().hex[:10]}",
        source=transcript.source,
        session_id=transcript.session_id,
        reviewer_id=reviewer["reviewer_id"],
        created_at=datetime.now(timezone.utc).isoformat(),
        summary=llm.summary,
        annotations=annotations,
        patterns=patterns,
    )
