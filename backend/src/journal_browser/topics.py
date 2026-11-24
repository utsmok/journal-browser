"""Works-weighted topic mass over venue ISSN counts.

Shared by harvest/authors and services/authors; imports neither package.
"""

from typing import Any


def topic_mass(venues: dict[str, int], topics_by_issn: dict[str, list[Any]]) -> dict[str, float]:
    """Works-weighted topic mass across venues.

    Each venue's works are spread over its OpenAlex topic list in
    proportion to the topics' per-source `count` (a venue split
    40/30/20/10 contributes its works exactly that way), and labels carry
    the topics' subfield — coarser than topic names, whose hyper-specific
    fragments made "most common topic" nearly meaningless. Venues without
    counts (rows stored before the field was persisted) contribute to
    their primary topic only; entries without a subfield fall back to the
    topic name."""
    mass: dict[str, float] = {}
    for issn, n in venues.items():
        entries = [
            t
            for t in topics_by_issn.get(issn) or []
            if isinstance(t, dict) and t.get("display_name")
        ]
        if not entries:
            continue
        counts = [int(t.get("count") or 0) for t in entries]
        total = sum(counts)
        if total <= 0:
            name = entries[0].get("subfield") or entries[0]["display_name"]
            mass[name] = mass.get(name, 0.0) + n
            continue
        for t, c in zip(entries, counts, strict=False):
            name = t.get("subfield") or t["display_name"]
            mass[name] = mass.get(name, 0.0) + n * c / total
    return mass
