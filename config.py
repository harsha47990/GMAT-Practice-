"""GMAT Focus Edition exam blueprint, scoring constants, and paths."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
ATTEMPTS_DIR = DATA_DIR / "attempts"
REPORTS_DIR = BASE_DIR / "reports"
BANK_PATH = DATA_DIR / "bank.dat"
KEY_PATH = DATA_DIR / "bank.key"

for _d in (DATA_DIR, ATTEMPTS_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ── Question types ──────────────────────────────────────────────────────
# Every question is modeled as a single-answer multiple-choice item so the
# adaptive engine and UI stay uniform. Graphical Data Insights formats
# (Table/Graphics) are approximated as MCQ for this mock.
TYPE_LABELS = {
    "PS":  "Problem Solving",
    "DS":  "Data Sufficiency",
    "CR":  "Critical Reasoning",
    "RC":  "Reading Comprehension",
    "MSR": "Multi-Source Reasoning",
    "TA":  "Table Analysis",
    "GI":  "Graphics Interpretation",
    "TPA": "Two-Part Analysis",
}

# Types that share a passage/stimulus block shown above the question.
PASSAGE_TYPES = {"RC", "DS", "MSR", "TA", "GI"}


# ── Section blueprint (GMAT Focus Edition) ─────────────────────────────
SECTIONS = {
    "Quantitative": {
        "types": ["PS"],
        "num_questions": 21,
        "time_minutes": 45,
        "allow_calculator": False,   # Real Focus edition: no calculator in Quant.
    },
    "Verbal": {
        "types": ["CR", "RC"],
        "num_questions": 23,
        "time_minutes": 45,
        "allow_calculator": False,
    },
    "Data Insights": {
        "types": ["DS", "MSR", "TA", "GI", "TPA"],
        "num_questions": 20,
        "time_minutes": 45,
        "allow_calculator": True,    # Real exam: on-screen calculator in DI only.
    },
}

SECTION_ORDER = ["Quantitative", "Verbal", "Data Insights"]

# Editing rule: candidates may change up to this many answers per section.
REVIEW_EDIT_LIMIT = 3


# ── Difficulty bands (1..5) mapped to IRT "b" parameter ────────────────
BAND_TO_B = {1: -2.0, 2: -1.0, 3: 0.0, 4: 1.0, 5: 2.0}
BAND_LABELS = {1: "Very Easy", 2: "Easy", 3: "Medium", 4: "Hard", 5: "Very Hard"}


def b_to_band(b: float) -> int:
    """Bucket an IRT difficulty into a 1..5 band."""
    thresholds = [(-1.5, 1), (-0.5, 2), (0.5, 3), (1.5, 4)]
    for edge, band in thresholds:
        if b < edge:
            return band
    return 5


# ── Scoring ─────────────────────────────────────────────────────────────
SECTION_SCORE_MIN = 60
SECTION_SCORE_MAX = 90
TOTAL_SCORE_MIN = 205
TOTAL_SCORE_MAX = 805

# Ability (theta) is clamped to this range for scoring.
THETA_MIN = -3.0
THETA_MAX = 3.0
