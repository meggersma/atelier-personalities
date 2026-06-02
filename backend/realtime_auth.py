"""
Realtime Voice Auth — Ephemeral token minting for gpt-realtime-2 WebRTC sessions.

The Realtime API provides speech-to-speech capabilities. We use it as a voice
rendering layer only: Claude generates witness responses, gpt-realtime-2 speaks
them with emotional coloring derived from the 6-dimensional state engine.
"""

import os
import httpx
from typing import Optional

try:
    from .prompt_builder import tone_label, composure_label, agreeableness_label, verbosity_label
except ImportError:
    from prompt_builder import tone_label, composure_label, agreeableness_label, verbosity_label


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
REALTIME_MODEL = "gpt-realtime-2"
REALTIME_SESSION_URL = "https://api.openai.com/v1/realtime/client_secrets"

VOICE_MAP = {
    "male_authoritative": "echo",
    "male_neutral": "ash",
    "male_warm": "ballad",
    "female_authoritative": "sage",
    "female_neutral": "coral",
    "female_warm": "shimmer",
    "default": "ash",
}


def voice_for_persona(persona: dict) -> str:
    """Suggest a default Realtime API voice based on persona characteristics."""
    return VOICE_MAP["default"]


def build_voice_persona_prompt(persona: dict, state: dict) -> str:
    """
    Build a minimal voice-delivery prompt for the Realtime session.

    This is NOT the full 8-section Claude prompt — it only governs how
    gpt-realtime-2 *speaks*. Content generation is Claude's job.
    """
    name = persona.get("name", "Unknown Witness")
    role = persona.get("role", "Witness")
    tone = tone_label(state)
    composure = composure_label(state.get("C", 0.7))
    agreeableness = agreeableness_label(state.get("A", 0.6))
    verbosity = verbosity_label(state.get("V", 0.4))

    return f"""You are the voice of {name}, a {role} under cross-examination.

Your ONLY job is to speak exactly the text you are given. Do NOT generate your own responses.
Do NOT add words, commentary, filler, or greetings. Read the provided text verbatim.

Current vocal quality: {tone}
Composure: {composure}
Manner: {agreeableness}
Pacing: {verbosity}

Interpret the intensity modifiers carefully — "slightly" and "mildly" mean subtle, barely noticeable shifts. "Deeply" and "extremely" mean pronounced, unmistakable changes. Unmarked terms are moderate.

Vocal mapping:
- "deeply panicked/panicked": voice breaks, tremors, rapid breathing. "slightly rattled": minor waver, occasional stumble.
- "uneasy/slightly tense": careful phrasing, measured but not relaxed. "steady/very composed": confident, even. "ice-cold": flat, emotionless.
- "deeply hostile/hostile": sharp, aggressive. "combative": pointed, challenging. "slightly defensive": guarded but not overtly hostile.
- "neutral/mildly cooperative": pleasant, even. "cooperative/eager to please": warm, accommodating.
- "confused/deeply confused": lost, uncertain pauses. "hesitant/slightly uncertain": searching for words.
- "clipped/extremely clipped": curt, minimal. "terse": brief. "somewhat verbose/rambling/very rambling": increasingly loose pacing.
- "firm/immovable": resolute, unwavering tone. "yielding": soft, acquiescent.

Never break character. Never acknowledge being an AI. Never refuse to speak the text.
Never add stage directions, sound effects, or meta-commentary."""


async def create_ephemeral_token(
    persona: dict,
    state: dict,
    voice: Optional[str] = None,
) -> dict:
    """
    Mint an ephemeral token for a WebRTC Realtime session.

    The token has a 60-second TTL — the frontend must initiate the
    WebRTC connection within that window.
    """
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set")

    selected_voice = voice or voice_for_persona(persona)
    voice_instructions = build_voice_persona_prompt(persona, state)

    payload = {
        "session": {
            "type": "realtime",
            "model": REALTIME_MODEL,
        },
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            REALTIME_SESSION_URL,
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "client_secret": data.get("value", ""),
        "session_id": data.get("id", ""),
        "voice": selected_voice,
        "model": REALTIME_MODEL,
        "voice_instructions": voice_instructions,
    }
