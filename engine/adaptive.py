"""Adaptive engine: Rasch (1-PL IRT) ability estimation + item selection.

Ability theta is estimated by maximum likelihood over administered items.
The next item is the unused question whose difficulty maximizes Fisher
information at the current theta (i.e. difficulty closest to theta), subject
to the section's allowed question types.
"""

import math
import random

THETA_MIN, THETA_MAX = -3.0, 3.0
_DISCRIMINATION = 1.0  # Rasch model fixes a = 1.


def _p_correct(theta: float, b: float) -> float:
    """1-PL probability of a correct response."""
    return 1.0 / (1.0 + math.exp(-_DISCRIMINATION * (theta - b)))


def estimate_theta(responses: list[tuple[float, bool]]) -> float:
    """MLE of ability given [(difficulty, correct), ...] via Newton-Raphson.

    Falls back to a bounded step for all-correct / all-wrong patterns where
    the likelihood has no interior maximum.
    """
    if not responses:
        return 0.0

    n_correct = sum(1 for _, c in responses if c)
    if n_correct == 0:
        return max(THETA_MIN, min(b for b, _ in responses) - 1.0)
    if n_correct == len(responses):
        return min(THETA_MAX, max(b for b, _ in responses) + 1.0)

    theta = 0.0
    for _ in range(40):
        grad = 0.0     # first derivative of log-likelihood
        info = 0.0     # negative second derivative (Fisher information)
        for b, correct in responses:
            p = _p_correct(theta, b)
            grad += (1.0 if correct else 0.0) - p
            info += p * (1.0 - p)
        if info < 1e-9:
            break
        step = grad / info
        theta += step
        theta = max(THETA_MIN, min(THETA_MAX, theta))
        if abs(step) < 1e-4:
            break
    return theta


class AdaptiveEngine:
    """Per-section adaptive controller over a fixed pool of questions."""

    def __init__(self, pool, allowed_types, seed=None):
        self.pool = list(pool)
        self.allowed_types = list(allowed_types)
        self.rng = random.Random(seed)
        self.theta = 0.0
        self.administered_ids: set[str] = set()
        self.responses: list[tuple[float, bool]] = []  # (difficulty, correct)

    def _candidates(self, qtype=None):
        cands = [q for q in self.pool if q.id not in self.administered_ids]
        if qtype:
            cands = [q for q in cands if q.type == qtype]
        else:
            cands = [q for q in cands if q.type in self.allowed_types]
        return cands

    def select_next(self, qtype=None):
        """Pick the next unused item with max information at current theta."""
        cands = self._candidates(qtype)
        if not cands and qtype:
            cands = self._candidates(None)
        if not cands:
            return None
        # Maximum Fisher information == difficulty closest to theta.
        # Small jitter avoids always picking the same item on ties.
        best = min(cands, key=lambda q: abs(q.difficulty - self.theta)
                   + self.rng.uniform(0, 0.05))
        return best

    def record(self, question, correct: bool):
        """Register a response and re-estimate ability."""
        self.administered_ids.add(question.id)
        self.responses.append((question.difficulty, bool(correct)))
        self.theta = estimate_theta(self.responses)
        return self.theta
