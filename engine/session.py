"""Exam session state machine: full mock + topic practice, with timers,
adaptive delivery, end-of-section review/edit, and result persistence.

Session state is held in memory (single local user). Timers are derived from
server timestamps; the browser renders the countdown and the server enforces
deadlines on every request.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from config import (
    SECTIONS, SECTION_ORDER, TYPE_LABELS, REVIEW_EDIT_LIMIT,
    ATTEMPTS_DIR,
)
from engine.bank import load_bank, filter_questions, Question
from engine.adaptive import AdaptiveEngine, estimate_theta
from engine.scoring import theta_to_section_score, combine_total


def _section_for_type(qtype: str) -> str:
    for name, cfg in SECTIONS.items():
        if qtype in cfg["types"]:
            return name
    return "Practice"


@dataclass
class SectionRun:
    name: str
    types: list[str]
    num_questions: int
    time_seconds: int
    allow_calculator: bool
    timed: bool = True
    engine: AdaptiveEngine = None
    served: list[Question] = field(default_factory=list)     # in delivery order
    answers: dict = field(default_factory=dict)              # qid -> choice_index
    served_at: dict = field(default_factory=dict)            # qid -> timestamp
    time_spent: dict = field(default_factory=dict)           # qid -> seconds
    start_time: float = 0.0
    edits_used: int = 0
    state: str = "pending"   # pending -> active -> review -> done

    def deadline(self) -> float:
        return self.start_time + self.time_seconds

    def time_remaining(self) -> int:
        if not self.timed:
            return -1
        return max(0, int(round(self.deadline() - time.time())))

    def is_expired(self) -> bool:
        return self.timed and time.time() >= self.deadline()

    def quota_reached(self) -> bool:
        return len(self.served) >= self.num_questions


class Session:
    def __init__(self, mode: str):
        self.sid = uuid.uuid4().hex
        self.mode = mode                      # "full" | "practice"
        self.created_at = time.time()
        self.bank = load_bank()
        self.sections: list[SectionRun] = []
        self.cursor = 0                       # index into self.sections
        self.current_qid: str | None = None
        self.finished = False
        self.results: dict | None = None

    # ── Construction ────────────────────────────────────────────────────

    @classmethod
    def full_exam(cls) -> "Session":
        s = cls("full")
        for name in SECTION_ORDER:
            cfg = SECTIONS[name]
            pool = filter_questions(s.bank, section=name, types=cfg["types"])
            s.sections.append(SectionRun(
                name=name, types=list(cfg["types"]),
                num_questions=cfg["num_questions"],
                time_seconds=cfg["time_minutes"] * 60,
                allow_calculator=cfg["allow_calculator"],
                timed=True,
                engine=AdaptiveEngine(pool, cfg["types"]),
            ))
        return s

    @classmethod
    def practice(cls, qtype: str, count: int, timed: bool) -> "Session":
        s = cls("practice")
        section_name = _section_for_type(qtype)
        allow_calc = SECTIONS.get(section_name, {}).get("allow_calculator", False)
        pool = filter_questions(s.bank, qtype=qtype)
        count = max(1, min(count, len(pool) if pool else count))
        # Practice time budget mirrors the real ~2 min/question pace.
        s.sections.append(SectionRun(
            name=f"Practice · {TYPE_LABELS.get(qtype, qtype)}",
            types=[qtype], num_questions=count,
            time_seconds=count * 120,
            allow_calculator=allow_calc,
            timed=timed,
            engine=AdaptiveEngine(pool, [qtype]),
        ))
        return s

    # ── Current section helpers ─────────────────────────────────────────

    @property
    def section(self) -> SectionRun | None:
        if self.cursor < len(self.sections):
            return self.sections[self.cursor]
        return None

    def _served_question(self, qid: str) -> Question | None:
        for sec in self.sections:
            for q in sec.served:
                if q.id == qid:
                    return q
        return None

    # ── Flow ────────────────────────────────────────────────────────────

    def _ensure_started(self):
        sec = self.section
        if sec and sec.state == "pending":
            sec.state = "active"
            sec.start_time = time.time()
            self._serve_next()

    def _serve_next(self):
        sec = self.section
        if sec is None:
            return
        q = sec.engine.select_next()
        if q is None:
            sec.state = "review"
            self.current_qid = None
            return
        sec.served.append(q)
        sec.served_at[q.id] = time.time()
        self.current_qid = q.id

    def submit_answer(self, qid: str, choice_index: int):
        """Record an answer during the active phase and advance."""
        sec = self.section
        if sec is None or sec.state != "active":
            return
        if sec.is_expired():
            self._finalize_section()
            return
        q = self._served_question(qid)
        if q is None or qid != self.current_qid:
            return
        sec.answers[qid] = int(choice_index)
        sec.time_spent[qid] = round(time.time() - sec.served_at.get(qid, time.time()), 1)
        sec.engine.record(q, correct=(int(choice_index) == q.answer_index))

        if sec.quota_reached() or sec.is_expired():
            sec.state = "review"
            self.current_qid = None
        else:
            self._serve_next()

    def edit_answer(self, qid: str, choice_index: int) -> bool:
        """Change an answer during the review phase (bounded by edit limit)."""
        sec = self.section
        if sec is None or sec.state != "review":
            return False
        if qid not in sec.answers:
            return False
        if sec.answers[qid] == int(choice_index):
            return True
        if sec.edits_used >= REVIEW_EDIT_LIMIT:
            return False
        sec.answers[qid] = int(choice_index)
        sec.edits_used += 1
        return True

    def confirm_section(self):
        """End the current section (from review) and advance."""
        sec = self.section
        if sec is None:
            return
        self._finalize_section()

    def _finalize_section(self):
        sec = self.section
        if sec is None or sec.state == "done":
            return
        sec.state = "done"
        self.current_qid = None
        self.cursor += 1
        if self.section is not None:
            self._ensure_started()
        else:
            self._finalize_exam()

    # ── Results ─────────────────────────────────────────────────────────

    def _section_result(self, sec: SectionRun) -> dict:
        # Recompute ability from FINAL answers (so review edits matter).
        responses = []
        detail = []
        for q in sec.served:
            chosen = sec.answers.get(q.id)
            correct = chosen is not None and chosen == q.answer_index
            responses.append((q.difficulty, bool(correct)))
            detail.append({
                "id": q.id, "type": q.type, "difficulty": q.difficulty,
                "difficulty_band": q.difficulty_band, "tags": q.tags,
                "chosen": chosen, "answer_index": q.answer_index,
                "correct": bool(correct), "answered": chosen is not None,
                "time_spent": sec.time_spent.get(q.id),
                "est_time_sec": q.est_time_sec,
            })
        theta = estimate_theta(responses) if responses else 0.0
        score = theta_to_section_score(theta)
        n_correct = sum(1 for d in detail if d["correct"])
        return {
            "name": sec.name,
            "theta": round(theta, 3),
            "score": score,
            "num_served": len(sec.served),
            "num_correct": n_correct,
            "accuracy": round(n_correct / len(detail), 3) if detail else 0.0,
            "edits_used": sec.edits_used,
            "questions": detail,
        }

    def _finalize_exam(self):
        section_results = [self._section_result(s) for s in self.sections]
        section_scores = {r["name"]: r["score"] for r in section_results}
        total = combine_total(section_scores) if self.mode == "full" else None
        self.results = {
            "sid": self.sid,
            "mode": self.mode,
            "created_at": self.created_at,
            "finished_at": time.time(),
            "total_score": total,
            "sections": section_results,
        }
        self.finished = True
        self._persist()

    def _persist(self):
        path = Path(ATTEMPTS_DIR) / f"{int(self.created_at)}_{self.sid[:8]}.json"
        path.write_text(json.dumps(self.results, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # ── Serialization for the client ────────────────────────────────────

    def state_payload(self) -> dict:
        self._ensure_started()
        sec = self.section

        if self.finished:
            return {"phase": "finished", "sid": self.sid, "results": self.results}

        if sec is None:
            self._finalize_exam()
            return {"phase": "finished", "sid": self.sid, "results": self.results}

        # Enforce deadline on read.
        if sec.state == "active" and sec.is_expired():
            sec.state = "review"
            self.current_qid = None

        base = {
            "sid": self.sid,
            "mode": self.mode,
            "section": {
                "name": sec.name,
                "index": self.cursor,
                "total_sections": len(self.sections),
                "num_questions": sec.num_questions,
                "answered": len(sec.answers),
                "served": len(sec.served),
                "allow_calculator": sec.allow_calculator,
                "timed": sec.timed,
                "time_remaining": sec.time_remaining(),
                "edits_used": sec.edits_used,
                "edit_limit": REVIEW_EDIT_LIMIT,
            },
        }

        if sec.state == "review":
            base["phase"] = "review"
            base["review"] = [
                {
                    "id": q.id, "type": q.type,
                    "stem": q.stem, "passage": q.passage,
                    "options": q.options, "chosen": sec.answers.get(q.id),
                }
                for q in sec.served
            ]
            return base

        base["phase"] = "question"
        q = self._served_question(self.current_qid) if self.current_qid else None
        if q is None:
            self._serve_next()
            q = self._served_question(self.current_qid) if self.current_qid else None
        base["question"] = q.public_dict() if q else None
        base["question_number"] = len(sec.served)
        return base
