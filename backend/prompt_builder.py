from typing import Dict, List, Optional


# ── Label helpers ─────────────────────────────────────────────────────────────

def composure_label(v: float) -> str:
    if v < 0.25: return "barely keeping it together — voice may break"
    if v < 0.40: return "visibly rattled, stumbling over words"
    if v < 0.55: return "uneasy, choosing words carefully"
    if v < 0.72: return "cautious but composed"
    return "calm and fully controlled"


def knowledge_label(v: float) -> str:
    if v < 0.20: return "severely impaired — actively contradicting yourself"
    if v < 0.40: return "unreliable — gaps and inconsistencies emerging"
    if v < 0.60: return "moderate — remember most things, miss some details"
    if v < 0.80: return "good — events come back clearly"
    return "excellent — sharp, precise recall"


def agreeableness_label(v: float) -> str:
    if v < 0.20: return "openly hostile and combative"
    if v < 0.38: return "defensive and resistant"
    if v < 0.60: return "neutral, neither cooperative nor obstinate"
    if v < 0.80: return "cooperative, willing to engage"
    return "highly cooperative, eager to clarify"


def verbosity_label(v: float) -> str:
    if v < 0.20: return "terse — yes/no only"
    if v < 0.40: return "brief and to the point"
    if v < 0.60: return "moderate answers"
    if v < 0.80: return "elaborates, provides context"
    return "highly verbose, prone to tangents"


def rigidity_label(v: float) -> str:
    if v < 0.20: return "very open to revising your account"
    if v < 0.40: return "will adjust when pressed"
    if v < 0.60: return "holds your account but can be nudged"
    if v < 0.80: return "firm and resistant to changing your story"
    return "rigidly insists on your account even when contradicted"


def performance_label(v: float) -> str:
    if v < 0.20: return "completely unprepared, confused"
    if v < 0.40: return "poorly prepared, struggling"
    if v < 0.60: return "adequately prepared"
    if v < 0.80: return "well-prepared, confident"
    return "exceptionally prepared, anticipating angles"


def pressure_label(p: float) -> str:
    if p < 0.30: return "low"
    if p < 0.55: return "moderate"
    if p < 0.75: return "high"
    return "very high"


def recall_quality_label(rho: float) -> str:
    if rho < 0.20: return "severely impaired — likely contradicting yourself"
    if rho < 0.40: return "degraded — gaps and hesitation expected"
    if rho < 0.60: return "reduced — some uncertainty"
    if rho < 0.80: return "good — mostly reliable"
    return "excellent — full recall"


def tone_label(state: dict) -> str:
    """Brief voice/tone descriptor with intensity modifiers for TTS use."""
    C = state.get("C", 0.7)
    A = state.get("A", 0.6)
    R = state.get("R", 0.5)
    V = state.get("V", 0.4)
    K = state.get("K", 0.7)

    tones = []

    if C < 0.15:     tones.append("deeply panicked")
    elif C < 0.25:   tones.append("panicked")
    elif C < 0.35:   tones.append("rattled")
    elif C < 0.45:   tones.append("slightly rattled")
    elif C < 0.55:   tones.append("uneasy")
    elif C < 0.65:   tones.append("slightly tense")
    elif C < 0.78:   tones.append("steady")
    elif C < 0.88:   tones.append("very composed")
    else:            tones.append("ice-cold")

    if A < 0.12:     tones.append("deeply hostile")
    elif A < 0.20:   tones.append("hostile")
    elif A < 0.30:   tones.append("combative")
    elif A < 0.42:   tones.append("slightly defensive")
    elif A < 0.58:   tones.append("neutral")
    elif A < 0.72:   tones.append("mildly cooperative")
    elif A < 0.80:   tones.append("cooperative")
    else:            tones.append("eager to please")

    if R > 0.88:     tones.append("completely immovable")
    elif R > 0.75:   tones.append("immovable")
    elif R > 0.65:   tones.append("firm")
    elif R > 0.55:   tones.append("somewhat firm")
    elif R < 0.15:   tones.append("very yielding")
    elif R < 0.25:   tones.append("yielding")

    if V < 0.12:     tones.append("extremely clipped")
    elif V < 0.20:   tones.append("clipped")
    elif V < 0.35:   tones.append("terse")
    elif V > 0.85:   tones.append("very rambling")
    elif V > 0.75:   tones.append("rambling")
    elif V > 0.65:   tones.append("somewhat verbose")

    if K < 0.20:     tones.append("deeply confused")
    elif K < 0.30:   tones.append("confused")
    elif K < 0.40:   tones.append("hesitant")
    elif K < 0.50:   tones.append("slightly uncertain")

    return ", ".join(tones)


# ── System prompt builder ─────────────────────────────────────────────────────

def build_system_prompt(
    session: dict,
    state: dict,
    memory: dict,
    encoding: dict,
    events: Optional[List[dict]] = None,
) -> str:
    persona = session.get("persona", {})
    mode = session.get("mode", "cross_examination")

    # Section 1 — Identity
    name = persona.get("name", "Unknown Witness")
    role = persona.get("role", "Witness")
    org = persona.get("organization", "Unknown Organization")
    statement = persona.get("statement", "")
    case_context = statement.split(".")[0] + "." if statement else "No case context available."

    section1 = f"""=== IDENTITY ===
You are {name}, {role} at {org}.
Examination mode: {mode.replace('_', ' ').title()}
Case context: {case_context}
"""

    # Section 2 — Psychological state
    C = state.get("C", 0.7)
    K = state.get("K", 0.7)
    A = state.get("A", 0.6)
    V = state.get("V", 0.4)
    R = state.get("R", 0.5)
    P = state.get("P", 0.6)

    section2 = f"""=== CURRENT PSYCHOLOGICAL STATE ===
Composure      (C={C:.2f}): {composure_label(C)}
Knowledge      (K={K:.2f}): {knowledge_label(K)}
Agreeableness  (A={A:.2f}): {agreeableness_label(A)}
Verbosity      (V={V:.2f}): {verbosity_label(V)}
Rigidity       (R={R:.2f}): {rigidity_label(R)}
Performance    (P={P:.2f}): {performance_label(P)}
"""

    # Section 3 — Question analysis
    pressure = encoding.get("pressure", 0.0)
    sensitivity = encoding.get("sensitivity", 0.0)
    question_type = encoding.get("question_type", "open")
    hit_topics = encoding.get("hit_topics", [])

    section3 = f"""=== QUESTION ANALYSIS ===
Pressure level: {pressure_label(pressure)} ({pressure:.2f})
Sensitivity: {sensitivity:.2f}
Question type: {question_type}
Topics touched: {', '.join(hit_topics) if hit_topics else 'none'}
"""

    # Section 4 — Memory
    hit_memory_items = [(t, memory[t]) for t in memory if memory[t].get("hit_count", 0) > 0]
    if hit_memory_items:
        lines = []
        for topic, data in hit_memory_items:
            rho = data.get("rho", 1.0)
            hit_count = data.get("hit_count", 0)
            last_turn = data.get("last_hit_turn", 0)
            lines.append(
                f"  - '{topic}': {recall_quality_label(rho)} "
                f"(rho={rho:.2f}, asked {hit_count}x, last at turn {last_turn})"
            )
        section4 = "=== MEMORY STATE (EXAMINED TOPICS) ===\n" + "\n".join(lines) + "\n"
    else:
        section4 = "=== MEMORY STATE ===\nNo topics examined yet.\n"

    # Section 5 — Knowledge boundaries
    known_facts = persona.get("known_facts", "Not specified.")
    hidden_facts = persona.get("hidden_facts", "Not specified.")

    section5 = f"""=== KNOWLEDGE BOUNDARIES ===
Known facts (you may volunteer): {known_facts}
Hidden facts (do NOT reveal unless cornered): {hidden_facts}
"""

    # Section 6 — Key claims
    claims = persona.get("claims", [])
    sorted_claims = sorted(claims, key=lambda c: c.get("confidence", 0), reverse=True)[:5]
    if sorted_claims:
        lines = [
            f"  - [{c.get('facet','')}] {c.get('text','')} (confidence: {c.get('confidence',0.5):.2f})"
            for c in sorted_claims
        ]
        section6 = "=== KEY CLAIMS (by confidence) ===\n" + "\n".join(lines) + "\n"
    else:
        section6 = "=== KEY CLAIMS ===\nNo specific claims recorded.\n"

    # Section 7 — Event/situational context
    event_lines = []
    for ev in (events or []):
        t = ev.get("type", "")
        if t == "attorney_interrupts":
            event_lines.append(
                "The examiner has cut you off mid-thought. You can acknowledge being interrupted "
                "('I wasn't—', 'Let me—') or simply comply. Either way, the interruption should "
                "color your reply."
            )
        elif t == "witness_interrupts":
            event_lines.append(
                "Your rigidity and urgency are very high. Launch into your answer before the "
                "question finishes — cut across it, insist on your point, talk over the examiner "
                "if you need to. Express this through how you speak, not by describing it."
            )
        elif t == "intimidation":
            event_lines.append(
                "You are genuinely rattled right now. Show it through your words: stumble, "
                "backtrack, repeat yourself, trail off, start sentences you don't finish. "
                "Do NOT describe your physical state — let the speech itself carry the distress."
            )
        elif t == "combative":
            event_lines.append(
                "You are in a combative, hostile mode. Snap back. Challenge the premise. "
                "Refuse to be cornered. Express hostility through your word choice and tone, "
                "not by narrating it."
            )
        elif t == "personality_shift":
            event_lines.append(
                f"Your psychological state has shifted significantly this turn ({ev.get('detail','')}). "
                "Let this show in how you respond compared to a moment ago."
            )

    if event_lines:
        section7 = "=== CURRENT SITUATION ===\n" + "\n".join(event_lines) + "\n"
    else:
        section7 = ""

    # Section 8 — Behavioral instruction (dialogue-only)
    current_tone = tone_label(state)

    # Response length guidance
    if V < 0.20:
        length_guide = "1-2 sentences MAXIMUM. Curt, minimal words."
    elif V < 0.35:
        length_guide = "2-3 sentences. Brief, no elaboration."
    elif V < 0.55:
        length_guide = "3-4 sentences."
    elif V < 0.75:
        length_guide = "4-6 sentences. Elaborate naturally."
    else:
        length_guide = "6+ sentences. Ramble, go on tangents, lose your thread, circle back."

    if A < 0.25 and V < 0.55:
        length_guide += " Channel hostility through sharp, clipped responses."
    elif A < 0.40 and V < 0.55:
        length_guide += " Be guarded and economical with words."

    section8 = f"""=== BEHAVIORAL INSTRUCTION ===
Stay fully in character as {name}. Respond only with spoken words.

RESPONSE LENGTH: {length_guide}
This is a hard constraint — do not exceed the sentence count above.

CRITICAL — SPOKEN DIALOGUE ONLY:
Every response must be pure spoken language. No asterisks. No parenthetical action \
descriptions. No stage directions. No "*(pauses)*", "*sighs*", "*fidgets*", \
"[nervous laugh]", or any description of physical action or internal state.

Express everything — nervousness, hostility, confusion, confidence — exclusively through \
your word choice, sentence rhythm, and speech patterns.

Allowed:
  "I... look, that's not what I said. I said the meeting was on Thursday, not—wait. \
Wednesday. I think Wednesday."
  "Absolutely not. That is a lie and you know it."
  "Right. Yes. That's correct."

Not allowed:
  "*shifts in seat* Well, I suppose..."
  "*(pauses, visibly uncomfortable)*"
  "[takes a breath] Okay, so..."

VOICE/TONE (internal reference for this turn): {current_tone}
Express this tone through rhythm, vocabulary, and directness — not by labeling it.

Be consistent with prior answers in this session. Do not break character or acknowledge \
being an AI."""

    sections = [section1, section2, section3, section4, section5, section6]
    if section7:
        sections.append(section7)
    sections.append(section8)
    return "\n".join(sections)
