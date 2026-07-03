"""
The analyzer contract.

Everything upstream (live session adapter, uploaded-transcript adapter)
normalizes INTO CanonicalTranscript; everything downstream (dashboard,
Word/DOCX renderer, comparison view) renders OUT OF Analysis. Views must
never depend on analyzer internals — only on these models.

Wireframe reference: wireframes/analyzer-output-shape.html
"""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Canonical transcript (analyzer input) ──────────────────

class Speaker(str, Enum):
    EXAMINER = "examiner"
    WITNESS = "witness"
    OTHER = "other"  # colloquy, objections by counsel, court reporter notes


class Turn(BaseModel):
    turn_id: int
    speaker: Speaker
    text: str


class Enrichment(BaseModel):
    """Live-session extras. Absent for uploaded transcripts — every
    downstream consumer must treat these as nullable."""
    trajectory: Optional[list[dict[str, float]]] = None       # C/K/A/V/R/P per turn
    scores_trajectory: Optional[list[dict[str, float]]] = None  # witness behavior scores


class TranscriptSource(str, Enum):
    LIVE_SESSION = "live_session"
    UPLOADED = "uploaded"


class CanonicalTranscript(BaseModel):
    source: TranscriptSource
    session_id: Optional[str] = None
    witness_name: Optional[str] = None
    mode: Optional[str] = None  # cross_examination | deposition | direct
    case_context: Optional[str] = None
    turns: list[Turn]
    enrichment: Optional[Enrichment] = None


# ── Analysis (analyzer output) ──────────────────────────────

class Severity(str, Enum):
    CRITICAL = "critical"  # cost you the point
    MAJOR = "major"        # weakened the record
    MINOR = "minor"        # polish
    PRAISE = "praise"      # keep doing this


class Category(str, Enum):
    # Form — question construction (usually carries a suggested_rewrite)
    COMPOUND_QUESTION = "compound_question"
    VAGUE_QUESTION = "vague_question"
    ASSUMES_FACTS = "assumes_facts"
    CALLS_FOR_NARRATIVE = "calls_for_narrative"
    UNINTENDED_LEADING = "unintended_leading"
    # Strategy — judgment calls (often comment-only)
    ONE_QUESTION_TOO_MANY = "one_question_too_many"
    MISSED_IMPEACHMENT = "missed_impeachment"
    FAILURE_TO_PIN = "failure_to_pin"
    SEQUENCING_ERROR = "sequencing_error"
    NO_EXIT = "no_exit"
    # Control / style
    LOST_CONTROL = "lost_control"
    TONE_DRIFT = "tone_drift"
    TELEGRAPHING = "telegraphing"
    CONTROLLED_SEQUENCE = "controlled_sequence"  # praise
    # The record — mostly uploaded transcripts
    OBJECTION_DRAWN = "objection_drawn"
    OBJECTION_SUSTAINED = "objection_sustained"
    ANSWER_OVER_QUESTION = "answer_over_question"
    EXHIBIT_MISHANDLED = "exhibit_mishandled"


class Span(BaseModel):
    """The LLM supplies `quote`; the backend resolves offsets by string
    matching (LLMs are unreliable at raw character offsets). Unresolved
    spans (offsets None) render as comment-only, never dropped."""
    quote: str
    start: Optional[int] = None
    end: Optional[int] = None


class Annotation(BaseModel):
    annotation_id: str
    turn_id: int
    span: Optional[Span] = None
    category: Category
    severity: Severity
    ai_note: str
    suggested_rewrite: Optional[str] = None
    reviewer_id: str


class Pattern(BaseModel):
    pattern_id: str
    label: str                # short handle, e.g. "leading_erosion"
    turn_ids: list[int]
    note: str


class SummaryScores(BaseModel):
    """Examiner skill dimensions, 0-100. Distinct from the state engine's
    witness-behavior scores (consistency/evasion/realism/adversarial)."""
    witness_control: int = Field(ge=0, le=100)
    question_form: int = Field(ge=0, le=100)
    sequencing: int = Field(ge=0, le=100)
    impeachment_discipline: int = Field(ge=0, le=100)


class Summary(BaseModel):
    scores: SummaryScores
    memo: str                    # reviewer's cover paragraph (Word view header)
    try_next: list[str]          # 2-3 concrete drills for the next session


class Analysis(BaseModel):
    analysis_id: str
    source: TranscriptSource
    session_id: Optional[str] = None
    reviewer_id: str
    created_at: str
    summary: Summary
    annotations: list[Annotation]
    patterns: list[Pattern]


# ── What the LLM is asked to return (subset — ids/offsets added server-side) ──

class LLMAnnotation(BaseModel):
    turn_id: int
    quote: Optional[str] = None
    category: Category
    severity: Severity
    ai_note: str
    suggested_rewrite: Optional[str] = None


class LLMPattern(BaseModel):
    label: str
    turn_ids: list[int]
    note: str


class LLMAnalysis(BaseModel):
    summary: Summary
    annotations: list[LLMAnnotation]
    patterns: list[LLMPattern]
