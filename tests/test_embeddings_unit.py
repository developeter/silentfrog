"""Unit tests for v2.0 V20 topic embeddings (fake embedder — no model)."""

from __future__ import annotations

from silentfrog.embeddings import TopicEmbeddingsPayload, build_topic_embedding_check, topic_coherence
from silentfrog.embeddings.topic import select_paragraphs

_LONG = "This paragraph talks about the audited topic in enough detail to be substantial."


def _fake_embedder(vectors: dict[str, list[float]]):
    def embed(texts):
        return [vectors[text] for text in texts]

    return embed


def test_topic_coherence_high_when_title_and_body_align() -> None:
    title = "Espresso brewing guide"
    body = _LONG
    embedder = _fake_embedder({title: [1.0, 0.0], body: [1.0, 0.0]})
    payload = topic_coherence(title, [body], embedder=embedder)
    assert payload.measured is True
    assert payload.coherence == 1.0
    assert payload.paragraphs_scored == 1


def test_topic_coherence_low_when_body_drifts() -> None:
    title = "Espresso brewing guide"
    body = _LONG
    embedder = _fake_embedder({title: [1.0, 0.0], body: [0.0, 1.0]})
    payload = topic_coherence(title, [body], embedder=embedder)
    assert payload.measured is True
    assert payload.coherence == 0.0


def test_unmeasured_without_title_or_paragraphs_or_extra() -> None:
    assert topic_coherence("", [_LONG], embedder=_fake_embedder({})).measured is False
    assert topic_coherence("Title", ["short"], embedder=_fake_embedder({})).measured is False
    # No embedder injected and no extra installed -> degrades, never raises.
    payload = topic_coherence("Title", [_LONG], embedder=None)
    if not payload.measured:
        assert "sentence-transformers" in payload.reason or "Embedding failed" in payload.reason


def test_model_construction_failure_degrades_to_unmeasured(monkeypatch) -> None:
    # Regression: SentenceTransformer() downloads the model on first use, so
    # its constructor raising (offline/proxy) must degrade, not crash the audit.
    import sys
    import types

    stub = types.ModuleType("sentence_transformers")

    class _BoomTransformer:
        def __init__(self, name: str) -> None:
            raise OSError("HF hub unreachable")

    stub.SentenceTransformer = _BoomTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", stub)
    payload = topic_coherence("Title", [_LONG], embedder=None)
    assert payload.measured is False
    assert "failed to load" in payload.reason or "unavailable" in payload.reason


def test_embedder_failure_degrades_to_unmeasured() -> None:
    def boom(texts):
        raise RuntimeError("model exploded")

    payload = topic_coherence("Title", [_LONG], embedder=boom)
    assert payload.measured is False
    assert "RuntimeError" in payload.reason


def test_select_paragraphs_filters_short_and_caps() -> None:
    paragraphs = ["short"] + [f"{_LONG} #{i}" for i in range(30)]
    chosen = select_paragraphs(paragraphs)
    assert len(chosen) == 20
    assert all(len(text) >= 40 for text in chosen)


def test_check_emitted_only_when_measured_with_heuristic_threshold() -> None:
    assert build_topic_embedding_check(TopicEmbeddingsPayload()) is None
    good = build_topic_embedding_check(
        TopicEmbeddingsPayload(measured=True, coherence=0.62, paragraphs_scored=5, model="m")
    )
    assert good is not None
    assert good.key == "topic_embedding_coherence"
    assert good.status == "good"
    drifting = build_topic_embedding_check(
        TopicEmbeddingsPayload(measured=True, coherence=0.18, paragraphs_scored=5, model="m")
    )
    assert drifting is not None
    assert drifting.status == "warning"


def test_payload_round_trips_json_native() -> None:
    payload = TopicEmbeddingsPayload(measured=True, coherence=0.5, paragraphs_scored=3, model="m")
    assert TopicEmbeddingsPayload.from_raw(payload.to_dict()) == payload
