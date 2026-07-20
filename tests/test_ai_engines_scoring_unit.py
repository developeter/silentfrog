"""Unit tests for the v3 G3 Stage 1 AI-engine scoring helpers (pure, no I/O)."""

from __future__ import annotations

from silentfrog.integrations.ai_engines.scoring import (
    cites_domain,
    count_competitor_mentions,
    mentions_brand,
    sentiment_label,
)
from silentfrog.integrations.ai_engines.types import EngineAnswer

# --- mentions_brand -----------------------------------------------------


def test_mentions_brand_case_insensitive() -> None:
    assert mentions_brand("ACME is a great tool.", "Acme") is True
    assert mentions_brand("we use acme daily", "Acme") is True


def test_mentions_brand_no_false_hit_on_substring() -> None:
    # "Acmesoft" contains "Acme" but is a different word entirely.
    assert mentions_brand("Acmesoft is unrelated to the brand.", "Acme") is False
    assert mentions_brand("A megacme company exists.", "Acme") is False


def test_mentions_brand_empty_inputs() -> None:
    assert mentions_brand("", "Acme") is False
    assert mentions_brand("Acme is great", "") is False


# --- cites_domain ---------------------------------------------------------


def test_cites_domain_via_citations_list() -> None:
    answer = EngineAnswer(text="See the source.", citations=("https://acme.com/about",), measured=True)
    assert cites_domain(answer, "acme.com") is True


def test_cites_domain_via_url_in_text_when_no_citations() -> None:
    answer = EngineAnswer(text="More info at https://acme.com/pricing.", citations=(), measured=True)
    assert cites_domain(answer, "acme.com") is True


def test_cites_domain_false_when_absent() -> None:
    answer = EngineAnswer(text="No links here.", citations=("https://other.example/x",), measured=True)
    assert cites_domain(answer, "acme.com") is False


# --- sentiment_label --------------------------------------------------------


def test_sentiment_label_positive() -> None:
    assert sentiment_label("Acme is excellent, reliable, and highly recommended.") == "positive"


def test_sentiment_label_negative() -> None:
    assert sentiment_label("Many call it a scam; it is unreliable and slow.") == "negative"


def test_sentiment_label_neutral_on_tie_or_no_hits() -> None:
    assert sentiment_label("Acme is a company that sells software.") == "neutral"
    assert sentiment_label("Acme is great but also a bit buggy.") == "neutral"  # 1 positive, 1 negative -> tie


# --- count_competitor_mentions -----------------------------------------------


def test_count_competitor_mentions_share_math() -> None:
    texts = ["Acme and Rival Co are both popular.", "Rival Co is the market leader.", "Acme alone here."]
    assert count_competitor_mentions(texts, ("Rival Co",)) == 2
    assert count_competitor_mentions(texts, ("Rival Co", "Other Inc")) == 2
    assert count_competitor_mentions(texts, ()) == 0


def test_count_competitor_mentions_no_false_hit() -> None:
    assert count_competitor_mentions(["Rivalry is fierce."], ("Rival",)) == 0
