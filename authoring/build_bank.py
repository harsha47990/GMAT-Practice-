"""Build (or extend) the encrypted question bank.

Usage:
    python -m authoring.build_bank                  # seed -> fresh bank
    python -m authoring.build_bank --merge          # add seed to existing bank
    python -m authoring.build_bank --from file.json # build from a JSON file

New items are validated and de-duplicated against the existing bank before
being encrypted into data/bank.dat.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.bank import (  # noqa: E402
    load_bank, save_bank, make_question, existing_fingerprints, fingerprint,
)
from authoring.validate_bank import validate_raw  # noqa: E402

SEED_PATH = Path(__file__).resolve().parent / "seed_questions.json"


def _next_ids(existing):
    """Return a counter of the highest used index per type."""
    counters = defaultdict(int)
    for q in existing:
        prefix, _, num = q.id.rpartition("_")
        if num.isdigit():
            counters[q.type] = max(counters[q.type], int(num))
    return counters


def add_items(raw_items, merge=True):
    """Validate + dedup raw items, assign ids, and write the bank.
    Returns (added_count, skipped_count)."""
    errors, warnings, _ = validate_raw(raw_items)
    for w in warnings:
        print("WARN:", w)
    if errors:
        for e in errors:
            print("ERROR:", e)
        raise SystemExit("Aborting: fix validation errors first.")

    existing = load_bank() if merge else []
    seen = existing_fingerprints(existing)
    counters = _next_ids(existing)

    added, skipped = [], 0
    for raw in raw_items:
        fp = fingerprint(raw)
        if fp in seen:
            skipped += 1
            continue
        seen.add(fp)
        counters[raw["type"]] += 1
        qid = f"{raw['type'].lower()}_{counters[raw['type']]:04d}"
        added.append(make_question(raw, qid))

    bank = existing + added
    save_bank(bank)
    return len(added), skipped, len(bank)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge", action="store_true", help="add to existing bank")
    ap.add_argument("--from", dest="src", default=str(SEED_PATH),
                    help="source JSON file (default: seed_questions.json)")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.exists():
        raise SystemExit(
            f"Source file not found: {src}\n"
            "The plaintext seed was removed after the encrypted bank was built. "
            "The bank already lives in data/bank.dat. To add more questions, use "
            "the AI generator (python -m authoring.generate_questions ...) or pass "
            "your own JSON with --from path\\to\\file.json."
        )

    raw = json.loads(src.read_text(encoding="utf-8"))
    added, skipped, total = add_items(raw, merge=args.merge)
    print(f"Added {added}, skipped {skipped} duplicate(s). Bank now holds {total} questions.")


if __name__ == "__main__":
    main()
