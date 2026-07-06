"""Topic-coherence scoring with local sentence embeddings (v2.0 V20).

Embeds the page title and its substantial paragraphs with a local
sentence-transformers model and reports the mean cosine similarity —
a page whose body drifts from what the title promises scores low,
which hurts both topical SEO and how confidently generative engines
can attribute the page to a query.

Everything degrades: without ``silentfrog[embeddings]`` (or when the
flag is off) the payload is unmeasured and no check is emitted. The
model runs fully locally (first use downloads it from the HF hub);
no text ever leaves the machine. The ``embedder`` seam keeps tests
model-free.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ..crawl_types import AiVisibilityCheck

_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_MAX_PARAGRAPHS = 20
_MIN_PARAGRAPH_CHARS = 40
# Silentfrog heuristic (H6): MiniLM title/body cosine below this reads as
# topical drift. Chosen from typical in-domain similarity bands, not a study.
_COHERENCE_GOOD = 0.40

Embedder = Callable[[Sequence[str]], Sequence[Sequence[float]]]


@dataclass(frozen=True)
class TopicEmbeddingsPayload:
    measured: bool = False
    reason: str = ""
    coherence: float = 0.0
    paragraphs_scored: int = 0
    model: str = ""

    @classmethod
    def from_raw(cls, value: Any) -> TopicEmbeddingsPayload:
        if not isinstance(value, dict):
            return cls()
        return cls(
            measured=bool(value.get("measured", False)),
            reason=str(value.get("reason", "")),
            coherence=float(value.get("coherence", 0.0) or 0.0),
            paragraphs_scored=int(value.get("paragraphs_scored", 0) or 0),
            model=str(value.get("model", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "measured": self.measured,
            "reason": self.reason,
            "coherence": self.coherence,
            "paragraphs_scored": self.paragraphs_scored,
            "model": self.model,
        }


def _default_embedder() -> Embedder | None:
    # The constructor is guarded too: first use downloads the model from the
    # HF hub, so offline/proxied machines fail HERE, not at import time.
    try:
        from sentence_transformers import SentenceTransformer  # lazy, optional extra

        model = SentenceTransformer(_MODEL_NAME)
    except Exception:
        return None

    def embed(texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return model.encode(list(texts), show_progress_bar=False).tolist()

    return embed


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def select_paragraphs(paragraphs: Sequence[str]) -> list[str]:
    """Substantial paragraphs only, capped so inference stays bounded."""
    chosen = [text.strip() for text in paragraphs if len(text.strip()) >= _MIN_PARAGRAPH_CHARS]
    return chosen[:_MAX_PARAGRAPHS]


def topic_coherence(
    title: str,
    paragraphs: Sequence[str],
    embedder: Embedder | None = None,
) -> TopicEmbeddingsPayload:
    """Mean title↔paragraph cosine similarity. Never raises."""
    clean_title = (title or "").strip()
    body = select_paragraphs(paragraphs)
    if not clean_title or not body:
        return TopicEmbeddingsPayload(reason="No title or no substantial paragraphs to embed")
    active = embedder if embedder is not None else _default_embedder()
    if active is None:
        return TopicEmbeddingsPayload(
            reason="sentence-transformers unavailable or the model failed to load (silentfrog[embeddings])"
        )
    try:
        vectors = active([clean_title, *body])
    except Exception as exc:
        return TopicEmbeddingsPayload(reason=f"Embedding failed: {type(exc).__name__}: {exc}")
    if len(vectors) != len(body) + 1:
        return TopicEmbeddingsPayload(reason="Embedder returned a mismatched vector count")
    title_vec = vectors[0]
    scores = [_cosine(title_vec, vec) for vec in vectors[1:]]
    coherence = sum(scores) / len(scores)
    return TopicEmbeddingsPayload(
        measured=True,
        coherence=round(coherence, 4),
        paragraphs_scored=len(body),
        model=_MODEL_NAME,
    )


_CHECK_TITLE = "Body paragraphs stay on the topic the title promises"
_CHECK_RECOMMENDATION = (
    "Keep each paragraph anchored to the page's main entity/intent; move drifting sections to "
    "their own pages. Threshold is a Silentfrog heuristic on local MiniLM embeddings, not a "
    "measured ranking factor."
)


def build_topic_embedding_check(payload: TopicEmbeddingsPayload) -> AiVisibilityCheck | None:
    """Topic-clarity check — ``None`` (not emitted) when unmeasured."""
    if not payload.measured:
        return None
    status = "good" if payload.coherence >= _COHERENCE_GOOD else "warning"
    return AiVisibilityCheck(
        area="Topic clarity",
        check=_CHECK_TITLE,
        status=status,
        details=(
            f"Mean title-to-paragraph embedding similarity: {payload.coherence:.2f} "
            f"across {payload.paragraphs_scored} paragraphs (model: {payload.model})."
        ),
        recommendation=_CHECK_RECOMMENDATION,
        key="topic_embedding_coherence",
    )


__all__ = [
    "Embedder",
    "TopicEmbeddingsPayload",
    "build_topic_embedding_check",
    "select_paragraphs",
    "topic_coherence",
]
