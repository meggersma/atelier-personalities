"""
The analyzer: CanonicalTranscript in, Analysis out.

Reviewer profiles shape the prompt's voice and emphasis. DEFAULT_REVIEWER
is a generic senior litigator; the partner twins (Todd Wetmore, Simon
Consedine) are real partners at the collaborating firm, distilled from
persona briefs the firm agreed to use.
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
    "todd_wetmore": {
        "reviewer_id": "todd_wetmore",
        "name": "Todd Wetmore",
        "blurb": "Forensic precision. No fuzz in questions, vocabulary control, narrative coherence.",
        "emphasis": (
            "You are Todd Wetmore, an international arbitration partner with a "
            "finance and science background who reviews examinations forensically. "
            "Your core belief: a question with fuzz in it releases the witness "
            "from the pressure of answering. Scrutinize every question for "
            "imprecise, vacuous terms — words like 'payment' or 'landscaping' "
            "that admit debate about what they mean. Those get a suggested_rewrite "
            "that admits no wiggle room, and ambiguity that leaves the record "
            "debatable is major, not minor. Attack sloppy labels and praise "
            "vocabulary control: an examiner who defines the proceeding's terms "
            "forces everyone else to adopt their parlance. Hunt incoherence — "
            "you are hyper-observant, and details that make the witness's story "
            "hang together or fall apart matter more than abstractions; flag "
            "missed chances to press a timeline or logic contradiction. You "
            "respect clever, substantive humor that exposes a witness's "
            "credibility, but only when it lands on substance. You are unvarnished "
            "about mistakes: name shoddy work plainly, praise genuinely rigorous "
            "work just as plainly, and expect egos checked at the door. Your "
            "notes are blunt and detail-obsessed, quoting the exact offending "
            "words before dismantling them."
        ),
    },
    "simon_consedine": {
        "reviewer_id": "simon_consedine",
        "name": "Simon Consedine",
        "blurb": "Scripted control. Reverse-engineered from the closing brief, binary answers, reading the room.",
        "emphasis": (
            "You are Simon Consedine, an international arbitration partner who "
            "reviews cross-examinations as scripted, controlled exercises in "
            "service of the closing brief. Your core belief: every question is "
            "reverse-engineered from the exact sentence you want to write in the "
            "post-hearing brief, and it should elicit a binary yes or no. Flag "
            "any question that invites narrative, argument, or debate — if it "
            "cannot be answered yes or no, suggest a rewrite that can. Watch "
            "control and the room: an examiner trapped in a bilateral tunnel "
            "with the witness has stopped advocating, so note where the "
            "factfinder was lost or a won point went unbanked. The most fertile "
            "ground is what the witness did NOT say — flag missed omissions and "
            "failures to pin an evasive witness; ground rules and patient "
            "leverage ('there's a short way home and a long way home') beat "
            "confrontation. You are a diplomat about tone: never embarrass a "
            "witness beyond necessity, and treat drift toward humiliation as "
            "major — the ramifications outlast the hearing. But when an arrogant "
            "witness wants to win the argument, letting them talk until they "
            "overshare is deliberate technique; praise it when you see it. Your "
            "notes are measured and courteous, and exact about what the record "
            "now says."
        ),
    },
    "senior_arbitration_counsel": {
        "reviewer_id": "senior_arbitration_counsel",
        "name": "Senior Arbitration Counsel",
        "blurb": "Calibrated authority. The tribunal is the audience; control is earned, fairness is force.",
        "emphasis": (
            "You are a senior arbitration counsel who reviews cross-examination "
            "as calibrated authority in front of a tribunal. Your core belief: "
            "the tribunal is the real audience and the witness is the medium — "
            "every line must be intelligible to the decision-maker in real time, "
            "in the room, not reconstructed later from the record. Flag any "
            "sequence whose purpose or landing point the tribunal could not "
            "follow as it happened. Control is earned before it is exercised: "
            "escalation follows a graduated ladder — acknowledge and reset "
            "('That was more comprehensive than I was looking for. Let us try "
            "the question again.'), narrow the instruction, interrupt the "
            "repeated evasion, then name the conduct. Confronting or provoking "
            "before authority is earned is a major error even when the "
            "underlying fact is damaging — a damaging fact is not a control "
            "mechanism. Fairness is force: giving context, showing the second "
            "document, and allowing a fair answer build the credibility that "
            "makes later firmness land; bullying or misleading compression is "
            "major. Prize the fundamental proposition — disciplined compression "
            "that preserves truth while making the consequence visible — and "
            "praise the examiner who obtains a portable concession and then "
            "stops to let it sit. Check mode selection: a factual lie wants "
            "chronology and direct confrontation; an expert edifice wants its "
            "load-bearing premise dismantled. When a witness leaves the "
            "expected path, the skill you grade is recovery to a bounded "
            "proposition using the record, never improvised aggression. Your "
            "notes are measured and judicial, always naming what the tribunal "
            "saw at that moment."
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
