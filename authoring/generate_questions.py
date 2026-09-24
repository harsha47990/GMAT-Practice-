"""Dedup-aware AI question generation.

Reads the existing encrypted bank, shows the model the stems already present
(so it avoids duplicates), and generates fresh questions at requested types
and difficulty bands. New items are validated, de-duplicated, and merged into
the bank.

Usage:
    # Generate 10 hard Critical Reasoning questions
    python -m authoring.generate_questions --type CR --band 4 --count 10

    # Top up every type to ~100 questions, spread across bands 1-5
    python -m authoring.generate_questions --target 100

    # Preview only (write JSON, don't touch the bank)
    python -m authoring.generate_questions --type PS --band 3 --count 5 --preview out.json
"""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import TYPE_LABELS, BAND_LABELS, BAND_TO_B, PASSAGE_TYPES, SECTIONS  # noqa: E402

_TYPE_TO_SECTION = {t: name for name, cfg in SECTIONS.items() for t in cfg["types"]}
from models.providers import llm_call, extract_json  # noqa: E402
from models.global_config import GMAT_MODEL  # noqa: E402
from engine.bank import load_bank, filter_questions, fingerprint  # noqa: E402
from authoring.build_bank import add_items  # noqa: E402
from authoring.validate_bank import validate_raw  # noqa: E402


_SYSTEM = (
    "You are an expert GMAT item writer. You create original, high-quality, "
    "unambiguous GMAT-style questions with exactly one defensible correct "
    "answer and plausible distractors. You never copy real, published GMAT "
    "questions. You output only valid JSON when asked."
)

_DS_NOTE = (
    "This is Data Sufficiency. Put the question and BOTH numbered statements "
    "inside 'stem' (use \\n between them). 'options' MUST be exactly the five "
    "standard DS choices in order, and 'answer_index' selects the correct one:\n"
    '  0: "Statement (1) ALONE is sufficient, but (2) alone is not."\n'
    '  1: "Statement (2) ALONE is sufficient, but (1) alone is not."\n'
    '  2: "BOTH statements TOGETHER are sufficient, but NEITHER alone is."\n'
    '  3: "EACH statement ALONE is sufficient."\n'
    '  4: "Statements (1) and (2) TOGETHER are NOT sufficient."\n'
)


def _existing_stems(bank, qtype, limit=80):
    stems = [q.stem.replace("\n", " ")[:140] for q in filter_questions(bank, qtype=qtype)]
    return stems[-limit:]


def _prompt(qtype, band, count, existing_stems):
    label = TYPE_LABELS.get(qtype, qtype)
    band_label = BAND_LABELS.get(band, "Medium")
    b_value = BAND_TO_B[band]
    passage_note = ""
    if qtype in PASSAGE_TYPES:
        passage_note = (
            "Include a self-contained 'passage' (the stimulus/data/table described "
            "in text) that the question refers to.\n"
        )
    ds_note = _DS_NOTE if qtype == "DS" else ""

    avoid = "\n".join(f"- {s}" for s in existing_stems) or "(none yet)"

    return f"""Write {count} NEW {label} ({qtype}) questions at difficulty band \
{band} ({band_label}).

{ds_note}{passage_note}
Do NOT duplicate or lightly reword any of these EXISTING questions:
{avoid}

Requirements:
- Each question must be original and clearly distinct from the list above and from each other.
- Exactly one correct answer; 5 options unless the format requires otherwise.
- Difficulty must genuinely match band {band} ({band_label}).
- Provide a concise 'explanation' of why the answer is correct.
- Add 2-4 lowercase 'tags' describing the concept (e.g. "assumption", "work-rate").

Return ONLY a JSON array. Each element:
{{
  "section": "<Quantitative|Verbal|Data Insights>",
  "type": "{qtype}",
  "difficulty_band": {band},
  "difficulty": {b_value},
  "passage": "<text or empty string>",
  "stem": "<question text>",
  "options": ["...", "..."],
  "answer_index": <int, 0-based>,
  "explanation": "<why the answer is correct>",
  "tags": ["...", "..."],
  "est_time_sec": <int>
}}"""


def generate_batch(qtype, band, count, model=None):
    """Generate, validate, and dedup a batch. Returns a list of clean raw dicts."""
    model = model or GMAT_MODEL
    bank = load_bank()
    seen = {fingerprint(q) for q in bank}

    prompt = _prompt(qtype, band, count, _existing_stems(bank, qtype))
    raw_text = llm_call(model, _SYSTEM, prompt)
    try:
        items = extract_json(raw_text)
    except Exception as e:
        print(f"  ! Could not parse model output for {qtype} band {band}: {e}")
        return []
    if not isinstance(items, list):
        items = [items]

    # Drop items that collide with the bank or each other, then validate.
    clean = []
    for it in items:
        it["type"] = qtype
        it["section"] = _TYPE_TO_SECTION.get(qtype, it.get("section", "Verbal"))
        it["difficulty_band"] = band
        it["difficulty"] = BAND_TO_B[band]
        fp = fingerprint(it)
        if fp in seen:
            continue
        seen.add(fp)
        clean.append(it)

    errors, warnings, _ = validate_raw(clean)
    if errors:
        # Keep only items not implicated in an error index.
        bad = {int(e.split("[")[1].split("]")[0]) for e in errors if "item[" in e}
        clean = [it for i, it in enumerate(clean) if i not in bad]
    return clean


def _plan_targets(target_per_type):
    """Distribute a per-type target across the 5 difficulty bands."""
    base = target_per_type // 5
    return {b: base for b in (1, 2, 3, 4, 5)}


def _stamp():
    """Current time as DD-MM-YY HH:MM:SS (24-hour)."""
    return time.strftime("%d-%m-%y %H:%M:%S")


def _fmt_dur(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if m else f"{s}s"


def run_target(target_per_type, model=None, batch=10):
    bank = load_bank()
    counts = Counter((q.type, q.difficulty_band) for q in bank)
    plan = _plan_targets(target_per_type)
    total_added = 0
    start_all = time.time()
    for qtype in TYPE_LABELS:
        for band, want in plan.items():
            have = counts.get((qtype, band), 0)
            need = want - have
            stalls = 0                       # consecutive rounds that added nothing
            while need > 0:
                n = min(batch, need)
                print(f"[{_stamp()}] Generating {n} x {qtype} band {band} "
                      f"(have {have}/{want}) ...")
                t0 = time.time()
                items = generate_batch(qtype, band, n, model=model)
                dt = time.time() - t0
                added, skipped, total = 0, 0, None
                if items:
                    added, skipped, total = add_items(items, merge=True)

                if added == 0:
                    stalls += 1
                    print(f"  no new unique questions in {_fmt_dur(dt)} "
                          f"(stall {stalls}/3)")
                    if stalls >= 3:
                        print(f"  giving up on {qtype} band {band} at "
                              f"{have}/{want} (model out of unique items)")
                        break
                    continue

                stalls = 0
                elapsed = time.time() - start_all
                print(f"  +{added} added, {skipped} dup skipped (bank={total}) "
                      f"in {_fmt_dur(dt)}  |  total {total_added + added} added, "
                      f"elapsed {_fmt_dur(elapsed)}")
                total_added += added
                have += added
                need -= added        # count only what was actually added
    print(f"\n[{_stamp()}] Done. Added {total_added} questions in "
          f"{_fmt_dur(time.time() - start_all)}.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", dest="qtype", choices=list(TYPE_LABELS))
    ap.add_argument("--band", type=int, choices=[1, 2, 3, 4, 5])
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--target", type=int, help="top up every type to N questions")
    ap.add_argument("--model", default=None)
    ap.add_argument("--preview", help="write JSON here instead of updating the bank")
    args = ap.parse_args()

    if args.target:
        run_target(args.target, model=args.model)
        return

    if not (args.qtype and args.band):
        ap.error("provide --type and --band, or use --target")

    print(f"[{_stamp()}] Generating {args.count} x {args.qtype} band {args.band} ...")
    t0 = time.time()
    items = generate_batch(args.qtype, args.band, args.count, model=args.model)
    print(f"[{_stamp()}] Generated {len(items)} clean question(s) in "
          f"{_fmt_dur(time.time() - t0)}.")
    if args.preview:
        Path(args.preview).write_text(json.dumps(items, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        print(f"Wrote preview to {args.preview} (bank not modified).")
    elif items:
        added, skipped, total = add_items(items, merge=True)
        print(f"Added {added}, skipped {skipped} dup. Bank now holds {total}.")


if __name__ == "__main__":
    main()
