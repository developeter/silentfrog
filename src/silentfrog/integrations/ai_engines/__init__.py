"""BYO-key AI-engine share-of-voice integration (v3 G3 Stage 1, optional
extra ``silentfrog[ai-engines]``). Off by default — a stock audit never
calls OpenAI/Perplexity/Gemini. ``keyring`` is lazy-imported by the client
and degrades to env-only when the optional extra is absent."""

from __future__ import annotations

from .checks import SOV_AREA, build_sov_checks
from .client import fetch_share_of_voice, resolve_api_key, test_connection
from .types import EngineAnswer, EngineShareOfVoice, ShareOfVoiceReport

__all__ = [
    "SOV_AREA",
    "EngineAnswer",
    "EngineShareOfVoice",
    "ShareOfVoiceReport",
    "build_sov_checks",
    "fetch_share_of_voice",
    "resolve_api_key",
    "test_connection",
]
