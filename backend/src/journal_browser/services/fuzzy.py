"""Trigram similarity in Python, for filters that run in memory over a
cached snapshot (org-unit search) instead of SQL.

The author search goes through SQL and uses the real pg_trgm
`word_similarity`. This module mirrors its trigram construction (pg_trgm
pads each word with two spaces on the left and one on the right) but
scores with the full-set formula count / (len_q + len_target - count),
which is the lower bound of pg_trgm's sliding-window `word_similarity`.
Thresholds here are therefore set below the equivalent pg_trgm ones and
calibrated against it on the observed zero-result queries (see
test_typo_search.py).
"""

import re

#: Jaccard threshold matching pg_trgm's default word_similarity_threshold
#: of 0.3 on the calibrated queries (piloso 0.286, phyloso 0.385 pass;
#: zzqqxx 0.0 fails).
WORD_SIMILARITY_THRESHOLD = 0.25

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

#: Words per comparison window: single words plus adjacent pairs, so
#: queries like "nano lab" still hit "Nano Lab".
_MAX_RUN_WORDS = 2


def word_trigrams(word: str) -> frozenset[str]:
    """pg_trgm trigrams of one word: padded '  word ', all 3-char windows
    ('foo' -> '  f', ' fo', 'foo', 'oo '); a 1-char word yields '  a'
    and ' a '."""
    padded = "  " + word + " "
    n = len(word)
    if n == 0:
        return frozenset()
    return frozenset(padded[i : i + 3] for i in range(n + 1))


def text_trigrams(text: str) -> frozenset[str]:
    """Union of the trigrams of every word in `text`."""
    grams: set[str] = set()
    for word in _WORD_RE.findall(text.lower()):
        grams |= word_trigrams(word)
    return frozenset(grams)


def similarity(a: str, b: str) -> float:
    """count / (len_a + len_b - count) over the two trigram sets."""
    ta, tb = text_trigrams(a), text_trigrams(b)
    if not ta or not tb:
        return 0.0
    shared = len(ta & tb)
    return shared / (len(ta) + len(tb) - shared)


def word_similarity(query: str, text: str) -> float:
    """Best `similarity` between the query and any short run of words in
    `text` (each word and each adjacent pair), so the query can match one
    word inside a longer unit name."""
    words = _WORD_RE.findall(text.lower())
    if not words:
        return 0.0
    return max(
        similarity(" ".join(words[start : start + span]), query)
        for start in range(len(words))
        for span in range(1, min(_MAX_RUN_WORDS, len(words) - start) + 1)
    )
