"""Embedding text construction for journal similarity.

Kept free of torch/sentence-transformers imports so the API container and
the test suite can use it; only jobs/embed_journals.py loads the model.
"""

import re
from typing import Any

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSION = 384

#: Journal-title boilerplate that carries no subject signal (owner request:
#: drop "journal", "of", "and", ...). Deliberately small — words like
#: "review" or "advances" are discriminative and must stay.
STOPWORDS = frozenset(
    {"a", "an", "and", "for", "in", "international", "journal", "journals", "of", "on", "the", "to"}
)


def clean_title(title: str) -> str:
    """Lowercased title words minus boilerplate; raw title as fallback when
    nothing survives (e.g. "Vaccines")."""
    words = re.findall(r"[a-z0-9]+", title.lower())
    kept = [w for w in words if w not in STOPWORDS]
    return " ".join(kept) if kept else title.strip()


def embed_text(
    title: str | None, topics: list[Any] | None, work_titles: list[str] | None
) -> str | None:
    """One text per journal: cleaned title, top topic names, then titles of
    the journal's most cited works. None when there is nothing to embed."""
    parts = []
    if title:
        parts.append(clean_title(title))
    parts.extend(t["display_name"] for t in (topics or [])[:5] if t.get("display_name"))
    parts.extend(t for t in (work_titles or [])[:3] if t)
    return " | ".join(parts) or None
