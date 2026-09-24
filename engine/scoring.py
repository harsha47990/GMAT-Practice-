"""Score mapping: ability (theta) -> section score -> total scaled score."""

from config import (
    SECTION_SCORE_MIN, SECTION_SCORE_MAX,
    TOTAL_SCORE_MIN, TOTAL_SCORE_MAX,
    THETA_MIN, THETA_MAX,
)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def theta_to_section_score(theta: float) -> int:
    """Map ability in [-3, 3] linearly to the 60-90 section band."""
    theta = _clamp(theta, THETA_MIN, THETA_MAX)
    frac = (theta - THETA_MIN) / (THETA_MAX - THETA_MIN)
    score = SECTION_SCORE_MIN + frac * (SECTION_SCORE_MAX - SECTION_SCORE_MIN)
    return int(round(score))


def combine_total(section_scores: dict[str, int]) -> int:
    """Combine section scores (60-90 each) into a 205-805 total.

    Approximation of the official curve: average the section bands, then
    map linearly onto the total range. Rounded to the nearest 10 (GMAT
    totals are reported in 10-point steps).
    """
    if not section_scores:
        return TOTAL_SCORE_MIN
    avg = sum(section_scores.values()) / len(section_scores)
    frac = (avg - SECTION_SCORE_MIN) / (SECTION_SCORE_MAX - SECTION_SCORE_MIN)
    frac = _clamp(frac, 0.0, 1.0)
    total = TOTAL_SCORE_MIN + frac * (TOTAL_SCORE_MAX - TOTAL_SCORE_MIN)
    return int(round(total / 10.0) * 10)
