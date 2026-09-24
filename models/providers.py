"""
Model abstraction layer — all LLM provider logic lives here.
Self-contained copy for the GMAT app. Callers use llm_call() / chat_completion().
"""

import json
import base64
import re
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests as http_requests
from .global_config import (
    FOUNDRY_API_KEY,
    FOUNDRY_BASE,
    OPENAI_MODELS,
    ANTHROPIC_MODELS,
    get_model_max_tokens,
)


# ── Response types ──────────────────────────────────────────────────────

@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class LLMResponse:
    """Unified response from any provider."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_response: object = None

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


# ── Provider detection ──────────────────────────────────────────────────

def _is_anthropic(model_name: str) -> bool:
    return model_name in ANTHROPIC_MODELS


def _get_openai_client():
    from openai import OpenAI
    return OpenAI(base_url=f"{FOUNDRY_BASE}/openai/v1", api_key=FOUNDRY_API_KEY)


def _get_anthropic_client():
    import anthropic
    return anthropic.Anthropic(base_url=f"{FOUNDRY_BASE}/anthropic/", api_key=FOUNDRY_API_KEY)


# ── Core LLM interface ──────────────────────────────────────────────────

def chat_completion(model_name: str, system: str, messages: list,
                    max_tokens: int = None) -> LLMResponse:
    """Unified chat completion across providers (text in/out, no tools)."""
    if max_tokens is None:
        max_tokens = get_model_max_tokens(model_name)

    if _is_anthropic(model_name):
        return _anthropic_completion(model_name, system, messages, max_tokens)
    return _openai_completion(model_name, system, messages, max_tokens)


def llm_call(model_name: str, system: str, user: str, max_tokens: int = None) -> str:
    """Simple text-in text-out LLM call. No tools."""
    if max_tokens is None:
        max_tokens = min(get_model_max_tokens(model_name), 16384)
    messages = [{"role": "user", "content": user}]
    return chat_completion(model_name, system, messages, max_tokens=max_tokens).text


# ── Private: provider implementations ──────────────────────────────────

def _openai_completion(model_name, system, messages, max_tokens) -> LLMResponse:
    client = _get_openai_client()
    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "system", "content": system}] + messages,
        max_completion_tokens=max_tokens,
    )
    msg = response.choices[0].message
    return LLMResponse(text=msg.content or "", raw_response=msg)


def _anthropic_completion(model_name, system, messages, max_tokens) -> LLMResponse:
    client = _get_anthropic_client()
    with client.messages.stream(
        model=model_name, max_tokens=max_tokens, system=system, messages=messages,
    ) as stream:
        response = stream.get_final_message()
    text = "\n".join(b.text for b in response.content if b.type == "text")
    return LLMResponse(text=text, raw_response=response.content)


# ── JSON extraction helper (LLM outputs often wrap JSON in prose) ───────

def extract_json(text: str):
    """Extract the first JSON array or object from an LLM response."""
    text = text.strip()
    # Strip markdown code fences.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Find first [...] or {...} span.
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    return json.loads(text)
