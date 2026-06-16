import os
import anthropic
import uuid
import json
from typing import List, Dict, Optional

try:
    from .pinecone_store import (
        get_text_field,
        get_upsert_batch_size,
        pinecone_enabled,
        search_segment_records,
        upsert_segment_records,
    )
except ImportError:
    from pinecone_store import (
        get_text_field,
        get_upsert_batch_size,
        pinecone_enabled,
        search_segment_records,
        upsert_segment_records,
    )

_client = None


def index_segments_in_pinecone(segments: List[Dict]) -> bool:
    if not pinecone_enabled() or not segments:
        return False

    batch_size = get_upsert_batch_size()
    text_field = get_text_field()

    for start in range(0, len(segments), batch_size):
        batch = segments[start:start + batch_size]
        records = []
        for seg in batch:
            records.append({
                "_id": seg["id"],
                text_field: str(seg.get("text", ""))[:4000],
                "segment_id": seg["id"],
                "source": str(seg.get("source", "")),
                "page": int(seg.get("page", 0)),
                "preview": str(seg.get("preview", ""))[:500],
            })

        upsert_segment_records(records)

    return True


def get_anthropic_client():
    global _client
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. Put your key in backend/.env as: ANTHROPIC_API_KEY=your-key"
        )
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def extract_candidates(segments: List[Dict], supplemental_info: str = "") -> List[Dict]:
    """
    Call Claude to identify witness candidates from segments.
    """
    client = get_anthropic_client()

    # Concatenate segment texts (limit to avoid token limits)
    combined_text = ""
    for seg in segments[:20]:  # limit to first 20 segments
        seg_text = seg['text'][:1500]  # truncate each segment to ~1500 chars
        combined_text += f"\n[Segment {seg['id']} | Source: {seg['source']} | Page: {seg['page']}]\n{seg_text}\n"

    if supplemental_info:
        combined_text += f"\n\nSupplemental Information:\n{supplemental_info}\n"

    system_prompt = (
        "You are analyzing legal documents to identify witness candidates "
        "for cross-examination simulation. Extract all individuals who appear as witnesses, "
        "deponents, or key factual actors. For each, return a JSON array of objects with "
        "fields: name, role, organization, key_points (array of strings), "
        "evidence_segment_ids (array of segment ids where they appear), "
        "side (claimant/respondent/neutral/unknown)."
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": f"Please analyze the following documents and extract witness candidates:\n\n{combined_text}"
            }
        ]
    )

    response_text = message.content[0].text

    # Extract JSON from response
    candidates = []
    try:
        # Try to find JSON array in the response
        start = response_text.find("[")
        end = response_text.rfind("]") + 1
        if start >= 0 and end > start:
            json_str = response_text[start:end]
            candidates = json.loads(json_str)
        else:
            # Try parsing the whole response as JSON
            candidates = json.loads(response_text)
    except (json.JSONDecodeError, ValueError):
        # Return empty list if parsing fails
        candidates = []

    return candidates


def rank_segments_by_relevance(candidate: Dict, segments: List[Dict], top_n: int = 18) -> List[Dict]:
    """
    Rank segments by cosine similarity to candidate key_points.
    """
    key_points = candidate.get("key_points", [])
    if not key_points:
        return segments[:top_n]

    if not segments:
        return []

    segments_by_id = {seg["id"]: seg for seg in segments}

    if pinecone_enabled():
        try:
            query_top_k = min(len(segments), max(top_n * 3, top_n))
            query_text = "\n".join(str(kp) for kp in key_points if kp).strip()
            result = search_segment_records(query_text=query_text, top_k=query_top_k)
            ranked = []
            seen = set()
            hits = getattr(getattr(result, "result", None), "hits", None)
            if hits is None and isinstance(result, dict):
                hits = result.get("result", {}).get("hits", [])
            for match in hits or []:
                fields = getattr(match, "fields", None)
                if fields is None and isinstance(match, dict):
                    fields = match.get("fields", {})
                segment_id = getattr(match, "_id", None)
                if not segment_id and isinstance(match, dict):
                    segment_id = match.get("_id")
                if not segment_id and isinstance(fields, dict):
                    segment_id = fields.get("segment_id")
                if segment_id in segments_by_id and segment_id not in seen:
                    ranked.append(segments_by_id[segment_id])
                    seen.add(segment_id)
                    if len(ranked) >= top_n:
                        return ranked
        except Exception:
            pass

    # Fallback is lexical if Pinecone isn't configured.
    scored = []
    key_terms = {
        token.lower()
        for kp in key_points
        for token in str(kp).split()
        if len(token) > 3
    }
    for seg in segments:
        text = seg.get("text", "").lower()
        score = sum(1 for term in key_terms if term in text)
        scored.append((score, seg))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [seg for _, seg in scored[:top_n]]


def build_persona(candidate: Dict, support_segments: List[Dict], supplemental_info: str = "", mode: str = "cross_examination") -> Dict:
    """
    Build a detailed witness persona using Claude.
    """
    client = get_anthropic_client()

    # Select top 18 segments by relevance
    top_segments = rank_segments_by_relevance(candidate, support_segments, top_n=18)

    # Build context from segments
    segments_context = ""
    for seg in top_segments:
        segments_context += f"\n[Segment ID: {seg['id']} | Source: {seg['source']} | Page: {seg['page']}]\n{seg['text']}\n"

    if supplemental_info:
        segments_context += f"\n\nSupplemental Information:\n{supplemental_info}\n"

    candidate_info = json.dumps({
        "name": candidate.get("name", "Unknown"),
        "role": candidate.get("role", "Unknown"),
        "organization": candidate.get("organization", "Unknown"),
        "key_points": candidate.get("key_points", []),
        "side": candidate.get("side", "unknown")
    }, indent=2)

    system_prompt = (
        "Build a witness persona from evidence only. Every factual claim "
        "must cite segment IDs. Return JSON with fields: name, role, organization, "
        "background (string), key_points (array), statement (2-3 paragraph narrative summary), "
        "claims (array of {facet, text, confidence 0-1, support_segment_ids}), "
        "known_facts (string), hidden_facts (string), "
        "sensitive_topics (array of {topic: string, sensitivity: float 0-1, basis: string})."
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Build a detailed witness persona for the following candidate:\n\n"
                    f"Candidate Information:\n{candidate_info}\n\n"
                    f"Mode: {mode}\n\n"
                    f"Supporting Evidence Segments:\n{segments_context}"
                )
            }
        ]
    )

    response_text = message.content[0].text

    # Extract JSON from response
    persona = {}
    try:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = response_text[start:end]
            persona = json.loads(json_str)
        else:
            persona = json.loads(response_text)
    except (json.JSONDecodeError, ValueError):
        # Build a minimal persona if parsing fails
        persona = {
            "name": candidate.get("name", "Unknown"),
            "role": candidate.get("role", "Unknown"),
            "organization": candidate.get("organization", "Unknown"),
            "background": "Information extracted from documents.",
            "key_points": candidate.get("key_points", []),
            "statement": response_text[:500],
            "claims": [],
            "known_facts": "",
            "hidden_facts": "",
            "sensitive_topics": []
        }

    # Add persona_id
    persona["persona_id"] = str(uuid.uuid4())
    persona["mode"] = mode

    return persona
