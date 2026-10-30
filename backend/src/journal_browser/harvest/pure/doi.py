import re
from urllib.parse import unquote

# ── DOI extraction (port of ut-metadata identifiers.extract_doi) ────────────

_DOI_RE = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)
_ZW_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
_DOI_PREFIX_RE = re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/?", re.IGNORECASE)
_DOI_TAIL_RE = re.compile(r"[?#].*$")
_DOI_TRAIL = ".,;)-/"
_DOI_VERSION_RE = re.compile(r"\.v\d+$", re.IGNORECASE)


def _doi_clean(s: str | None) -> str | None:
    """Prewash: whitespace, zero-width chars, percent-encoding, resolver and
    ``doi:`` prefixes, query/fragment tails, trailing punctuation, version
    suffixes. None when nothing remains."""
    out = (s or "").strip()
    if "%" in out:
        out = unquote(out)
    out = _ZW_RE.sub("", out).strip().lower()
    while True:
        if m := _DOI_PREFIX_RE.match(out):
            out = out[m.end() :].strip()
        elif out.startswith("doi:"):
            out = out[4:].strip()
        elif out.startswith("/"):
            out = out[1:].strip()
        else:
            break
    out = _DOI_TAIL_RE.sub("", out).rstrip(_DOI_TRAIL)
    return _DOI_VERSION_RE.sub("", out) or None


def extract_doi(value: str) -> str | None:
    """Bare lowercase DOI found anywhere in a dc:identifier-ish string."""
    match = _DOI_RE.search(value)
    if match is None:
        return None
    return _doi_clean(match.group(0))
