#!/usr/bin/env python3
"""
Batch deposition simulator.

Usage:
  # Extract only (build personas, save to personas.json):
  python batch_sim.py --questions-zip attorney_questions.zip --extract-only

  # Full run (all witnesses, all 14 archetypes):
  python batch_sim.py --questions-zip attorney_questions.zip --out ./output

  # Subset of witnesses:
  python batch_sim.py --questions-zip attorney_questions.zip --witnesses "James Rausch" "Kate Neely"

  # Limit questions per session:
  python batch_sim.py --questions-zip attorney_questions.zip --max-questions 30

  # Enrich personas with case documents:
  python batch_sim.py --questions-zip attorney_questions.zip --docs case.pdf exhibit.pdf

  # Document-first mode: extract personas from a file and auto-generate questions:
  python batch_sim.py --input-file case.pdf --out ./output
  python batch_sim.py --input-file witness_statement.txt --out ./output --archetypes Neutral Combative
"""

import argparse
import copy
import json
import os
import random
import re
import sys
import time
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# Flush stdout immediately so log files stay current when running detached
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / "backend" / ".env")

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.state_engine import (
    encode_question, update_state, update_memory,
    detect_events, compute_scores,
)
from backend.prompt_builder import build_system_prompt, tone_label

# ── Constants ─────────────────────────────────────────────────────────────────

WITNESS_LIST = [
    "James Rausch", "Catherine Jackson", "Kevin Webb", "Steven Becker",
    "John Adams", "Kevin Vorderstrasse", "Cathy Stewart", "Stacy Chick",
    "Karen Harper", "Floyd Ratliff", "Kate Neely", "Victor Borelli",
    "Art Morelli", "Tiffany Kilper", "George Saffold", "Eileen Spaulding",
    "John Gillies", "Bonnie New", "Lynn Phillips", "Ronald Wickline",
    "Gail Tetzlaff", "George Pate", "Gregg Wolf", "Matthew Harbaugh",
    "Mark Trudeau", "Jane Williams", "Ginger Collier", "Lisa Cardetti",
    "Kevin Becker", "Erin Cox", "Susan Jolliff", "Karen Degen",
    "Christopher Clark", "Cheryl Herbold", "Michael Wessler", "Jeffrey Kilper",
    "Kirk Dumont", "Hugh O'Neill", "Todd Dean", "Eric Hichman",
    "Mark Pugh", "Terrence Terifay", "Stephen Nichols",
]

ARCHETYPES = {
    "Neutral":       {"C": 0.80, "K": 0.80, "A": 0.60, "V": 0.40, "R": 0.50, "P": 0.30},
    "Loquacious":    {"C": 0.60, "K": 0.60, "A": 0.70, "V": 0.95, "R": 0.30, "P": 0.40},
    "Combative":     {"C": 0.70, "K": 0.30, "A": 0.05, "V": 0.50, "R": 0.70, "P": 0.40},
    "Cooperative":   {"C": 0.80, "K": 0.90, "A": 0.95, "V": 0.50, "R": 0.30, "P": 0.30},
    "Forgetful":     {"C": 0.40, "K": 0.50, "A": 0.60, "V": 0.40, "R": 0.30, "P": 0.30},
    "Inventive":     {"C": 0.70, "K": 0.10, "A": 0.50, "V": 0.60, "R": 0.60, "P": 0.70},
    "Evasive":       {"C": 0.60, "K": 0.10, "A": 0.40, "V": 0.70, "R": 0.50, "P": 0.50},
    "Defensive":     {"C": 0.40, "K": 0.50, "A": 0.20, "V": 0.60, "R": 0.70, "P": 0.50},
    "Overconfident": {"C": 0.90, "K": 0.40, "A": 0.50, "V": 0.70, "R": 0.80, "P": 0.70},
    "Dogmatic":      {"C": 0.80, "K": 0.60, "A": 0.40, "V": 0.50, "R": 0.95, "P": 0.60},
    "Nervous":       {"C": 0.10, "K": 0.60, "A": 0.50, "V": 0.40, "R": 0.30, "P": 0.20},
    "Overprepared":  {"C": 0.90, "K": 0.70, "A": 0.60, "V": 0.50, "R": 0.70, "P": 0.95},
    "Pedantic":      {"C": 0.80, "K": 0.70, "A": 0.50, "V": 0.70, "R": 0.80, "P": 0.50},
    "Charming":      {"C": 0.90, "K": 0.60, "A": 0.90, "V": 0.70, "R": 0.40, "P": 0.80},
}


# ── Retry wrapper ─────────────────────────────────────────────────────────────

def api_call_with_retry(fn, max_retries=6):
    """Call fn(), retrying on rate-limit (429) errors with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            is_rate_limit = (
                "429" in str(e) or
                "rate_limit" in str(e).lower() or
                "too many requests" in str(e).lower() or
                "overloaded" in str(e).lower()
            )
            if is_rate_limit and attempt < max_retries - 1:
                wait = (2 ** attempt) + 1
                print(f"  Rate limited — waiting {wait}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
            else:
                raise


# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    """'Hugh O\'Neill' → 'hugh_oneill'"""
    s = name.lower()
    s = s.replace("'", "").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def parse_questions_from_text(text: str) -> list[str]:
    """Extract Q. lines from a deposition transcript file."""
    questions = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Q."):
            q = line[2:].strip()
            # Skip very short or procedural-only lines
            if len(q) > 15:
                questions.append(q)
    return questions


def parse_header(text: str) -> dict:
    """Extract Witness/Attorney/Source from file header."""
    info = {}
    for line in text.splitlines()[:6]:
        if line.startswith("Witness:"):
            info["witness_name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Attorney:"):
            info["attorney"] = line.split(":", 1)[1].strip()
        elif line.startswith("Source:"):
            info["source"] = line.split(":", 1)[1].strip()
    return info


def sample_questions(questions: list[str], max_q: int | None) -> list[str]:
    """
    Evenly sample up to max_q questions across the full list,
    always including the first 5 (foundational intro questions).
    Pass max_q=None to use all questions.
    """
    if max_q is None or len(questions) <= max_q:
        return questions
    intro = questions[:5]
    rest = questions[5:]
    need = max_q - len(intro)
    if need <= 0:
        return intro[:max_q]
    step = len(rest) / need
    sampled = [rest[int(i * step)] for i in range(need)]
    return intro + sampled


def load_questions_for_witness(zip_path: str, witness_name: str) -> tuple[list[str], dict]:
    """
    Load and combine all depo files for a witness from the zip.
    Returns (questions, header_info).
    """
    slug = slugify(witness_name)
    all_questions = []
    header_info = {}

    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist()
                 if not n.startswith("__MACOSX") and n.endswith(".txt")]

        # Find files matching this witness slug
        matched = []
        for n in names:
            basename = Path(n).stem  # e.g. "james_rausch_depo1"
            # strip trailing _depo\d+ suffix for matching
            base_slug = re.sub(r"_depo\d+$", "", basename)
            if base_slug == slug:
                matched.append(n)

        matched.sort()  # depo1 before depo2

        for name in matched:
            text = zf.read(name).decode("utf-8", errors="replace")
            if not header_info:
                header_info = parse_header(text)
            all_questions.extend(parse_questions_from_text(text))

    return all_questions, header_info


def build_persona_from_questions(
    witness_name: str,
    questions: list[str],
    header_info: dict,
    doc_context: str,
    client: anthropic.Anthropic,
) -> dict:
    """Use Claude to build a witness persona from deposition questions + optional doc context."""

    q_sample = questions[:80]  # send first 80 questions as context
    q_text = "\n".join(f"Q. {q}" for q in q_sample)

    attorney = header_info.get("attorney", "unknown attorney")
    source = header_info.get("source", "")

    doc_section = f"\n\nCase document excerpts:\n{doc_context[:3000]}" if doc_context else ""

    prompt = (
        f"You are analyzing a deposition of {witness_name} examined by {attorney} "
        f"(source: {source}).\n\n"
        f"Based on the following attorney questions asked of this witness, "
        f"build a detailed witness persona. Infer their role, organization, "
        f"what they likely know, what they might hide, and what topics are sensitive.\n\n"
        f"Attorney questions (sample):\n{q_text}"
        f"{doc_section}\n\n"
        f"Return a JSON object with fields: name, role, organization, background (string), "
        f"statement (2-3 paragraph narrative), key_points (array of strings), "
        f"known_facts (string), hidden_facts (string), claims (array of "
        f"{{facet, text, confidence 0-1}}), "
        f"sensitive_topics (array of {{topic, sensitivity 0-1, basis}})."
    )

    response = api_call_with_retry(lambda: client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=(
            "Build a realistic legal witness persona from deposition context. "
            "Every claim must be grounded in the questions asked. "
            "Return only valid JSON, no markdown fences."
        ),
        messages=[{"role": "user", "content": prompt}],
    ))

    text = response.content[0].text
    persona = {}
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            persona = json.loads(text[start:end])
    except (json.JSONDecodeError, ValueError):
        pass

    persona.setdefault("name", witness_name)
    persona.setdefault("role", "Witness")
    persona.setdefault("organization", "Unknown")
    persona.setdefault("background", "")
    persona.setdefault("statement", "")
    persona.setdefault("key_points", [])
    persona.setdefault("known_facts", "")
    persona.setdefault("hidden_facts", "")
    persona.setdefault("claims", [])
    persona.setdefault("sensitive_topics", [])
    persona["name"] = witness_name  # always use canonical name
    return persona


def load_segments_from_file(file_path: str) -> list[dict]:
    """Read a PDF or text file and return segmented chunks."""
    from backend.document_processor import ingest_files
    p = Path(file_path)
    file_bytes = p.read_bytes()
    segments, _ = ingest_files([{
        "filename": p.name,
        "bytes": file_bytes,
        "content_type": "application/pdf" if p.suffix.lower() == ".pdf" else "text/plain",
    }])
    return segments


def generate_questions_for_persona(
    persona: dict,
    segments: list[dict],
    client: anthropic.Anthropic,
    n: int = 40,
) -> list[str]:
    """Use Claude to generate deposition questions tailored to this persona."""
    # Pull the most relevant segments for context (up to ~3000 chars)
    doc_context = ""
    for seg in segments[:10]:
        doc_context += seg["text"][:300] + "\n"

    known = persona.get("known_facts", "")
    hidden = persona.get("hidden_facts", "")
    sensitive = ", ".join(
        t["topic"] for t in persona.get("sensitive_topics", [])
    )
    key_points = "\n".join(f"- {kp}" for kp in persona.get("key_points", [])[:8])

    prompt = (
        f"You are a skilled litigator preparing to depose {persona['name']}, "
        f"a {persona.get('role','witness')} at {persona.get('organization','unknown')}.\n\n"
        f"Key points about this witness:\n{key_points}\n\n"
        f"Known facts they will admit: {known}\n"
        f"Facts they are likely hiding: {hidden}\n"
        f"Sensitive topics: {sensitive}\n\n"
        f"Relevant document excerpts:\n{doc_context[:2000]}\n\n"
        f"Generate exactly {n} sharp, varied deposition questions. Mix foundational "
        f"background questions, factual probes, leading pressure questions, and "
        f"questions targeting the sensitive topics and hidden facts. "
        f"Return one question per line, no numbering, no preamble."
    )

    response = api_call_with_retry(lambda: client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=(
            "You are a litigator. Generate realistic, varied deposition questions. "
            "Return only the questions, one per line, no extra text."
        ),
        messages=[{"role": "user", "content": prompt}],
    ))

    lines = response.content[0].text.strip().splitlines()
    questions = [ln.strip() for ln in lines if len(ln.strip()) > 10]
    return questions[:n]


def load_witnesses_from_document(
    file_path: str,
    client: anthropic.Anthropic,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Full document-first pipeline:
      1. Ingest file → segments
      2. Extract witness candidates
      3. Build a full persona for each candidate
    Returns (personas, segments, candidates).
    """
    from backend.persona_builder import extract_candidates, build_persona
    print(f"  Reading file: {file_path}")
    segments = load_segments_from_file(file_path)
    print(f"  Segmented into {len(segments)} chunks")

    print("  Extracting witness candidates…")
    candidates = extract_candidates(segments)
    print(f"  Found {len(candidates)} candidate(s): "
          f"{', '.join(c.get('name','?') for c in candidates)}")

    personas = []
    for i, candidate in enumerate(candidates, 1):
        name = candidate.get("name", f"Witness {i}")
        print(f"  [{i}/{len(candidates)}] Building persona for {name}…")
        try:
            persona = build_persona(candidate, segments)
            persona["name"] = name  # ensure canonical name
            personas.append(persona)
            print(f"    → {persona.get('role','?')} at {persona.get('organization','?')}")
        except Exception as e:
            print(f"    ERROR: {e}")

    return personas, segments, candidates


def make_session(persona: dict, archetype_state: dict) -> dict:
    """Create a fresh session dict for one archetype run."""
    state_0 = copy.deepcopy(archetype_state)
    memory = {}
    for topic_data in persona.get("sensitive_topics", []):
        topic = topic_data.get("topic", "")
        if topic:
            memory[topic] = {
                "rho": 1.0,
                "sigma": topic_data.get("sensitivity", 0.5),
                "hit_count": 0,
                "last_hit_turn": 0,
                "basis": topic_data.get("basis", ""),
            }
    return {
        "persona": persona,
        "mode": "cross_examination",
        "state_0": copy.deepcopy(state_0),
        "state": copy.deepcopy(state_0),
        "memory": memory,
        "turn": 0,
        "messages": [],
        "trajectory": [copy.deepcopy(state_0)],
        "scores_trajectory": [compute_scores(state_0)],
    }


def run_archetype(
    persona: dict,
    archetype_name: str,
    archetype_state: dict,
    questions: list[str],
    client: anthropic.Anthropic,
    verbose: bool = True,
) -> dict:
    """
    Run one full deposition simulation.
    Returns dict with transcript, per-turn deltas, and events.
    """
    session = make_session(persona, archetype_state)
    turns = []

    label = f"  [{archetype_name}]"
    if verbose:
        print(f"{label} Starting — {len(questions)} questions")

    for i, question in enumerate(questions):
        # 1. Encode question
        encoding = encode_question(question, session)

        # 2. Update state
        prev_state = copy.deepcopy(session["state"])
        new_state = update_state(
            session["state"], session["state_0"], encoding, session["turn"]
        )

        # 3. Update memory
        new_memory = update_memory(
            session["memory"], encoding["hit_topics"], encoding["pressure"], session["turn"]
        )

        # 4. Detect events
        events = detect_events(new_state, prev_state, encoding, question)

        # 5. Build prompt
        system_prompt = build_system_prompt(session, new_state, new_memory, encoding, events)

        # 6. Build message history (last 12 exchanges)
        history = []
        for msg in session["messages"][-24:]:
            history.append({"role": msg["role"], "content": msg["content"]})
        history.append({"role": "user", "content": question})

        # 7. Call Claude
        response = api_call_with_retry(lambda: client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=system_prompt,
            messages=history,
        ))
        reply = response.content[0].text

        # 8. Compute delta + scores
        state_delta = {k: round(new_state[k] - prev_state[k], 4) for k in ["C", "K", "A", "V", "R", "P"]}
        scores = compute_scores(new_state)
        tone = tone_label(new_state)

        turn_record = {
            "turn": i + 1,
            "question": question,
            "reply": reply,
            "state": copy.deepcopy(new_state),
            "state_delta": state_delta,
            "scores": scores,
            "encoding": encoding,
            "events": events,
            "tone": tone,
        }
        turns.append(turn_record)

        # 9. Update session
        session["messages"].append({"role": "user", "content": question})
        session["messages"].append({
            "role": "assistant", "content": reply,
            "encoding": encoding, "state_delta": state_delta, "scores": scores,
        })
        session["state"] = new_state
        session["memory"] = new_memory
        session["turn"] += 1
        session["trajectory"].append(copy.deepcopy(new_state))
        session["scores_trajectory"].append(scores)

        event_labels = [e["label"] for e in events]
        if verbose and event_labels:
            print(f"{label}   turn {i+1}: {', '.join(event_labels)}")

    if verbose:
        print(f"{label} Done — final state C={session['state']['C']:.2f} A={session['state']['A']:.2f}")

    return {
        "witness": persona["name"],
        "archetype": archetype_name,
        "initial_state": archetype_state,
        "final_state": session["state"],
        "turns": turns,
        "trajectory": session["trajectory"],
        "scores_trajectory": session["scores_trajectory"],
    }


def write_transcript(result: dict, out_path: Path):
    """Write a human-readable transcript file."""
    lines = []
    lines.append(f"WITNESS: {result['witness']}")
    lines.append(f"ARCHETYPE: {result['archetype']}")
    lines.append(f"INITIAL STATE: {result['initial_state']}")
    lines.append(f"FINAL STATE:   {result['final_state']}")
    lines.append("=" * 70)
    lines.append("")

    for t in result["turns"]:
        lines.append(f"[Turn {t['turn']}]")
        lines.append(f"Q: {t['question']}")
        lines.append(f"A: {t['reply']}")

        # State deltas
        delta_parts = []
        for dim, val in t["state_delta"].items():
            if abs(val) >= 0.01:
                arrow = "▲" if val > 0 else "▼"
                delta_parts.append(f"{dim}{arrow}{abs(val):.3f}")
        if delta_parts:
            lines.append(f"   Δ: {' '.join(delta_parts)}")

        # Events
        for ev in t["events"]:
            lines.append(f"   ⚡ {ev['label']} — {ev['detail']}")

        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_deltas_json(result: dict, out_path: Path):
    """Write a compact JSON of all deltas and events."""
    rows = []
    for t in result["turns"]:
        row = {
            "turn": t["turn"],
            "question_snippet": t["question"][:80],
            "state_delta": t["state_delta"],
            "state": t["state"],
            "scores": t["scores"],
            "events": [{"label": e["label"], "detail": e["detail"]} for e in t["events"]],
            "tone": t["tone"],
            "pressure": t["encoding"]["pressure"],
            "question_type": t["encoding"]["question_type"],
        }
        rows.append(row)
    out_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────

def print_question_manifest(zip_path: str, witnesses: list[str], max_questions: int):
    """
    Print a manifest showing exactly which questions are assigned to each witness.
    Called before simulation starts so it's always clear what will run.
    """
    print("\n" + "=" * 70)
    print("QUESTION MANIFEST — questions assigned to each witness")
    print("=" * 70)
    missing = []
    for witness_name in witnesses:
        questions_all, header_info = load_questions_for_witness(zip_path, witness_name)
        if not questions_all:
            missing.append(witness_name)
            print(f"\n  {witness_name}")
            print(f"    ⚠  NO QUESTION FILE FOUND (slug: {slugify(witness_name)})")
            continue

        sampled = sample_questions(questions_all, max_questions)
        attorney = header_info.get("attorney", "unknown")
        source = header_info.get("source", "")
        print(f"\n  {witness_name}")
        print(f"    Attorney : {attorney}")
        if source:
            print(f"    Source   : {source}")
        print(f"    Questions: {len(questions_all)} total → {len(sampled)} will be used")
        for j, q in enumerate(sampled[:5], 1):
            preview = q[:90] + "…" if len(q) > 90 else q
            print(f"      {j}. {preview}")
        if len(sampled) > 5:
            print(f"      … and {len(sampled) - 5} more")

    print("\n" + "=" * 70)
    if missing:
        print(f"WARNING: {len(missing)} witness(es) have no question files: {missing}")
    print(f"Total: {len(witnesses) - len(missing)} witnesses with questions")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Batch deposition simulator")

    # ── Input mode (mutually exclusive) ──────────────────────────────────────
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--questions-zip", help="Path to attorney_questions.zip (deposition transcript mode)")
    input_group.add_argument("--input-file", help="Path to any PDF or text file (document-first mode: auto-extracts personas and generates questions)")

    parser.add_argument("--docs", nargs="+", default=[], help="Optional extra case document paths (PDF/txt) for persona enrichment")
    parser.add_argument("--out", default="./output", help="Output directory")
    parser.add_argument("--extract-only", action="store_true", help="Only build personas, skip simulation")
    parser.add_argument("--preview", action="store_true", help="Show question manifest per witness and exit (zip mode only)")
    parser.add_argument("--witnesses", nargs="+", default=[], help="Subset of witness names to run")
    parser.add_argument("--sample", type=int, default=None, help="Randomly sample N witnesses from the full list (ignored if --witnesses is set)")
    parser.add_argument("--archetypes", nargs="+", default=[], help="Subset of archetypes to run (default: all 14)")
    parser.add_argument("--max-questions", type=int, default=None, help="Max questions per session (default: all questions)")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-turn output")
    parser.add_argument("--workers", type=int, default=1, help="Number of witnesses to simulate in parallel (default: 1)")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_path = out_dir / "checkpoint.json"
    personas_path = out_dir / "personas.json"

    # Load checkpoint (completed runs)
    completed = set()
    if checkpoint_path.exists():
        completed = set(json.loads(checkpoint_path.read_text()))
        print(f"Resuming: {len(completed)} runs already completed.")

    checkpoint_lock = threading.Lock()

    # Anthropic client
    client = anthropic.Anthropic()

    # Determine archetype list
    archetype_names = args.archetypes if args.archetypes else list(ARCHETYPES.keys())
    archetypes = {k: ARCHETYPES[k] for k in archetype_names if k in ARCHETYPES}

    # ── DOCUMENT-FIRST MODE ───────────────────────────────────────────────────
    if args.input_file:
        print(f"\n{'='*70}")
        print(f" Document-first mode: {args.input_file}")
        print(f"{'='*70}\n")

        all_personas = {}
        # Load existing personas if resuming
        if personas_path.exists():
            print(f"Loading existing personas from {personas_path}")
            all_personas = {p["name"]: p for p in json.loads(personas_path.read_text())}

        # Extract personas from the uploaded document if not already done
        if not all_personas:
            personas_list, segments, _ = load_witnesses_from_document(args.input_file, client)
            all_personas = {p["name"]: p for p in personas_list}
            personas_path.write_text(json.dumps(list(all_personas.values()), indent=2))
            print(f"\nPersonas saved to {personas_path}")
        else:
            # Still need segments for question generation
            segments = load_segments_from_file(args.input_file)

        if not all_personas:
            print("No personas could be extracted from the document. Exiting.")
            return

        if args.extract_only:
            print("\nExtract-only mode. Done.")
            return

        # Filter to requested witnesses if specified
        if args.witnesses:
            missing = [w for w in args.witnesses if w not in all_personas]
            if missing:
                print(f"WARNING: these witnesses were not found in document: {missing}")
            witnesses = [w for w in args.witnesses if w in all_personas]
        else:
            witnesses = list(all_personas.keys())

        # ── Phase 2 (doc mode): Generate questions + run simulations ─────────
        # Pre-generate questions for each witness (cache to avoid re-generating on resume)
        questions_cache_path = out_dir / "generated_questions.json"
        questions_cache: dict[str, list[str]] = {}
        if questions_cache_path.exists():
            questions_cache = json.loads(questions_cache_path.read_text())

        total_runs = len(witnesses) * len(archetypes)
        run_idx = 0
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting simulation: "
              f"{len(witnesses)} witnesses × {len(archetypes)} archetypes = {total_runs} runs")

        for witness_name in witnesses:
            persona = all_personas[witness_name]

            # Generate or load cached questions
            if witness_name not in questions_cache:
                n_questions = args.max_questions or 50
                print(f"\n  Generating {n_questions} questions for {witness_name}…")
                try:
                    qs = generate_questions_for_persona(persona, segments, client, n=n_questions)
                    questions_cache[witness_name] = qs
                    questions_cache_path.write_text(json.dumps(questions_cache, indent=2))
                    print(f"  Generated {len(qs)} questions")
                except Exception as e:
                    print(f"  ERROR generating questions for {witness_name}: {e}")
                    continue

            questions = questions_cache[witness_name][:args.max_questions]

            witness_dir = out_dir / slugify(witness_name)
            witness_dir.mkdir(exist_ok=True)

            print(f"\n{'='*60}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] WITNESS: {witness_name}  "
                  f"({len(questions)} questions, {len(archetypes)} archetypes)")
            print(f"{'='*60}")

            for archetype_name, archetype_state in archetypes.items():
                run_idx += 1
                run_key = f"{slugify(witness_name)}::{archetype_name}"

                if run_key in completed:
                    print(f"  [{archetype_name}] Already done, skipping.")
                    continue

                print(f"  [{run_idx}/{total_runs}] {archetype_name}...")

                try:
                    result = run_archetype(
                        persona, archetype_name, archetype_state,
                        questions, client,
                        verbose=not args.quiet,
                    )
                except Exception as e:
                    print(f"  ERROR in {archetype_name} for {witness_name}: {e}")
                    continue

                transcript_path = witness_dir / f"{archetype_name.lower()}_transcript.txt"
                deltas_path = witness_dir / f"{archetype_name.lower()}_deltas.json"
                write_transcript(result, transcript_path)
                write_deltas_json(result, deltas_path)

                completed.add(run_key)
                checkpoint_path.write_text(json.dumps(list(completed)))
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] ✓ {archetype_name} saved "
                      f"({len(completed)}/{total_runs} total complete)")

            # Per-witness summary (only if any archetypes completed)
            summary = {"witness": witness_name, "archetypes": {}}
            for archetype_name in archetypes:
                dp = witness_dir / f"{archetype_name.lower()}_deltas.json"
                if dp.exists():
                    turns = json.loads(dp.read_text())
                    events_all = [e for t in turns for e in t["events"]]
                    summary["archetypes"][archetype_name] = {
                        "event_count": len(events_all),
                        "events": events_all,
                        "final_state": turns[-1]["state"] if turns else {},
                        "final_scores": turns[-1]["scores"] if turns else {},
                    }
            if summary["archetypes"]:
                (witness_dir / "summary.json").write_text(json.dumps(summary, indent=2))

        print(f"\n\nAll done. Output in: {out_dir.resolve()}")
        return

    # ── ZIP / DEPOSITION MODE (existing behaviour) ────────────────────────────

    # Determine witness list
    if args.witnesses:
        witnesses = args.witnesses
    elif args.sample:
        witnesses = random.sample(WITNESS_LIST, min(args.sample, len(WITNESS_LIST)))
        print(f"Randomly sampled {len(witnesses)} witnesses: {', '.join(witnesses)}")
    else:
        witnesses = WITNESS_LIST

    # Always print the question manifest so it's clear which questions belong to whom
    print_question_manifest(args.questions_zip, witnesses, args.max_questions)
    if args.preview:
        return

    # Load optional doc context
    doc_context = ""
    for doc_path in args.docs:
        try:
            p = Path(doc_path)
            if p.suffix.lower() == ".pdf":
                import pymupdf as fitz
                with fitz.open(str(p)) as doc:
                    for page in doc:
                        doc_context += page.get_text() + "\n"
                        if len(doc_context) > 8000:
                            break
            else:
                doc_context += p.read_text(errors="replace")[:4000]
        except Exception as e:
            print(f"Warning: could not read {doc_path}: {e}")

    # ── Phase 1: Load / build personas ───────────────────────────────────────

    all_personas = {}
    if personas_path.exists():
        print(f"Loading existing personas from {personas_path}")
        all_personas = {p["name"]: p for p in json.loads(personas_path.read_text())}

    for witness_name in witnesses:
        if witness_name in all_personas:
            continue

        print(f"\nBuilding persona: {witness_name}")
        questions_all, header_info = load_questions_for_witness(args.questions_zip, witness_name)

        if not questions_all:
            print(f"  WARNING: no question file found for {witness_name} (slug: {slugify(witness_name)})")
            continue

        print(f"  Loaded {len(questions_all)} questions from deposition file(s)")

        try:
            persona = build_persona_from_questions(
                witness_name, questions_all, header_info, doc_context, client
            )
            all_personas[witness_name] = persona
            print(f"  Persona built: {persona.get('role','?')} at {persona.get('organization','?')}")
        except Exception as e:
            print(f"  ERROR building persona for {witness_name}: {e}")

    # Save personas
    personas_path.write_text(json.dumps(list(all_personas.values()), indent=2))
    print(f"\nPersonas saved to {personas_path}")

    if args.extract_only:
        print("\nExtract-only mode. Done.")
        return

    # ── Phase 2: Run simulations ──────────────────────────────────────────────

    total_runs = len(witnesses) * len(archetypes)
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting simulation: "
          f"{len(witnesses)} witnesses × {len(archetypes)} archetypes = {total_runs} runs "
          f"({args.workers} worker(s))")

    def run_witness(witness_name: str):
        persona = all_personas.get(witness_name)
        if not persona:
            print(f"Skipping {witness_name} — no persona built.")
            return

        questions_all, _ = load_questions_for_witness(args.questions_zip, witness_name)
        if not questions_all:
            print(f"Skipping {witness_name} — no questions found.")
            return

        questions = sample_questions(questions_all, args.max_questions)
        witness_dir = out_dir / slugify(witness_name)
        witness_dir.mkdir(exist_ok=True)

        print(f"\n{'='*60}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] WITNESS: {witness_name}  "
              f"({len(questions)} questions, {len(archetypes)} archetypes)")
        print(f"{'='*60}")

        for archetype_name, archetype_state in archetypes.items():
            run_key = f"{slugify(witness_name)}::{archetype_name}"

            with checkpoint_lock:
                if run_key in completed:
                    print(f"  [{witness_name} / {archetype_name}] Already done, skipping.")
                    continue

            print(f"  [{witness_name}] {archetype_name}...")

            try:
                result = run_archetype(
                    persona, archetype_name, archetype_state,
                    questions, client,
                    verbose=not args.quiet,
                )
            except Exception as e:
                print(f"  ERROR in {archetype_name} for {witness_name}: {e}")
                continue

            transcript_path = witness_dir / f"{archetype_name.lower()}_transcript.txt"
            deltas_path = witness_dir / f"{archetype_name.lower()}_deltas.json"
            write_transcript(result, transcript_path)
            write_deltas_json(result, deltas_path)

            with checkpoint_lock:
                completed.add(run_key)
                checkpoint_path.write_text(json.dumps(list(completed)))
            print(f"  [{datetime.now().strftime('%H:%M:%S')}] ✓ {witness_name}/{archetype_name} "
                  f"({len(completed)}/{total_runs} total complete)")

        summary = {"witness": witness_name, "archetypes": {}}
        for archetype_name in archetypes:
            dp = witness_dir / f"{archetype_name.lower()}_deltas.json"
            if dp.exists():
                turns = json.loads(dp.read_text())
                events_all = [e for t in turns for e in t["events"]]
                summary["archetypes"][archetype_name] = {
                    "event_count": len(events_all),
                    "events": events_all,
                    "final_state": turns[-1]["state"] if turns else {},
                    "final_scores": turns[-1]["scores"] if turns else {},
                }
        if summary["archetypes"]:
            (witness_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_witness, w): w for w in witnesses}
        for future in as_completed(futures):
            w = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"ERROR: witness {w} failed: {e}")

    print(f"\n\nAll done. Output in: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
