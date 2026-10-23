"""Tests for embedding text construction (services/embeddings.py)."""

from journal_browser.services.embeddings import clean_title, embed_text


def test_clean_title_drops_boilerplate():
    assert clean_title("International Journal of Plant Sciences") == "plant sciences"


def test_clean_title_falls_back_when_all_stopwords():
    # "Vaccines" survives ("vaccines"); only an all-boilerplate title
    # falls back to the raw string.
    assert clean_title("Journal") == "Journal"
    assert clean_title("Vaccines") == "vaccines"


def test_embed_text_combines_parts():
    topics = [{"display_name": "Plant Science", "score": 0.9}]
    text = embed_text(
        "Journal of Nematology", topics, ["A very cited worm paper"]
    )
    assert text == "nematology | Plant Science | A very cited worm paper"


def test_embed_text_none_when_empty():
    assert embed_text(None, [], []) is None


def test_embed_text_limits_topics_and_works():
    topics = [{"display_name": f"Topic {i}"} for i in range(8)]
    works = [f"Work {i}" for i in range(6)]
    text = embed_text("Blood", topics, works)
    # cleaned title + 5 topics + 3 works
    assert len(text.split(" | ")) == 9
