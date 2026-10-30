"""Work-anchored author identity cascade — ported from ut-metadata's
core_authors.py (the deterministic rungs and aggregation, OpenAlex slot
only: journal-browser stores no Crossref/OpenAIRE work-level author
lists).

Owner ruling carried over: soft ids only, deterministic work-scoped
cascade — orcid-exact > name-exact (norm_text full name, unique on the
work) > name-initials (canonical initials+family forms equal, spaced or
tight — pure "J.B.F. van Erp" vs openalex "Jeroen Bernard François van
Erp" both fold to "j b f van erp") > family-unique (family form hits
exactly one external entry AND no other pure author on the work shares
it) > name-fuzzy-strict (family forms equal AND InDel ratio of the tight
initials+family form >= FUZZY_RATIO_FLOOR). Ambiguous or unmatched stays
None; no cross-work fuzzy merging — aggregation across a person's works
only ranks methods and counts conflicting distinct external ids (most
frequent stored). The pure-side ORCID comes from the pure person record,
never from the work author entry.
"""

from collections import Counter
from typing import Any, NamedTuple

from Levenshtein import ratio as levenshtein_ratio

from .author_names import (
    FUZZY_RATIO_FLOOR,
    NameForms,
    bare_orcid,
    cjk_guard,
    decompose_name,
    decompose_parts,
    norm_text,
)

METHOD_ORCID = "orcid-exact"
METHOD_NAME = "name-exact"
METHOD_INITIALS = "name-initials"
METHOD_FAMILY = "family-unique"
METHOD_FUZZY = "name-fuzzy-strict"
#: higher rank wins when one person's works hit different methods
_RANK = {
    METHOD_FUZZY: 1,
    METHOD_FAMILY: 2,
    METHOD_INITIALS: 3,
    METHOD_NAME: 4,
    METHOD_ORCID: 5,
}
#: public alias (the local source adapter picks each author's primary id
#: by this ranking)
METHOD_RANK = _RANK


class ExtEntry(NamedTuple):
    """One external author entry from a work payload (id None = no A-id)."""

    id: str | None
    name: str | None
    orcid: str | None


class PureAuthor(NamedTuple):
    """One pure-side author of a work (CERIF contributor entry)."""

    uuid: str
    first: str
    family: str


def pure_authors_of(cerif_authors: list[dict[str, Any]], root_orgs: set[str]) -> list[PureAuthor]:
    """Institution-affiliated cerif authors of one work.

    An author's affiliation_id must resolve to an org whose closure
    reaches the institution root (root_orgs = the uuids that pass — built
    by the caller from pure_orgs + parents). The flattened primary
    affiliation is the fallback when the affiliations list is empty."""
    out: list[PureAuthor] = []
    for a in cerif_authors or []:
        pid = a.get("person_id")
        if not pid:
            continue
        affs = a.get("affiliations") or [{"affiliation_id": a.get("affiliation_id")}]
        if not any(af.get("affiliation_id") in root_orgs for af in affs):
            continue
        uuid = pid.rsplit("/", 1)[-1]
        out.append(
            PureAuthor(
                uuid,
                a.get("first_names") or "",
                a.get("family_names") or "",
            )
        )
    return out


def openalex_entries(authorships: list[dict[str, Any]]) -> list[ExtEntry]:
    """External entries from one work's authorships.

    Accepts both the stored compact form ({a, n, o}) and raw OpenAlex
    authorships ({author: {id, display_name, orcid}}). Entries may carry
    author.id None (known-author authorships never assigned an A-id) —
    they still match by orcid/name; the stored id stays None for them
    (nothing to collect)."""
    out: list[ExtEntry] = []
    for sh in authorships or []:
        a = sh.get("author") or sh
        if not isinstance(a, dict):
            continue
        aid = (a.get("id") or a.get("a") or "").rsplit("/", 1)[-1] or None
        name = a.get("display_name") or a.get("name") or a.get("n")
        orcid = a.get("orcid") or a.get("o")
        if not name and not orcid:
            continue
        out.append(ExtEntry(aid, name, bare_orcid(orcid)))
    return out


def _uniq_key(e: ExtEntry) -> str:
    """Uniqueness key of an external entry: its id, else its normal name
    (two same-name id-less entries are ambiguous)."""
    return e.id or f"n:{norm_text(e.name)}"


def match(
    author: PureAuthor,
    entries: list[ExtEntry],
    pure_orcid: str | None,
    peer_families: set[str],
) -> tuple[ExtEntry | None, str | None]:
    """Deterministic cascade for one pure author against one work's list.

    Returns (entry, method); (None, None) when ambiguous or unmatched."""
    pf = decompose_parts(author.first, author.family)
    exact = norm_text(f"{author.first} {author.family}")
    fam_ok = len(pf.family_only) > 1  # a lone-letter "family" is a parse artifact
    # CJK guard (ported from entity_match's §12 lesson): surname-only and
    # fuzzy evidence is far too weak on CJK homonyms ("Wei Wang" vs "Wu
    # Wang") — only orcid/full-name/initials-forms evidence may decide.
    weak_ok = fam_ok and not cjk_guard(author.family, author.first)
    parsed = [(e, decompose_name(e.name)) for e in entries]

    def _orcid(e: ExtEntry, _f: NameForms) -> bool:
        return bool(pure_orcid) and e.orcid == pure_orcid

    def _name(e: ExtEntry, _f: NameForms) -> bool:
        return bool(e.name) and norm_text(e.name) == exact

    def _initials(e: ExtEntry, f: NameForms) -> bool:
        return bool(pf.initials_forms & f.initials_forms)

    def _family(e: ExtEntry, f: NameForms) -> bool:
        return weak_ok and f.family == pf.family and pf.family_only not in peer_families

    def _fuzzy(e: ExtEntry, f: NameForms) -> bool:
        return (
            weak_ok
            and f.family == pf.family
            and bool(pf.initials_family_tight)
            and bool(f.initials_family_tight)
            and levenshtein_ratio(pf.initials_family_tight, f.initials_family_tight)
            >= FUZZY_RATIO_FLOOR
        )

    rungs: list[tuple[str, Any]] = [
        (METHOD_ORCID, _orcid),
        (METHOD_NAME, _name),
        (METHOD_INITIALS, _initials),
        (METHOD_FAMILY, _family),
        (METHOD_FUZZY, _fuzzy),
    ]
    for method, hit in rungs:
        hits = [e for e, _f in parsed if hit(e, _f)]
        if len({_uniq_key(e) for e in hits}) == 1:
            return hits[0], method
    return None, None


def aggregate(outcomes: list[tuple[ExtEntry, str]]) -> tuple[ExtEntry, str, int] | None:
    """Best outcome across a person's works: best method rank first, most
    frequent id within it (ties break lexicographically), conflicts =
    distinct other ids seen anywhere."""
    if not outcomes:
        return None
    best = max(_RANK[m] for _, m in outcomes)
    top = [o for o in outcomes if _RANK[o[1]] == best]
    counts = Counter(e.id for e, _ in top)
    # id-bearing beats id-less at equal rank+count (a stored A-id is
    # strictly more useful than orphan evidence)
    chosen_id = min(counts, key=lambda k: (-counts[k], k is None, str(k)))
    chosen = next(e for e, _ in top if e.id == chosen_id)
    conflicts = len({e.id for e, _ in outcomes} - {chosen_id} - {None})
    method = next(m for e, m in top if e.id == chosen_id)
    return chosen, method, conflicts
