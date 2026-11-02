"""Green-route repository names -> jisc_repositories urls.

Route payloads carry short repository names ("RePEc", "arXiv") while the
canon table keeps full display names ("RePEc: Research Papers in
Economics"). The canon list is static between harvests, so it is loaded
once per process and shared by every journal-detail request.
"""

import re
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import JiscRepository

# (display name, url) in canon id order; None until the first request.
_canon: list[tuple[str, str]] | None = None


def reset_canon_cache() -> None:
    """Forget the process-level canon list (test fixture hook: every test
    runs against its own throwaway database)."""
    global _canon
    _canon = None


def _squash(name: str) -> str:
    """Normalized-equality key: lowercase, punctuation and whitespace dropped."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _word_needle(name: str) -> str:
    """Regex matching the full route name as contiguous words (no touching
    alphanumerics): 'repec' matches 'RePEc: Research Papers in Economics',
    never 'RePEcHub'. Empty for punctuation-only names."""
    words = re.findall(r"[a-z0-9]+", name.lower())
    if not words:
        return ""
    return r"(?<![a-z0-9])" + r"\s+".join(map(re.escape, words)) + r"(?![a-z0-9])"


def match_repositories(names: Iterable[str], canon: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Route repository name -> canon url. Exact normalized-equality wins;
    otherwise the first canon name (table id order) containing the full
    route name as a word. Unmatched names are simply absent."""
    exact: dict[str, str] = {}
    lower: list[tuple[str, str]] = []
    for display, url in canon:
        exact.setdefault(_squash(display), url)
        lower.append((display.lower(), url))
    links: dict[str, str] = {}
    for name in names:
        url = exact.get(_squash(name))
        if url is None:
            needle = _word_needle(name)
            if needle:
                url = next((u for low, u in lower if re.search(needle, low)), None)
        if url:
            links[name] = url
    return links


async def repository_links(session: AsyncSession, names: Iterable[str]) -> dict[str, str]:
    """Match against jisc_repositories (cached canon list; static between
    harvests)."""
    global _canon
    if _canon is None:
        rows = (
            await session.execute(
                select(JiscRepository.name, JiscRepository.url)
                .where(JiscRepository.name.is_not(None), JiscRepository.url.is_not(None))
                .order_by(JiscRepository.id)
            )
        ).all()
        _canon = [(row.name, row.url) for row in rows]
    return match_repositories(names, _canon)
