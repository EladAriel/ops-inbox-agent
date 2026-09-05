"""Token / cost helpers for the per-request audit trail.

Uses OpenRouter list prices (USD per 1M tokens) from ``settings``:
chat input/output for gpt-4o-mini, flat rate for text-embedding-3-small.
Cost is accumulated on each API call; ``finalize_audit`` only rounds.
"""
from __future__ import annotations

from typing import Any, Tuple

from starter.config import settings
from starter.state import RequestState


def _prompt_and_completion_tokens(usage: Any) -> Tuple[int, int]:
    """Return (prompt_tokens, completion_tokens) from an API usage object.

    If only ``total_tokens`` is present, treat the whole amount as prompt
    (conservative under-estimate vs pricing everything as output).
    """
    if usage is None:
        return 0, 0
    prompt = int(getattr(usage, "prompt_tokens", None) or 0)
    completion = int(getattr(usage, "completion_tokens", None) or 0)
    if prompt == 0 and completion == 0:
        total = getattr(usage, "total_tokens", None)
        if total is not None:
            prompt = int(total)
    return prompt, completion


def chat_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    """USD for a chat completion from OpenRouter gpt-4o-mini rates."""
    inp = settings.PRICE_PER_M_CHAT_INPUT
    out = settings.PRICE_PER_M_CHAT_OUTPUT
    return (max(0, prompt_tokens) * inp + max(0, completion_tokens) * out) / 1_000_000.0


def embedding_cost_usd(tokens: int) -> float:
    """USD for an embedding call from OpenRouter text-embedding-3-small rate."""
    return max(0, tokens) * settings.PRICE_PER_M_EMBEDDING / 1_000_000.0


def record_chat_usage(state: RequestState, completion: Any) -> None:
    """Add chat tokens and in/out cost onto the request audit state."""
    usage = getattr(completion, "usage", None)
    prompt, completion_toks = _prompt_and_completion_tokens(usage)
    state.tokens += prompt + completion_toks
    state.cost_usd += chat_cost_usd(prompt, completion_toks)


def record_embedding_usage(state: RequestState, response: Any) -> None:
    """Add embedding tokens and cost onto the request audit state."""
    usage = getattr(response, "usage", None)
    prompt, _ = _prompt_and_completion_tokens(usage)
    state.tokens += prompt
    state.cost_usd += embedding_cost_usd(prompt)
