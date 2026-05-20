#!/usr/bin/env python3
"""
curate_questions.py — Filter deposition questions to ~300 substantive ones per witness.

Reads attorney_questions.zip, removes procedural/boilerplate/repetitive questions,
deduplicates near-identical questions, then evenly samples to a target count.

Usage:
  python curate_questions.py
  python curate_questions.py --max 300 --out attorney_questions_curated.zip
"""

import argparse
import re
import zipfile
from collections import defaultdict
from pathlib import Path

# ── Procedural / boilerplate patterns ─────────────────────────────────────────
# These are questions that appear in virtually every deposition and add no
# substantive value to the simulation (ground rules, identification, logistics).

PROCEDURAL_PATTERNS = [
    r"^(good morning|good afternoon|good evening|hi\b|hello\b)",
    r"(state (your|and spell) (your |full )?name)",
    r"(spell your (last |full )?name)",
    r"(under oath|took an oath|taking an oath)",
    r"(ever been deposed|deposition before|given a deposition|had your deposition taken)",
    r"(taking any medication|any medication|any reason (you|that would) (cannot|can't|prevent) you from)",
    r"(need a break|take a break|want a break|ask for a break)",
    r"(ground rules|basic rules|some rules|few rules|couple of rules|set of rules)",
    r"(court reporter|stenographer)",
    r"(answer verbally|verbal answers|verbal response|nods of the head|head shake)",
    r"(don't (understand|know what).{0,40}(let me know|ask|tell me))",
    r"(if you (need|want|require) a)",
    r"(where do you (currently |now )?(live|reside))",
    r"(home address|business address|residential address|mailing address)",
    r"(have you (ever )?testified|testified (at trial|in court|under oath|before))",
    r"^(okay\.?|alright\.?|correct\.?|right\.?|thank you\.?|yes\.?|no\.?|sure\.?|great\.?|good\.?)$",
    r"(is that (correct|right|fair to say|accurate))\??$",
    r"(currently (employed|work|working|married))\??$",
    r"(represented by counsel|your attorney|your lawyer)",
    r"(introduce (myself|ourselves))",
    r"(met (briefly|before|earlier|off the record|a moment ago|just a moment))",
    r"(can you hear (me )?okay|are you able to hear)",
    r"(how are you (doing|today))\??$",
    r"(thank you for being here|appreciate (you|your time))",
    r"(before we (begin|start|get started))",
    r"(mark(ed)? (this|it) as exhibit|hand you what.{0,20}(marked|exhibit))",
    r"(deposition notice|notice of deposition|subpoena)",
    r"(what is your (full |legal )?name)\??$",
    r"(understand (that )?you('re| are) here today)",
    r"(sworn testimony)",
    r"(finish (my |the )?question before)",
    r"(answer (only )?the question (that is |that's )?asked)",
    r"(give (me |us )?a verbal|audible response)",
    r"(don't talk (at the same time|over each other|simultaneously))",
    r"(your best recollection|your best memory|best of your (memory|recollection|ability))",
    r"(if you don't remember|if you don't recall|if you don't know)",
    r"(do you understand (the )?question|do you understand what i('m| am) asking)",
    r"(pause (before|to) answer|wait (before|to) answer)",
    r"(how long have you (lived|been at|resided))",
    r"source:\s*https?://",
    r"^\*redacted",
    r"\d{2}:\d{2}:\d{2}.*\d{2}:\d{2}:\d{2}",   # timestamp-heavy lines
]

PROCEDURAL_RE = re.compile(
    "|".join(PROCEDURAL_PATTERNS),
    re.IGNORECASE,
)


def is_procedural(q: str) -> bool:
    return bool(PROCEDURAL_RE.search(q))


def too_noisy(q: str) -> bool:
    """Reject questions that are mostly OCR noise / timestamps / source URLs."""
    # Has 2+ embedded timestamps
    if len(re.findall(r'\d{2}:\d{2}:\d{2}', q)) >= 2:
        return True
    # Mostly uppercase noise
    words = q.split()
    if len(words) < 4:
        return True
    return False


def token_jaccard(a: str, b: str) -> float:
    ta = set(re.findall(r'\w+', a.lower()))
    tb = set(re.findall(r'\w+', b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def deduplicate(questions: list[str], threshold: float = 0.72) -> list[str]:
    """
    Remove near-duplicate questions.
    Only compares each question against the most recent 60 kept questions
    for efficiency on large lists.
    """
    kept: list[str] = []
    kept_tokensets: list[set] = []

    for q in questions:
        tokens = set(re.findall(r'\w+', q.lower()))
        if len(tokens) < 5:
            kept.append(q)
            kept_tokensets.append(tokens)
            continue

        window = kept_tokensets[-60:]
        is_dup = any(
            len(tokens & prev) / len(tokens | prev) >= threshold
            for prev in window
            if tokens | prev
        )
        if not is_dup:
            kept.append(q)
            kept_tokensets.append(tokens)

    return kept


def even_sample(questions: list[str], n: int) -> list[str]:
    """Evenly sample n questions, always keeping the first 5 (introductory)."""
    if len(questions) <= n:
        return questions
    intro = questions[:5]
    rest = questions[5:]
    need = n - len(intro)
    if need <= 0:
        return intro[:n]
    step = len(rest) / need
    sampled = [rest[int(i * step)] for i in range(need)]
    return intro + sampled


def parse_header(text: str) -> dict:
    info = {}
    for line in text.splitlines()[:6]:
        if line.startswith("Witness:"):
            info["witness"] = line.split(":", 1)[1].strip()
        elif line.startswith("Attorney:"):
            info["attorney"] = line.split(":", 1)[1].strip()
        elif line.startswith("Source:"):
            info["source"] = line.split(":", 1)[1].strip()
    return info


def parse_questions(text: str) -> list[str]:
    questions = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Q."):
            q = line[2:].strip()
            if len(q) > 20:
                questions.append(q)
    return questions


def main():
    parser = argparse.ArgumentParser(description="Curate deposition questions to ~N per witness")
    parser.add_argument("--input", default="attorney_questions.zip")
    parser.add_argument("--out", default="attorney_questions_curated.zip")
    parser.add_argument("--max", type=int, default=300, help="Target questions per witness (default: 300)")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"ERROR: {in_path} not found")
        return

    # ── Read all files, group by witness slug ─────────────────────────────────
    witness_files: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with zipfile.ZipFile(in_path) as zf:
        names = sorted(
            n for n in zf.namelist()
            if not n.startswith("__MACOSX") and n.endswith(".txt")
        )
        for name in names:
            stem = Path(name).stem
            slug = re.sub(r"_depo\d+$", "", stem)
            text = zf.read(name).decode("utf-8", errors="replace")
            witness_files[slug].append((name, text))

    print(f"\nCurating questions for {len(witness_files)} witnesses  (target: {args.max} each)")
    print(f"{'='*70}")
    print(f"  {'Witness':<30} {'Raw':>5}  {'−Proc':>6}  {'−Dup':>6}  {'Final':>6}")
    print(f"  {'-'*30} {'-'*5}  {'-'*6}  {'-'*6}  {'-'*6}")

    results: dict[str, tuple[dict, list[str]]] = {}

    for slug, file_list in sorted(witness_files.items()):
        all_questions: list[str] = []
        header: dict = {}

        for _fname, text in file_list:
            if not header:
                header = parse_header(text)
            all_questions.extend(parse_questions(text))

        raw_count = len(all_questions)
        witness_name = header.get("witness", slug)

        # Step 1: Remove procedural / noisy questions
        filtered = [
            q for q in all_questions
            if not is_procedural(q) and not too_noisy(q)
        ]
        proc_count = len(filtered)

        # Step 2: Deduplicate
        deduped = deduplicate(filtered)
        dup_count = len(deduped)

        # Step 3: Sample to target
        final = even_sample(deduped, args.max)

        results[slug] = (header, final)
        print(f"  {witness_name:<30} {raw_count:>5}  {proc_count:>6}  {dup_count:>6}  {len(final):>6}")

    # ── Write curated zip ──────────────────────────────────────────────────────
    out_path = Path(args.out)
    print(f"\nWriting {out_path} ...")
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf_out:
        for slug, (header, questions) in results.items():
            fname = f"{slug}_depo1.txt"
            lines = [
                f"Witness: {header.get('witness', slug)}",
                f"Attorney: {header.get('attorney', 'Unknown Attorney')}",
                f"Source: {header.get('source', '')}",
                "",
            ]
            for q in questions:
                lines.append(f"Q. {q}")
            zf_out.writestr(fname, "\n".join(lines))

    total_questions = sum(len(qs) for _, qs in results.values())
    print(f"\n{'='*70}")
    print(f"Done. {len(results)} witnesses, {total_questions:,} total questions")
    print(f"Saved to: {out_path}")
    print(f"\nNext steps:")
    print(f"  1. Preview:  ./run_batch.sh {out_path} ./output_curated --preview")
    print(f"  2. Run:      ./run_batch.sh {out_path} ./output_curated")


if __name__ == "__main__":
    main()
