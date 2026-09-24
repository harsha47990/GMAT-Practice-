"""Minimal, self-contained config for the GMAT app's LLM layer.

Only what providers.py needs. Credentials load from GMAT/.env.
"""

import os
from pathlib import Path


def _load_local_env_file():
    """Load simple KEY=VALUE pairs from GMAT/.env if present."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_local_env_file()

# ── Credentials ─────────────────────────────────────────────────────────
FOUNDRY_API_KEY = os.environ.get("FOUNDRY_API_KEY", "")
FOUNDRY_BASE = os.environ.get("FOUNDRY_BASE", "")

if not FOUNDRY_API_KEY:
    raise RuntimeError("FOUNDRY_API_KEY is not set. Add it to GMAT/.env")
if not FOUNDRY_BASE:
    raise RuntimeError("FOUNDRY_BASE is not set. Add it to GMAT/.env")

# ── Available models (name -> max output tokens) ───────────────────────
OPENAI_MODELS = {
    "gpt-5.6-sol": 128000,
    "gpt-5.5": 128000,
    "gpt-54-sbx": 128000,
}

ANTHROPIC_MODELS = {
    "claude-sonnet-5": 128000,
    "claude-opus-4-8": 128000,
}

ALL_MODELS = list(OPENAI_MODELS.keys()) + list(ANTHROPIC_MODELS.keys())

# Default model for GMAT question generation + report cards.
GMAT_MODEL = os.environ.get("GMAT_MODEL", "gpt-5.6-sol")


def get_model_max_tokens(model_name: str) -> int:
    """Get the max output token limit for a model."""
    return OPENAI_MODELS.get(model_name) or ANTHROPIC_MODELS.get(model_name) or 16384
