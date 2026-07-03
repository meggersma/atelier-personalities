"""
On-ramps into the canonical transcript format.

Live sessions today; uploaded depositions next (a second adapter that
parses Q./A. court-reporter format lands here, producing the same
CanonicalTranscript with enrichment=None).
"""

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
