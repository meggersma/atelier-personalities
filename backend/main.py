from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import uuid
import anthropic
import json
import copy
import os

try:
    from . import session_store
    from .document_processor import ingest_files, parse_pdf, parse_text
    from .persona_builder import extract_candidates, build_persona, index_segments_in_pinecone, rank_segments_by_relevance
    from .pinecone_store import pinecone_enabled
    from .state_engine import encode_question, update_state, update_memory, compute_scores, detect_events
    from .prompt_builder import build_system_prompt, tone_label
    from .realtime_auth import create_ephemeral_token, build_voice_persona_prompt, voice_for_persona
    from .analysis.adapters import session_to_transcript, parse_uploaded_transcript
    from .analysis.analyzer import analyze_transcript, distill_reviewer, REVIEWERS
except ImportError:
    import session_store
    from document_processor import ingest_files, parse_pdf, parse_text
    from persona_builder import extract_candidates, build_persona, index_segments_in_pinecone, rank_segments_by_relevance
    from pinecone_store import pinecone_enabled
    from state_engine import encode_question, update_state, update_memory, compute_scores, detect_events
    from prompt_builder import build_system_prompt, tone_label
    from realtime_auth import create_ephemeral_token, build_voice_persona_prompt, voice_for_persona
    from analysis.adapters import session_to_transcript, parse_uploaded_transcript
    from analysis.analyzer import analyze_transcript, distill_reviewer, REVIEWERS

app = FastAPI(title="Witness Simulator API")

_cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

_anthropic_client = None


def get_client():
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client


# ── Pydantic models ──────────────────────────────────────────────────────────

class ExtractCandidatesRequest(BaseModel):
    segment_ids: List[str] = []
    segments: Optional[List[Dict[str, Any]]] = None
    supplemental_info: Optional[str] = ""


class BuildPersonaRequest(BaseModel):
    candidate: Dict[str, Any]
    support_segment_ids: List[str] = []
    support_segments: Optional[List[Dict[str, Any]]] = None
    supplemental_info: Optional[str] = ""
    mode: Optional[str] = "cross_examination"


class CreateSessionRequest(BaseModel):
    persona_id: Optional[str] = None
    persona: Optional[Dict[str, Any]] = None
    personality_state: Dict[str, float]  # {C, K, A, V, R, P}
    memory_overrides: Optional[List[Dict[str, Any]]] = []


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    session: Optional[Dict[str, Any]] = None
    message: str


class SuggestedQuestionsRequest(BaseModel):
    session_id: Optional[str] = None
    session: Optional[Dict[str, Any]] = None


class RealtimeSessionRequest(BaseModel):
    session_id: Optional[str] = None
    session: Optional[Dict[str, Any]] = None
    voice: Optional[str] = None


class VoiceInstructionsRequest(BaseModel):
    session_id: Optional[str] = None
    session: Optional[Dict[str, Any]] = None


class AnalysisRequest(BaseModel):
    session_id: Optional[str] = None
    session: Optional[Dict[str, Any]] = None
    reviewer_id: Optional[str] = None
    reviewer: Optional[Dict[str, Any]] = None  # custom profile, client-supplied


class BuildReviewerRequest(BaseModel):
    name: str
    materials: str


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/ingest")
async def ingest_endpoint(files: List[UploadFile] = File(...)):
    """Ingest uploaded files and return segments."""
    file_dicts = []
    for f in files:
        content = await f.read()
        file_dicts.append({
            "filename": f.filename,
            "bytes": content,
            "content_type": f.content_type or ""
        })

    try:
        segments, documents = ingest_files(file_dicts)
        pinecone_indexed = False
        if pinecone_enabled():
            pinecone_indexed = index_segments_in_pinecone(segments)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    for seg in segments:
        session_store.segments_set(seg["id"], seg)

    return {
        "segments": segments,
        "documents": documents,
        "count": len(segments),
        "pinecone_indexed": pinecone_indexed,
    }


@app.post("/api/extract-candidates")
def extract_candidates_endpoint(req: ExtractCandidatesRequest):
    """Extract witness candidates from specified segments."""
    segments = list(req.segments or [])
    if not segments:
        for sid in req.segment_ids:
            seg = session_store.segments_get(sid)
            if seg:
                segments.append(seg)

    if not segments:
        all_segs = session_store.segments_all()
        segments = list(all_segs.values())[:50]

    segments = [s for s in segments if "libmupdf.dylib" not in s.get("text", "") and "Library not loaded" not in s.get("text", "")]

    try:
        candidates = extract_candidates(segments, req.supplemental_info or "")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"candidates": candidates}


@app.post("/api/build-persona")
def build_persona_endpoint(req: BuildPersonaRequest):
    """Build a detailed persona for a candidate."""
    support_segments = list(req.support_segments or [])
    if not support_segments:
        for sid in req.support_segment_ids:
            seg = session_store.segments_get(sid)
            if seg:
                support_segments.append(seg)

    if not support_segments:
        all_segs = session_store.segments_all()
        support_segments = list(all_segs.values())

    persona = build_persona(
        req.candidate,
        support_segments,
        req.supplemental_info or "",
        req.mode or "cross_examination"
    )

    session_store.personas_set(persona["persona_id"], persona)
    return {"persona": persona}


@app.post("/api/session")
def create_session(req: CreateSessionRequest):
    """Create a new examination session."""
    persona = req.persona
    if not persona and req.persona_id:
        persona = session_store.personas_get(req.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    state_0 = {
        "C": req.personality_state.get("C", 0.7),
        "K": req.personality_state.get("K", 0.7),
        "A": req.personality_state.get("A", 0.6),
        "V": req.personality_state.get("V", 0.4),
        "R": req.personality_state.get("R", 0.5),
        "P": req.personality_state.get("P", 0.6),
    }

    # Build memory from persona's sensitive topics + any overrides
    memory = {}

    # Add sensitive topics from persona
    for topic_data in persona.get("sensitive_topics", []):
        topic = topic_data.get("topic", "")
        if topic:
            memory[topic] = {
                "rho": 1.0,  # recall quality starts at max
                "sigma": topic_data.get("sensitivity", 0.5),  # sensitivity weight
                "hit_count": 0,
                "last_hit_turn": 0,
                "basis": topic_data.get("basis", "")
            }

    # Apply memory overrides
    for override in (req.memory_overrides or []):
        topic = override.get("topic", "")
        if topic:
            if topic in memory:
                memory[topic].update({
                    "sigma": override.get("sensitivity", memory[topic]["sigma"]),
                })
                if "selective" in override:
                    memory[topic]["selective"] = override["selective"]
            else:
                memory[topic] = {
                    "rho": 1.0,
                    "sigma": override.get("sensitivity", 0.5),
                    "hit_count": 0,
                    "last_hit_turn": 0,
                    "selective": override.get("selective", False)
                }

    session_id = str(uuid.uuid4())
    session = {
        "session_id": session_id,
        "persona_id": req.persona_id,
        "persona": persona,
        "mode": persona.get("mode", "cross_examination"),
        "state_0": copy.deepcopy(state_0),
        "state": copy.deepcopy(state_0),
        "memory": memory,
        "turn": 0,
        "messages": [],
        "trajectory": [copy.deepcopy(state_0)],
        "scores_trajectory": [compute_scores(state_0)],
    }

    session_store.set(session_id, session)
    return {
        "session_id": session_id,
        "session": session,
        "state": state_0,
        "memory": memory,
        "scores": compute_scores(state_0)
    }


@app.post("/api/chat")
def chat_endpoint(req: ChatRequest):
    """Send a message in an examination session."""
    session = copy.deepcopy(req.session) if req.session else None
    if not session and req.session_id:
        session = session_store.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 1. Encode question
    encoding = encode_question(req.message, session)

    # 2. Update state
    prev_state = copy.deepcopy(session["state"])
    new_state = update_state(
        session["state"],
        session["state_0"],
        encoding,
        session["turn"]
    )

    # 3. Update memory
    new_memory = update_memory(
        session["memory"],
        encoding["hit_topics"],
        encoding["pressure"],
        session["turn"]
    )

    # 4. Compute scores
    scores = compute_scores(new_state)

    # 4b. Detect events and tone
    events = detect_events(new_state, prev_state, encoding, req.message)
    current_tone = tone_label(new_state)

    # 5. Build system prompt
    system_prompt = build_system_prompt(session, new_state, new_memory, encoding, events)

    # 6. Build messages history (last 12 turns)
    history_messages = []
    for msg in session["messages"][-24:]:  # 12 exchanges = 24 messages
        history_messages.append({
            "role": msg["role"],
            "content": msg["content"]
        })

    # Add current user message
    history_messages.append({
        "role": "user",
        "content": req.message
    })

    # 7. Call Claude
    client = get_client()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=history_messages
    )

    reply_text = response.content[0].text

    # 8. Compute state delta
    state_delta = {
        k: round(new_state[k] - prev_state[k], 4)
        for k in ["C", "K", "A", "V", "R", "P"]
    }

    # 9. Update session
    session["messages"].append({"role": "user", "content": req.message})
    session["messages"].append({
        "role": "assistant",
        "content": reply_text,
        "encoding": encoding,
        "state_delta": state_delta,
        "scores": scores
    })
    session["state"] = new_state
    session["memory"] = new_memory
    session["turn"] += 1
    session["trajectory"].append(copy.deepcopy(new_state))
    session["scores_trajectory"].append(scores)

    if req.session_id:
        session_store.set(req.session_id, session)

    voice_instructions = build_voice_persona_prompt(session["persona"], new_state)

    return {
        "reply": reply_text,
        "session": session,
        "state": new_state,
        "scores": scores,
        "encoding": encoding,
        "state_delta": state_delta,
        "turn": session["turn"],
        "events": events,
        "tone": current_tone,
        "voice_instructions": voice_instructions,
    }


@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    """Get session state."""
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id,
        "persona_id": session["persona_id"],
        "state": session["state"],
        "state_0": session["state_0"],
        "memory": session["memory"],
        "turn": session["turn"],
        "messages": session["messages"],
        "scores": compute_scores(session["state"])
    }


@app.get("/api/session/{session_id}/trajectory")
def get_trajectory(session_id: str):
    """Get state trajectory for the session."""
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "trajectory": session.get("trajectory", []),
        "scores_trajectory": session.get("scores_trajectory", [])
    }


@app.delete("/api/session/{session_id}")
def delete_session(session_id: str):
    """Delete a session."""
    session_store.delete(session_id)
    return {"status": "deleted"}


@app.get("/api/personas")
def get_personas():
    """Get all built personas."""
    all_personas = session_store.personas_all()
    return {"personas": list(all_personas.values())}


@app.post("/api/realtime/session")
async def create_realtime_session(req: RealtimeSessionRequest):
    """Mint an ephemeral WebRTC token for gpt-realtime-2 voice sessions."""
    session = req.session
    if not session and req.session_id:
        session = session_store.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    persona = session["persona"]
    state = session["state"]

    try:
        result = await create_ephemeral_token(
            persona=persona,
            state=state,
            voice=req.voice,
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenAI Realtime API error: {e}")

    return result


@app.post("/api/realtime/voice-instructions")
def get_voice_instructions(req: VoiceInstructionsRequest):
    """Get updated voice delivery instructions for an active Realtime session."""
    session = req.session
    if not session and req.session_id:
        session = session_store.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    persona = session["persona"]
    state = session["state"]
    instructions = build_voice_persona_prompt(persona, state)
    suggested_voice = voice_for_persona(persona)

    return {
        "voice_instructions": instructions,
        "suggested_voice": suggested_voice,
        "tone": tone_label(state),
    }


@app.post("/api/session/{session_id}/suggested-questions")
def get_suggested_questions(session_id: str, req: Optional[SuggestedQuestionsRequest] = None):
    """Generate follow-up questions based on actual conversation so far."""
    session = copy.deepcopy(req.session) if req and req.session else None
    if not session:
        lookup_id = session_id if session_id != "__client__" else (req.session_id if req else None)
        session = session_store.get(lookup_id) if lookup_id else None
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    persona = session.get("persona", {})
    messages = session.get("messages", [])
    state = session.get("state", {})
    memory = session.get("memory", {})
    client = get_client()

    # Build a transcript of the last 6 exchanges for context
    recent = messages[-12:]
    transcript_lines = []
    for m in recent:
        role = "Attorney" if m["role"] == "user" else "Witness"
        transcript_lines.append(f"{role}: {m['content']}")
    transcript = "\n".join(transcript_lines)

    # Identify weak spots: topics hit but recall degraded, or untouched sensitive topics
    weak_topics = []
    for topic, data in memory.items():
        rho = data.get("rho", 1.0)
        sigma = data.get("sigma", 0.5)
        hits = data.get("hit_count", 0)
        if hits == 0 and sigma >= 0.6:
            weak_topics.append(f"{topic} (not yet explored, high sensitivity)")
        elif hits > 0 and rho < 0.5:
            weak_topics.append(f"{topic} (recall degraded to {rho:.2f} after {hits} questions)")

    # Current psychological state summary
    state_summary = (
        f"Composure: {state.get('C', 0.7):.2f}, "
        f"Knowledge: {state.get('K', 0.7):.2f}, "
        f"Agreeableness: {state.get('A', 0.6):.2f}, "
        f"Rigidity: {state.get('R', 0.5):.2f}"
    )

    has_transcript = bool(transcript_lines)

    if has_transcript:
        user_content = (
            f"Witness: {persona.get('name', 'Unknown')}, {persona.get('role', '')} at {persona.get('organization', '')}\n\n"
            f"Current psychological state: {state_summary}\n\n"
            f"Conversation so far:\n{transcript}\n\n"
            f"Weak spots to exploit: {'; '.join(weak_topics) if weak_topics else 'none identified yet'}\n\n"
            "Generate 4 follow-up questions that directly build on what was just said. "
            "Each question should either press on an inconsistency just revealed, follow up a vague answer, "
            "or pivot to a sensitive topic the witness hasn't been cornered on yet. "
            "Do NOT repeat questions already asked. Return a JSON array of exactly 4 question strings."
        )
    else:
        user_content = (
            f"Witness: {persona.get('name', 'Unknown')}, {persona.get('role', '')} at {persona.get('organization', '')}\n"
            f"Known sensitive topics: {'; '.join(weak_topics) if weak_topics else 'none'}\n"
            f"Key claims: {'; '.join(c.get('text','') for c in persona.get('claims', [])[:4])}\n\n"
            "Generate 4 opening cross-examination questions. "
            "Return a JSON array of exactly 4 question strings."
        )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=(
            "You are a skilled trial attorney. Generate sharp, specific cross-examination questions. "
            "Questions must feel like natural follow-ups to what was just said, not generic. "
            "Return a JSON array of exactly 4 question strings. No explanation, just the array."
        ),
        messages=[{"role": "user", "content": user_content}]
    )

    response_text = response.content[0].text

    questions = []
    try:
        start = response_text.find("[")
        end = response_text.rfind("]") + 1
        if start >= 0 and end > start:
            questions = json.loads(response_text[start:end])
        else:
            questions = json.loads(response_text)
    except (json.JSONDecodeError, ValueError):
        # Fallback: split by newlines and clean up
        lines = [l.strip().lstrip("0123456789.-) ").strip() for l in response_text.split("\n") if l.strip()]
        questions = [l for l in lines if l and "?" in l][:4]

    return {"questions": questions[:4]}


def _resolve_reviewer(reviewer: Optional[Dict], reviewer_id: Optional[str]) -> Optional[Dict]:
    if reviewer:
        if not reviewer.get("emphasis") or not reviewer.get("reviewer_id"):
            raise HTTPException(status_code=400, detail="Custom reviewer needs reviewer_id and emphasis")
        return reviewer
    if reviewer_id:
        profile = REVIEWERS.get(reviewer_id)
        if not profile:
            raise HTTPException(status_code=400, detail=f"Unknown reviewer: {reviewer_id}")
        return profile
    return None


@app.post("/api/analysis")
def create_analysis(req: AnalysisRequest):
    """Run the retrospective analyzer on a completed session."""
    session = copy.deepcopy(req.session) if req.session else None
    if not session and req.session_id:
        session = session_store.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.get("messages"):
        raise HTTPException(status_code=400, detail="Session has no turns to analyze")

    reviewer = _resolve_reviewer(req.reviewer, req.reviewer_id)

    transcript = session_to_transcript(session)
    analysis = analyze_transcript(transcript, get_client(), reviewer)
    session_store.analyses_set(analysis.analysis_id, analysis.model_dump())
    return analysis.model_dump()


@app.post("/api/analysis/upload")
async def create_analysis_from_upload(
    file: UploadFile = File(...),
    witness_name: str = Form(""),
    mode: str = Form(""),
    case_context: str = Form(""),
    reviewer_id: str = Form(""),
    reviewer: str = Form(""),
):
    """Run the analyzer on an uploaded deposition/cross-examination transcript.

    `reviewer` is a JSON-encoded custom profile (multipart forms can't nest
    objects); built-in reviewers come through `reviewer_id`.
    """
    reviewer_profile = None
    if reviewer:
        try:
            reviewer_profile = json.loads(reviewer)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="reviewer must be a JSON object")
    reviewer_profile = _resolve_reviewer(reviewer_profile, reviewer_id or None)

    data = await file.read()
    filename = file.filename or "transcript.txt"
    try:
        if filename.lower().endswith(".pdf"):
            pages = parse_pdf(data, filename)
        else:
            pages = parse_text(data, filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")
    text = "\n".join(p["text"] for p in pages)
    if not text.strip():
        raise HTTPException(status_code=400, detail="No text could be extracted from the file")

    transcript = parse_uploaded_transcript(
        text,
        get_client(),
        witness_name=witness_name.strip() or None,
        mode=mode.strip() or None,
        case_context=case_context.strip() or None,
    )
    if len(transcript.turns) < 2:
        raise HTTPException(status_code=400, detail="Could not find Q&A turns in the uploaded transcript")

    analysis = analyze_transcript(transcript, get_client(), reviewer_profile)
    result = analysis.model_dump()
    # Uploads have no session for the client to snapshot turns from —
    # ship the parsed turns with the analysis.
    result["turns"] = [t.model_dump() for t in transcript.turns]
    result["witness_name"] = transcript.witness_name
    session_store.analyses_set(analysis.analysis_id, result)
    return result


@app.get("/api/reviewers")
def list_reviewers():
    # Generic reviewers lead; named partners follow alphabetically.
    leads = ["default_senior_litigator", "senior_arbitration_counsel"]
    ordered = [REVIEWERS[i] for i in leads if i in REVIEWERS] + sorted(
        (r for r in REVIEWERS.values() if r["reviewer_id"] not in leads),
        key=lambda r: r["name"],
    )
    return {"reviewers": [
        {"reviewer_id": r["reviewer_id"], "name": r["name"], "blurb": r.get("blurb", "")}
        for r in ordered
    ]}


@app.post("/api/reviewers/build")
def build_reviewer(req: BuildReviewerRequest):
    """Distill a custom reviewer profile from samples of a partner's feedback."""
    if not req.name.strip() or not req.materials.strip():
        raise HTTPException(status_code=400, detail="Name and feedback samples are required")
    try:
        return distill_reviewer(req.name.strip(), req.materials, get_client())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not distill reviewer: {e}")


@app.get("/api/analysis/{analysis_id}")
def get_analysis(analysis_id: str):
    analysis = session_store.analyses_get(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis


# ── Static frontend serving ──────────────────────────────────────────────────
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _frontend_dist.is_dir():
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = _frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_frontend_dist / "index.html")
