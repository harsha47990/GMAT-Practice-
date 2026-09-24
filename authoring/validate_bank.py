"""Validate a set of raw question dicts (or the built bank).

Checks: required fields present, >=2 options, answer_index in range,
non-empty stem, DS/passage sanity, and duplicate fingerprints.
Returns (errors, warnings, stats).
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import TYPE_LABELS  # noqa: E402
from engine.bank import fingerprint, normalize_text  # noqa: E402


def validate_raw(items: list[dict]):
    errors, warnings = [], []
    seen = {}
    stats = {"total": len(items), "by_type": Counter(), "by_band": Counter()}

    for i, q in enumerate(items):
        where = f"item[{i}]"
        for req in ("section", "type", "stem", "options", "answer_index"):
            if req not in q or q[req] in (None, "", []):
                errors.append(f"{where}: missing required field '{req}'")
        if errors and errors[-1].startswith(where):
            continue

        if q["type"] not in TYPE_LABELS:
            warnings.append(f"{where}: unknown type '{q['type']}'")

        opts = q.get("options", [])
        if len(opts) < 2:
            errors.append(f"{where}: needs >= 2 options")
        if len(set(normalize_text(str(o)) for o in opts)) != len(opts):
            warnings.append(f"{where}: duplicate option text")

        ai = q.get("answer_index")
        if not isinstance(ai, int) or not (0 <= ai < len(opts)):
            errors.append(f"{where}: answer_index {ai} out of range")

        if len(normalize_text(q.get("stem", ""))) < 5:
            warnings.append(f"{where}: suspiciously short stem")

        fp = fingerprint(q)
        if fp in seen:
            errors.append(f"{where}: duplicate of item[{seen[fp]}]")
        else:
            seen[fp] = i

        stats["by_type"][q.get("type")] += 1
        stats["by_band"][q.get("difficulty_band")] += 1

    return errors, warnings, stats


def print_report(items: list[dict]):
    errors, warnings, stats = validate_raw(items)
    print(f"Total: {stats['total']}")
    print("By type: ", dict(stats["by_type"]))
    print("By band: ", dict(stats["by_band"]))
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print("  -", w)
    if errors:
        print(f"\n{len(errors)} ERROR(s):")
        for e in errors:
            print("  -", e)
    else:
        print("\nNo blocking errors.")
    return not errors


if __name__ == "__main__":
    import json
    from engine.bank import load_bank
    from dataclasses import asdict

    if len(sys.argv) > 1:
        data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    else:
        data = [asdict(q) for q in load_bank()]
    ok = print_report(data)
    sys.exit(0 if ok else 1)
