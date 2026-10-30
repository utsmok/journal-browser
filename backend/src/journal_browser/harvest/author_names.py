"""Person-name decomposition for the author identity cascade.

Ported from ut-metadata's reconcile/normalize.py (the core_authors ladder's
forms): norm_text, the NameForms decomposition (initials forms,
"J.B.F. van Erp" vs "Jeroen Bernard François van Erp" fold to the same
key), and the CJK surname guard that discards weak name-only evidence.
Person-name parsing stays nameparser-backed with the same lexicon tuning
('ten'/'ben' particles, religious honorifics restored to given names);
match-key construction is local.
"""

import re
import unicodedata
from typing import NamedTuple

from nameparser import Lexicon, Parser

# ── ORCID form (ut-metadata identifiers port) ──────────────────────────────

_ORCID_PREFIX_RE = re.compile(r"^\s*(?:https?://(?:orcid\.org/)?|orcid\.org/)", re.IGNORECASE)


def bare_orcid_form(s: str | None) -> str | None:
    """Bare ORCID, payload case preserved ('https://orcid.org/…' -> '…')."""
    if not s:
        return None
    out = _ORCID_PREFIX_RE.sub("", s.strip())
    return out or None


def bare_orcid(s: str | None) -> str | None:
    """Bare ORCID, lower-cased: ORCIDs compare case-insensitively."""
    out = bare_orcid_form(s)
    return out.lower() if out else None


def bare_ror(s: str | None) -> str | None:
    """'https://ror.org/02d4c4y02' -> '02d4c4y02'."""
    if not s:
        return None
    out = re.sub(r"^\s*https?://ror\.org/", "", s.strip(), flags=re.IGNORECASE)
    return out.lower() or None


def norm_text(s: str | None) -> str:
    """Normalize for fuzzy comparison: lowercase, strip punctuation/spaces."""
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]", "", s.lower())


# ── Structured author-name forms (the cascade's canonical keys) ────────────

# Dotless all-caps runs in a given block are compressed initials ("Jan AGM van Dijk").
_COMPRESSED_INITIALS = re.compile(r"[A-Z]{2,}")
# Hyphen/space unification: both are token separators ("Jean-Pierre" == "Jean Pierre").
_SEP_RE = re.compile(r"[\s.\-]+")


def _fold(s: str) -> str:
    """NFKD + strip combining marks + casefold ("É" -> "e")."""
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


class NameForms(NamedTuple):
    """Structured decomposition of one author name plus the canonical
    ordered forms of the identity ladder: (a) initials+family, spaced and
    tight; (b) full given+family; (c) first-initial+family; (d) family
    only. Empty form strings mean "not derivable" (e.g. no given block)."""

    given: tuple[str, ...]
    initials: tuple[str, ...]
    family: tuple[str, ...]
    initials_family: str
    initials_family_tight: str
    full: str
    first_initial_family: str
    family_only: str
    #: equality set for the initials rung (spaced + tight variants)
    initials_forms: frozenset[str]


def _given_and_initials(given: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(full given tokens, ordered initials) from a given-name block.
    Initials come from single-letter tokens, compressed caps runs and the
    first letter of full tokens alike, so "J.B.F.", "J B F" and "Jeroen
    Bernard François" all yield ('j', 'b', 'f')."""
    fulls: list[str] = []
    initials: list[str] = []
    for tok in _SEP_RE.split(given.strip()):
        folded = _fold(tok)
        if not folded:
            continue
        if len(tok) == 1:
            initials.append(folded)
        elif _COMPRESSED_INITIALS.fullmatch(tok):
            initials.extend(folded)
        else:
            fulls.append(folded)
            initials.append(folded[0])
    return tuple(fulls), tuple(initials)


def _family_tokens(family: str) -> tuple[str, ...]:
    return tuple(t for t in _SEP_RE.split(_fold(family or "")) if t)


def _name_forms(given: str, family: str) -> NameForms:
    fulls, initials = _given_and_initials(given)
    fam_toks = _family_tokens(family)
    fam = " ".join(fam_toks)
    spaced = f"{' '.join(initials)} {fam}" if initials and fam else ""
    tight = f"{''.join(initials)} {fam}" if initials and fam else ""
    return NameForms(
        given=fulls,
        initials=initials,
        family=fam_toks,
        initials_family=spaced,
        initials_family_tight=tight,
        full=" ".join((*fulls, *fam_toks)) if fulls and fam else "",
        first_initial_family=f"{initials[0]} {fam}" if initials and fam else "",
        family_only=fam,
        initials_forms=frozenset(f for f in (spaced, tight) if f),
    )


# ── Person name parsing (nameparser-backed, lexicon tuned) ─────────────────

# Lexicon tuning, data-driven (72.6k person names diffed in ut-metadata
# 2026-09-17): 'ten' (Dutch, never a first name) and 'ben' (Arabic
# patronymic) join the particle set ('ben' ambiguous: 'Ben van Lier' keeps
# its given name); religious/royal honorifics leave the title vocabulary —
# Mahdi, Imam, Cheikh, Prince, Rock, Gen, Maharajah, Tirthankar, Ab are
# ordinary given names here and must not be eaten as titles.
_LEXICON = (
    Lexicon.default()
    .add(particles={"ten", "ben"}, particles_ambiguous={"ben"})
    .remove(
        titles={
            "mahdi",
            "imam",
            "rock",
            "gen",
            "prince",
            "cheikh",
            "ab",
            "maharajah",
            "tirthankar",
            "marquis",
            "guru",
            "md",
            "royal",
            "shaik",
            "sheikh",
        },
        given_name_titles={"prince", "cheikh"},
    )
)
_DOTTED_RE = re.compile(r"[A-Za-z][A-Za-z.\-]*\.(?: [A-Za-z][A-Za-z.\-]*\.)*")
_PARSE = Parser(lexicon=_LEXICON).parse
_PAREN_RE = re.compile(r"\s*\([^)]*\)")
_WS_RE = re.compile(r"\s+")
# Honorific tokens that stay titles even in dotted form: the lexicon plus
# the legacy set the lexicon lacks (Dutch drs/ir/mw/ing). A dotted "title"
# is really an initials block for any token outside this set ('Th. Rasing',
# 'AL. Ramanathan', 'G.E.St.J.', 'dr. J.B.F.'); the honorifics among them
# drop, the rest fold back into the given block.
_LEGACY_TITLES = frozenset({"dr", "mr", "prof", "professor", "sir", "ing", "drs", "ir", "mw"})


def _initials_from_title(title: str) -> str:
    """Non-honorific tokens of a dotted structural title ('dr. J.B.F.' ->
    'J.B.F.', 'Dr.' -> '') — the initials a chained title swallowed."""
    honorifics = _LEGACY_TITLES | set(_LEXICON.titles)
    kept = [t for t in title.split() if t.lower().rstrip(".") not in honorifics]
    return " ".join(kept)


def _clean_name(s: str | None) -> str:
    """Strip (…)-nicknames and collapse whitespace."""
    if not s:
        return ""
    return _WS_RE.sub(" ", _PAREN_RE.sub("", s)).strip()


def _person_parts(s: str) -> tuple[str, str, str]:
    """(first, middles, family) from any display or inverted string.

    Repairs for the corpus's shapes: a wholly dotted given block read as a
    structural title ('Th. Rasing', 'Md. Kamruzzaman') re-reads as given
    initials (real honorifics stay titles); a display form whose surname is
    a degree acronym ('Fei Meng' — MENG) gets it back from the suffix
    field; a string with no family field at all lands whole in family
    (mononyms 'Beyza'/'S.M.', all-title misparses 'Bob.')."""
    p = _PARSE(s)
    family = p.family
    first, middles = p.given, p.middle
    if p.title and _DOTTED_RE.fullmatch(p.title):
        first = " ".join(x for x in (_initials_from_title(p.title), first) if x)
    if not family and p.suffix and "," not in s:
        family = p.suffix
    if not family:
        family = f"{first} {middles}".strip() or p.title
        first = middles = ""
    return first, middles, family


def _parsed_given(first: str | None) -> str:
    """Honorifics and (…)-nicknames out of a CERIF given block, parsed in
    isolation; dotted non-honorific titles ('Md.') fold back in. The
    family side comes from its own field. A lone block's tail tokens
    ('Jan AGM', 'dr. J.B.F.') land in the parse's family field and are
    collected back into the given block."""
    p = _PARSE(_clean_name(first or ""))
    g = " ".join(x for x in (p.given, p.middle, p.family, p.suffix) if x)
    if p.title and _DOTTED_RE.fullmatch(p.title):
        g = " ".join(x for x in (_initials_from_title(p.title), g) if x)
    return g


def decompose_parts(first: str | None, family: str | None) -> NameForms:
    """Structured forms from explicit (first_names, family_names) fields
    (pure CERIF): the family side is atomic — particles and multi-token
    married names stay whole, it is never re-split — while the given block
    may be initials ("F.G.S."), full ("Jeroen Bernard François"), mixed
    ("Jan AGM"), or carry honorifics ("dr. J.B.F.") and nicknames
    ("Christiaan (Chrit)") which the parser strips."""
    return _name_forms(_parsed_given(first), family or "")


def split_person_name(display: str | None) -> tuple[str, str, str]:
    """'First [Middles] Last' or 'Family, First' -> (first, middles, family).

    nameparser-backed: particles stay attached to the family name in
    either arrangement ("Kees de Vries", "Erp, J.B.F. van"); honorifics,
    suffixes and (…)-nicknames come off; CJK names parse family-first.
    Punctuation inside a field is preserved; every downstream key folds
    it away."""
    s = _clean_name(display)
    if not s:
        return "", "", ""
    return _person_parts(s)


def split_inverted_name(s: str | None) -> tuple[str, str] | None:
    """'Family, First' -> (first, family); None when there is no comma.

    The family side may lead with a particle ('von Stackelberg, Oyunbileg'
    stays one surname), and a trailing particle or honorific after the
    given block lands on the right side ('Erp, dr. J.B.F. van' ->
    ('J.B.F.', 'van Erp'))."""
    s = _clean_name(s)
    if not s or "," not in s:
        return None
    first, middles, family = _person_parts(s)
    return f"{first} {middles}".strip(), family


def initial_of(first: str | None) -> str:
    """First alphabetic char of the first-name block ('C.H.' -> 'c')."""
    for ch in first or "":
        if ch.isalpha():
            return ch.lower()
    return ""


# ── CJK-surname guard ──────────────────────────────────────────────────────

CJK_SURNAMES = frozenset(
    {
        "yang",
        "yi",
        "zhang",
        "zhao",
        "zhu",
        "zhou",
        "zhuang",
        "zhun",
        "zhuo",
        "zhuy",
        "chen",
        "cheng",
        "liu",
        "yuan",
        "wang",
        "bu",
        "feng",
        "fu",
        "gu",
        "guo",
        "hao",
        "hu",
        "jia",
        "jiang",
        "jie",
        "jin",
        "jing",
        "li",
        "xiao",
        "xu",
        "wu",
        "lin",
        "ying",
    }
)


def cjk_guard(family: str | None, first: str | None) -> bool:
    """True when surname or forename is a common CJK surname: name-only and
    last-only evidence is discarded for these (too many homonyms)."""
    fam = split_person_name(family)[2] if family else ""
    fore = (first or "").split(" ")[0]
    return bool(
        (fam and norm_text(fam) in CJK_SURNAMES) or (fore and norm_text(fore) in CJK_SURNAMES)
    )


def decompose_name(name: str | None) -> NameForms:
    """Structured forms from any external author display string: inverted
    "Family, First" or display "First [Middles] Last", particle-aware,
    parsed by nameparser."""
    if not name:
        return _name_forms("", "")
    s = _clean_name(name)
    inverted = split_inverted_name(s)
    if inverted is not None:
        first, family = inverted
    else:
        first, middles, family = split_person_name(s)
        first = f"{first} {middles}".strip()
    return _name_forms(first, family)


#: name-fuzzy-strict floor on the Levenshtein InDel ratio of the TIGHT
#: initials+family form ("jbfvanerp"): one missing middle initial on 7+
#: char forms passes ("jbfvanerp" vs "jbvanerp" 0.94), a single-initial
#: substitution never does ("jwang" vs "wwang" 0.80) — the floor is
#: calibrated to python-Levenshtein's ratio (substitution counts 2).
FUZZY_RATIO_FLOOR = 0.92
