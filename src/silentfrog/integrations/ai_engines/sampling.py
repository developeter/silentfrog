"""AI share-of-voice prompt sampling (v3 G3 Stage 1).

Builds the fixed prompt set sampled against each keyed engine. Pure and
side-effect-free (env reads only, no network) so it is trivially unit
tested. A custom prompt list (env override) wins outright; otherwise three
defaults are parameterized by the brand name.
"""

from __future__ import annotations

import os

_DEFAULT_PROMPT_TEMPLATES = (
    "What is {brand} and what does it offer?",
    "What are the best alternatives to {brand}?",
    "Is {brand} trustworthy? What do people say about it?",
)
_DEFAULT_MAX_PROMPTS = 5


def _max_prompts() -> int:
    raw = os.environ.get("SILENTFROG_AI_SOV_MAX_PROMPTS", "").strip()
    if not raw:
        return _DEFAULT_MAX_PROMPTS
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_MAX_PROMPTS


def _custom_prompts() -> tuple[str, ...]:
    raw = os.environ.get("SILENTFROG_AI_SOV_PROMPTS", "")
    return tuple(prompt.strip() for prompt in raw.split(";") if prompt.strip())


def build_prompts(brand: str) -> tuple[str, ...]:
    """The prompt set to sample: ``SILENTFROG_AI_SOV_PROMPTS`` (";"-separated)
    wins when set; otherwise three brand-parameterized defaults. Always
    capped at ``SILENTFROG_AI_SOV_MAX_PROMPTS`` (default 5)."""
    custom = _custom_prompts()
    brand = brand or ""
    prompts = custom if custom else tuple(template.format(brand=brand) for template in _DEFAULT_PROMPT_TEMPLATES)
    return prompts[: _max_prompts()]


__all__ = ["build_prompts"]
