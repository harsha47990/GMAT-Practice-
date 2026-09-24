"""AI report card: turns a finished attempt into a structured diagnostic
summary, then asks the LLM to produce a detailed, actionable review.
"""

import json
import time
from collections import defaultdict
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import REPORTS_DIR, TYPE_LABELS, BAND_LABELS  # noqa: E402
from models.providers import llm_call  # noqa: E402
from models.global_config import GMAT_MODEL  # noqa: E402


_SYSTEM = (
    "You are a sharp GMAT coach. Write a SHORT, high-signal report a busy "
    "student will actually read. Be blunt and specific. Diagnose root cause "
    "(concept gap vs. pacing vs. careless), never pad. No preamble, no "
    "encouragement filler, no restating the data back. Cite only the 2-3 "
    "numbers that matter. Hard limit: about 200 words. Do not invent data."
)


def _pace_flag(time_spent, est) -> str:
    if time_spent is None:
        return "unanswered"
    if est and time_spent < 0.4 * est:
        return "rushed"
    if est and time_spent > 1.8 * est:
        return "slow"
    return "ok"


def build_summary(results: dict) -> dict:
    """Aggregate a finished attempt into compact analytics for the LLM."""
    summary = {
        "mode": results.get("mode"),
        "total_score": results.get("total_score"),
        "sections": [],
    }
    for sec in results.get("sections", []):
        by_type = defaultdict(lambda: {"n": 0, "correct": 0})
        by_band = defaultdict(lambda: {"n": 0, "correct": 0})
        by_tag = defaultdict(lambda: {"n": 0, "correct": 0})
        pace = {"rushed": 0, "slow": 0, "ok": 0, "unanswered": 0}
        times = []

        for q in sec["questions"]:
            t, tag_correct = q["type"], q["correct"]
            by_type[t]["n"] += 1
            by_type[t]["correct"] += int(tag_correct)
            by_band[q["difficulty_band"]]["n"] += 1
            by_band[q["difficulty_band"]]["correct"] += int(tag_correct)
            for tag in q.get("tags", []):
                by_tag[tag]["n"] += 1
                by_tag[tag]["correct"] += int(tag_correct)
            pace[_pace_flag(q.get("time_spent"), q.get("est_time_sec"))] += 1
            if q.get("time_spent") is not None:
                times.append(q["time_spent"])

        def _acc(d):
            return {k: {"attempted": v["n"],
                        "correct": v["correct"],
                        "accuracy": round(v["correct"] / v["n"], 2) if v["n"] else 0.0}
                    for k, v in d.items()}

        summary["sections"].append({
            "name": sec["name"],
            "score": sec["score"],
            "theta": sec["theta"],
            "accuracy": sec["accuracy"],
            "num_served": sec["num_served"],
            "num_correct": sec["num_correct"],
            "edits_used": sec["edits_used"],
            "by_type": {TYPE_LABELS.get(k, k): v for k, v in _acc(by_type).items()},
            "by_difficulty": {BAND_LABELS.get(k, str(k)): v for k, v in _acc(by_band).items()},
            "by_tag": _acc(by_tag),
            "pacing": pace,
            "avg_time_sec": round(sum(times) / len(times), 1) if times else None,
        })
    return summary


def quick_report(results: dict) -> str:
    """Deterministic, no-AI analytics summary in Markdown.

    Works fully offline — no LLM call. Shown by default on the results screen.
    """
    summary = build_summary(results)
    out = []
    total = summary.get("total_score")
    if total is not None:
        out.append(f"**Total score:** {total}")

    for sec in summary["sections"]:
        pct = int(round(sec["accuracy"] * 100))
        out.append(
            f"### {sec['name']} — score {sec['score']} "
            f"({pct}% correct, {sec['num_correct']}/{sec['num_served']})"
        )

        # Merge type + tag breakdowns; only rate items attempted at least twice.
        rated = {**sec["by_type"], **sec["by_tag"]}
        rated = {k: v for k, v in rated.items() if v["attempted"] >= 2}

        if rated:
            weak = sorted(rated.items(), key=lambda kv: kv[1]["accuracy"])[:3]
            strong = sorted(rated.items(), key=lambda kv: -kv[1]["accuracy"])[:2]
            out.append("**Weakest:** " + "; ".join(
                f"{k} {int(round(v['accuracy'] * 100))}% ({v['correct']}/{v['attempted']})"
                for k, v in weak))
            out.append("**Strongest:** " + "; ".join(
                f"{k} {int(round(v['accuracy'] * 100))}%" for k, v in strong))

        # Accuracy on hard items (bands 4-5).
        hard = [v for k, v in sec["by_difficulty"].items()
                if k in ("Hard", "Very Hard") and v["attempted"]]
        if hard:
            hc = sum(v["correct"] for v in hard)
            ha = sum(v["attempted"] for v in hard)
            out.append(f"**Hard questions:** {int(round(hc / ha * 100))}% ({hc}/{ha})")

        p = sec["pacing"]
        bits = []
        if p.get("rushed"):
            bits.append(f"{p['rushed']} rushed")
        if p.get("slow"):
            bits.append(f"{p['slow']} slow")
        if p.get("unanswered"):
            bits.append(f"{p['unanswered']} unanswered")
        avg = sec.get("avg_time_sec")
        pacing = ", ".join(bits) if bits else "on pace"
        if avg is not None:
            pacing += f" · avg {avg:.0f}s/question"
        out.append(f"**Pacing:** {pacing}")

    return "\n\n".join(out)


def generate_report(results: dict, model: str = None) -> str:
    """Produce a Markdown report card and save it to reports/."""
    model = model or GMAT_MODEL
    summary = build_summary(results)

    user = (
        "Write a crisp GMAT debrief from this data. Follow the format EXACTLY, "
        "one line per bullet, no sub-bullets, no tables, ~200 words max.\n\n"
        "Data (JSON):\n```json\n"
        + json.dumps(summary, ensure_ascii=False, indent=2)
        + "\n```\n\n"
        "Format:\n"
        "**Verdict:** <one blunt sentence with the score>\n\n"
        "**Where you're losing points** (max 3, hardest-hitting first):\n"
        "- <topic/tag> \u2014 <accuracy> \u2014 <root cause: concept / pacing / careless>\n\n"
        "**What's solid** (max 2):\n"
        "- <topic> \u2014 <one-line evidence>\n\n"
        "**Pacing:** <one line \u2014 rushing, dragging, or fine>\n\n"
        "**Fix next** (exactly 3, most impactful first):\n"
        "1. <specific action>\n2. <specific action>\n3. <specific action>"
    )

    report = llm_call(model, _SYSTEM, user, max_tokens=700)
    ts = int(time.time())
    out = Path(REPORTS_DIR) / f"report_{ts}_{results.get('sid', '')[:8]}.md"
    out.write_text(report, encoding="utf-8")
    return report
