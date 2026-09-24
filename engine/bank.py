"""Encrypted question bank: read/write, filtering, and dedup helpers.

On-disk format:  JSON  ->  gzip  ->  Fernet-encrypted bytes  ->  data/bank.dat
The Fernet key lives in data/bank.key (gitignored). Without it the bank
cannot be read, so questions/answers are not human-readable on disk.
"""

import gzip
import json
import re
import unicodedata
from dataclasses import dataclass, asdict, field

from cryptography.fernet import Fernet

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import BANK_PATH, KEY_PATH, b_to_band  # noqa: E402


# ── Question model ──────────────────────────────────────────────────────

@dataclass
class Question:
    id: str
    section: str
    type: str
    stem: str
    options: list[str]
    answer_index: int
    difficulty: float                 # IRT "b" parameter (-3..3)
    difficulty_band: int = 3          # 1..5
    passage: str = ""                 # shared stimulus (RC/DS/MSR/TA/GI)
    explanation: str = ""
    tags: list[str] = field(default_factory=list)
    est_time_sec: int = 120

    def public_dict(self) -> dict:
        """Question payload safe to send to the browser (no answer/explanation)."""
        return {
            "id": self.id,
            "section": self.section,
            "type": self.type,
            "passage": self.passage,
            "stem": self.stem,
            "options": self.options,
            "difficulty_band": self.difficulty_band,
            "est_time_sec": self.est_time_sec,
        }


# ── Key management ──────────────────────────────────────────────────────

def _load_or_create_key() -> bytes:
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes()
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    return key


# ── Persistence ─────────────────────────────────────────────────────────

def save_bank(questions: list[Question], path=BANK_PATH) -> None:
    """Serialize -> gzip -> encrypt -> write."""
    raw = json.dumps([asdict(q) for q in questions], ensure_ascii=False).encode("utf-8")
    compressed = gzip.compress(raw)
    token = Fernet(_load_or_create_key()).encrypt(compressed)
    Path(path).write_bytes(token)


def load_bank(path=BANK_PATH) -> list[Question]:
    """Read -> decrypt -> gunzip -> deserialize."""
    p = Path(path)
    if not p.exists():
        return []
    compressed = Fernet(_load_or_create_key()).decrypt(p.read_bytes())
    data = json.loads(gzip.decompress(compressed).decode("utf-8"))
    return [Question(**item) for item in data]


# ── Filtering ───────────────────────────────────────────────────────────

def filter_questions(bank: list[Question], section=None, qtype=None,
                     types=None) -> list[Question]:
    out = bank
    if section:
        out = [q for q in out if q.section == section]
    if qtype:
        out = [q for q in out if q.type == qtype]
    if types:
        types = set(types)
        out = [q for q in out if q.type in types]
    return out


# ── Dedup helpers ───────────────────────────────────────────────────────

def normalize_text(text: str) -> str:
    """Lowercase, strip accents/punctuation/whitespace for fingerprinting."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def fingerprint(question) -> str:
    """Stable fingerprint of a question's stem (+ passage head) for dedup."""
    stem = question.stem if isinstance(question, Question) else question.get("stem", "")
    passage = question.passage if isinstance(question, Question) else question.get("passage", "")
    return normalize_text((passage or "")[:120] + " " + stem)


def existing_fingerprints(bank: list[Question]) -> set[str]:
    return {fingerprint(q) for q in bank}


# ── Bank-building helper ────────────────────────────────────────────────

def make_question(raw: dict, qid: str) -> Question:
    """Build a validated Question from a raw dict, filling derived fields."""
    b = float(raw.get("difficulty", 0.0))
    return Question(
        id=qid,
        section=raw["section"],
        type=raw["type"],
        stem=raw["stem"].strip(),
        options=[str(o).strip() for o in raw["options"]],
        answer_index=int(raw["answer_index"]),
        difficulty=b,
        difficulty_band=int(raw.get("difficulty_band") or b_to_band(b)),
        passage=(raw.get("passage") or "").strip(),
        explanation=(raw.get("explanation") or "").strip(),
        tags=list(raw.get("tags") or []),
        est_time_sec=int(raw.get("est_time_sec") or 120),
    )
