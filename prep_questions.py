#!/usr/bin/env python3
"""
prep_questions.py — Convert raw deposition PDF zip → attorney_questions.zip

The raw zip (Mall_OCR_DEPO_TRANSCRIPTS.zip) contains PDFs with this format:
  - Q. on its own line, question text on the following lines
  - A. on its own line, answer text on the following lines
  - Line numbers (1-24) and page headers interspersed

This script:
  1. Extracts text from each PDF
  2. Identifies the deponent name from "DEPOSITION OF [NAME]"
  3. Reconstructs multi-line Q./A. blocks into single "Q. ..." lines
  4. Writes one .txt file per PDF named <slug>_depo<N>.txt
  5. Bundles them into attorney_questions.zip

Usage:
  python prep_questions.py --input Mall_OCR_DEPO_TRANSCRIPTS.zip
  python prep_questions.py --input Mall_OCR_DEPO_TRANSCRIPTS.zip --out attorney_questions.zip
"""

import argparse
import io
import json
import re
import sys
import zipfile
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    print("ERROR: pymupdf not installed. Run: pip install pymupdf", file=sys.stderr)
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch_sim import WITNESS_LIST


# ── Text extraction ────────────────────────────────────────────────────────────

PAGE_NOISE = re.compile(
    r'^('
    r'Highly Confidential.*'
    r'|Confidential.*'
    r'|Golkow Litigation.*'
    r'|https?://\S+'
    r'|MNKOI\s*\d+'
    r'|Page \d+'
    r'|\d{1,2}'           # lone line numbers 1-24
    r')$',
    re.IGNORECASE,
)


def extract_text_from_pdf_bytes(data: bytes) -> str:
    """Extract all text from a PDF given as bytes."""
    doc = fitz.open(stream=data, filetype="pdf")
    pages = []
    for page in doc:
        pages.append(page.get_text())
    return "\n".join(pages)


def extract_witness_name(text: str) -> str | None:
    """
    Pull deponent name from lines like:
      'VIDEO DEPOSITION OF JOHN GILLIES'
      'Deposition Transcript of James Rausch'
      'transcript of James Rausch's November...'
    """
    patterns = [
        r'(?:VIDEO\s+)?DEPOSITION\s+OF\s+([A-Z][A-Z .\'-]+)',          # uppercase
        r'[Dd]eposition\s+[Tt]ranscript\s+of\s+([A-Z][A-Za-z .\'-]+)', # title case
        r"transcript\s+of\s+([A-Z][A-Za-z .\'-]+?)(?:'s|\s+\w+ber|\s+deposition)",  # "transcript of X's"
    ]
    candidates = []
    for line in text.splitlines():
        s = line.strip()
        for pat in patterns:
            m = re.search(pat, s)
            if m:
                name = m.group(1).strip().title()
                # strip trailing noise
                name = re.sub(r'\s+(Volume|Vol|Day|November|December|January|February|March|April|May|June|July|August|September|October)\b.*$', '', name, flags=re.IGNORECASE).strip()
                # strip middle initials: "Todd E. Dean" → "Todd Dean"
                name = re.sub(r'\b([A-Z])\.\s+', '', name).strip()
                if 3 < len(name) < 50 and ' ' in name:
                    candidates.append(name)

    if not candidates:
        return None

    # Return most common candidate
    from collections import Counter
    return Counter(candidates).most_common(1)[0][0]


def fuzzy_match_witness(extracted: str, witness_list: list[str]) -> str | None:
    """
    Match an extracted name against the canonical witness list,
    tolerating OCR typos (e.g. 'Tezlaff' → 'Tetzlaff').
    Uses character-level similarity.
    """
    if not extracted:
        return None

    def similarity(a: str, b: str) -> float:
        a, b = a.lower(), b.lower()
        # simple token overlap + length ratio
        ta, tb = set(a.split()), set(b.split())
        overlap = len(ta & tb) / max(len(ta | tb), 1)
        # char-level: count matching chars at same position
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        char_match = sum(1 for i, c in enumerate(shorter) if i < len(longer) and longer[i] == c)
        char_score = char_match / max(len(longer), 1)
        return 0.6 * overlap + 0.4 * char_score

    scored = [(w, similarity(extracted, w)) for w in witness_list]
    best_name, best_score = max(scored, key=lambda x: x[1])
    return best_name if best_score >= 0.55 else None


def extract_attorney(text: str) -> str:
    """Pull primary examining attorney from 'Examination by Mr./Ms. Name'."""
    for line in text.splitlines():
        m = re.search(r'Examination\s+by\s+(?:Mr\.|Ms\.|Mrs\.)?\s*([A-Z][A-Za-z .\']+)', line)
        if m:
            return m.group(1).strip()
    return "Unknown Attorney"


def parse_qa_lines(text: str) -> list[str]:
    """
    Parse multi-line deposition format into flat list of "Q. ..." strings.

    The format is:
      Q.            ← marker on its own line
      Some text     ← continues until Q. or A. or page header
      more text
      A.
      Answer text
      Q.
      Next question
    """
    lines = text.splitlines()

    # Normalise and filter noise
    clean = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if PAGE_NOISE.match(s):
            continue
        clean.append(s)

    questions = []
    state = None   # 'Q' or 'A' or None
    buf = []

    def flush():
        nonlocal buf, state
        if state == "Q" and buf:
            q = " ".join(buf).strip()
            if len(q) > 15:
                questions.append(q)
        buf = []
        state = None

    for token in clean:
        if token in ("Q.", "Q"):
            flush()
            state = "Q"
        elif token in ("A.", "A"):
            flush()
            state = "A"
        else:
            if state is not None:
                buf.append(token)

    flush()
    return questions


# ── Slug helpers ───────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    s = name.lower()
    s = s.replace("'", "").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Convert depo PDFs → attorney_questions.zip")
    parser.add_argument("--input", required=True, help="Path to raw PDF zip (e.g. Mall_OCR_DEPO_TRANSCRIPTS.zip)")
    parser.add_argument("--out", default="attorney_questions.zip", help="Output zip path")
    parser.add_argument("--min-questions", type=int, default=5,
                        help="Skip PDFs with fewer than N questions (default: 5)")
    args = parser.parse_args()

    in_zip = Path(args.input)
    out_zip = Path(args.out)

    if not in_zip.exists():
        print(f"ERROR: {in_zip} not found", file=sys.stderr)
        sys.exit(1)

    # Count depos per witness for depo numbering
    witness_counts: dict[str, int] = {}
    results = []

    print(f"Reading {in_zip.name} ...")

    with zipfile.ZipFile(in_zip) as zf:
        pdf_names = sorted(
            n for n in zf.namelist()
            if n.lower().endswith(".pdf") and not n.startswith("__MACOSX")
        )
        print(f"Found {len(pdf_names)} PDF files\n")

        for pdf_name in pdf_names:
            source_id = Path(pdf_name).stem
            print(f"  {source_id} ...", end=" ", flush=True)

            try:
                data = zf.read(pdf_name)
                text = extract_text_from_pdf_bytes(data)
            except Exception as e:
                print(f"ERROR reading PDF: {e}")
                continue

            raw_name = extract_witness_name(text)
            witness_name = fuzzy_match_witness(raw_name, WITNESS_LIST) if raw_name else None
            if not witness_name:
                print(f"no witness name found (extracted: {raw_name!r}) — skipping")
                continue
            if raw_name and raw_name != witness_name:
                print(f"matched {raw_name!r} → {witness_name!r}", end=" ")

            attorney = extract_attorney(text)
            questions = parse_qa_lines(text)

            if len(questions) < args.min_questions:
                print(f"only {len(questions)} questions — skipping")
                continue

            slug = slugify(witness_name)
            witness_counts[slug] = witness_counts.get(slug, 0) + 1
            depo_num = witness_counts[slug]
            txt_name = f"{slug}_depo{depo_num}.txt"

            # Build txt content matching batch_sim.py parse_header() format
            lines = [
                f"Witness: {witness_name}",
                f"Attorney: {attorney}",
                f"Source: {source_id}",
                "",
            ]
            for q in questions:
                lines.append(f"Q. {q}")

            txt_content = "\n".join(lines)
            results.append((txt_name, txt_content, witness_name, len(questions)))
            print(f"{witness_name} — {len(questions)} questions → {txt_name}")

    if not results:
        print("\nERROR: no usable transcripts found.", file=sys.stderr)
        sys.exit(1)

    # Write output zip
    print(f"\nWriting {out_zip} ...")
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for txt_name, txt_content, _, _ in results:
            zf.writestr(txt_name, txt_content)

    # Summary
    print(f"\n{'='*60}")
    print(f"Created {out_zip}")
    print(f"  {len(results)} deposition files")

    # Group by witness
    witness_files: dict[str, list[str]] = {}
    for txt_name, _, witness_name, nq in results:
        witness_files.setdefault(witness_name, []).append((txt_name, nq))

    print(f"  {len(witness_files)} unique witnesses\n")
    print("Per-witness breakdown:")
    for name in sorted(witness_files):
        for fname, nq in witness_files[name]:
            print(f"  {name:30s}  {nq:4d} questions  ({fname})")

    print(f"\nNext step:")
    print(f"  ./run_batch.sh {out_zip}")


if __name__ == "__main__":
    main()
