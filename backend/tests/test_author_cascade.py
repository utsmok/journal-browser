"""Author identity cascade + name forms — ported from ut-metadata's
tests/test_core_author_links.py fixtures (the "J.B.F. van Erp"-class cases
that justify each rung). Pure unit tests: the rungs' semantics live here,
the DB walk lives in test_author_ids.py."""

from journal_browser.harvest.author_cascade import (
    METHOD_FAMILY,
    METHOD_INITIALS,
    METHOD_NAME,
    METHOD_ORCID,
    PureAuthor,
    aggregate,
    match,
)
from journal_browser.harvest.author_names import (
    decompose_name,
    decompose_parts,
    norm_text,
)

ORCID_P1 = "0000-0001-7295-651x"


def _oa(aid: str | None, name: str | None, orcid: str | None = None):
    from journal_browser.harvest.author_cascade import ExtEntry

    return ExtEntry(aid, name, bare_orcid(orcid))


def bare_orcid(value):
    from journal_browser.harvest.author_names import bare_orcid as b

    return b(value)


# ── name decomposition (shared ladder forms) ──────────────────────────────


def test_decompose_inverted_and_display_forms():
    """Inverted "Family, First" and display "First ... Last" both yield the
    same structured record and the four canonical forms."""
    inv = decompose_name("van Erp, J.B.F.")
    assert (inv.family, inv.initials) == (("van", "erp"), ("j", "b", "f"))
    assert inv.initials_forms == {"j b f van erp", "jbf van erp"}
    assert inv.full == ""  # initials-only side has no full form
    disp = decompose_name("Jeroen Bernard François van Erp")
    assert disp.initials_forms == inv.initials_forms  # the big-bucket bridge
    assert disp.full == "jeroen bernard francois van erp"
    assert disp.first_initial_family == "j van erp"
    assert disp.family_only == "van erp"


def test_decompose_particles_hyphens_diacritics_caps_titles():
    assert decompose_name("Erp, J.B.F. van").family == ("van", "erp")
    assert decompose_parts("dr. J.B.F.", "van Erp").initials == ("j", "b", "f")
    assert (
        decompose_name("Jean-Pierre Dupont").initials_forms
        == decompose_name("Dupont, J.-P.").initials_forms
    )
    assert (
        decompose_name("Stéphanie M. van den Berg").initials_forms
        == decompose_parts("S.M.", "van den Berg").initials_forms
    )
    assert decompose_name("Jan AGM van Dijk").initials == ("j", "a", "g", "m")
    # CERIF family field is atomic: multi-token families are never re-split
    assert decompose_parts("Gema", "Albort Morant").family == ("albort", "morant")
    assert decompose_parts("Michel", "Klein Gunnewiek").family_only == "klein gunnewiek"
    # nicknames come out of the CERIF given block
    assert decompose_parts("Christiaan (Chrit)", "Brouwer").given == ("christiaan",)


def test_norm_text_and_orcid_forms():
    assert norm_text("Van Erp, J.B.F.") == "vanerpjbf"
    from journal_browser.harvest.author_names import bare_orcid, bare_ror

    assert bare_orcid("https://orcid.org/0000-0002-1825-0097") == "0000-0002-1825-0097"
    assert bare_orcid("0000-0002-1825-009X") == "0000-0002-1825-009x"
    assert bare_ror("https://ror.org/006hf6230") == "006hf6230"


# ── cascade rungs (one work's lists, ut-metadata fixture shapes) ──────────


def test_cascade_orcid_beats_name():
    """orcid-exact wins over an exact-name match on a different entry."""
    author = PureAuthor("p1", "Mandy", "Velthuis")
    entries = [
        _oa("A111", "Mandy Velthuis"),
        _oa("A222", "M. Velthuis", ORCID_P1.upper()),  # payload case folds
    ]
    entry, method = match(author, entries, ORCID_P1, set())
    assert entry is not None and entry.id == "A222"
    assert method == METHOD_ORCID


def test_name_initials_rung():
    """Initial-form external name misses name-exact, hits the initials form."""
    author = PureAuthor("p1", "Anneke", "de Vries")
    entry, method = match(author, [_oa("A333", "A. de Vries")], None, set())
    assert entry is not None and entry.id == "A333"
    assert method == METHOD_INITIALS


def test_name_initials_big_bucket():
    """The measured 78% bucket: pure initials vs external full first names
    both fold to "j b f van erp" and link without any orcid."""
    author = PureAuthor("p2", "J.B.F.", "van Erp")
    entries = [_oa("A777", "Jeroen Bernard François van Erp"), _oa("A778", "Wei Wang")]
    entry, method = match(author, entries, None, set())
    assert entry is not None and entry.id == "A777"
    assert method == METHOD_INITIALS


def test_family_unique_rung():
    """Family form alone links when it hits exactly one external entry and
    no other pure author on the work shares it. (Non-CJK family: the CJK
    guard blocks this rung for CJK surnames — see the guard test below.)"""
    author = PureAuthor("p1", "L.", "Maas")
    entries = [_oa("A888", "Wei Wang"), _oa("A889", "Anna Maas")]
    entry, method = match(author, entries, None, set())
    assert entry is not None and entry.id == "A889"
    assert method == METHOD_FAMILY


def test_family_unique_blocked_by_pure_peer():
    """Two same-family pure authors on one work: family-unique stays silent
    for both (the caller passes the peer family set)."""
    author = PureAuthor("p1", "L.", "Bakker")
    entries = [_oa("A888", "Anouk Bakker")]
    entry, _method = match(author, entries, None, {"bakker"})
    assert entry is None


def test_name_fuzzy_strict_rung():
    """One missing middle initial on the tight initials+family form is
    within the 0.92 floor; the disagreeing-initial twin does not fire."""
    author = PureAuthor("p1", "J.B.F.", "van Erp")
    entries = [_oa("A910", "Jeroen Bernard van Erp"), _oa("A911", "K. van Erp")]
    entry, method = match(author, entries, None, set())
    assert entry is not None and entry.id == "A910"
    assert method == "name-fuzzy-strict"


def test_fuzzy_rejects_initial_substitution():
    """A differing first initial is never within distance ("jwang" vs
    "wwang" 0.80 < 0.92); two same-family externals also block the
    family-unique rung, so the slot stays unmatched. (Wang is a CJK
    surname: the guard blocks both rungs regardless — the ratio assertion
    below pins the calibrated floor itself.)"""
    author = PureAuthor("p1", "J.", "Wang")
    entries = [_oa("A920", "Wei Wang"), _oa("A921", "Wu Wang")]
    entry, method = match(author, entries, None, {"wang"})
    assert entry is None
    assert method is None
    from Levenshtein import ratio

    assert round(ratio("jbfvanerp", "jbvanerp"), 2) == 0.94
    assert round(ratio("jwang", "wwang"), 2) == 0.8


def test_cjk_guard_blocks_family_and_fuzzy_evidence():
    """CJK homonyms: family-unique and fuzzy evidence never decide (the
    §12 lesson); only orcid/full-name/initials-forms evidence stays live."""
    # Family-unique would fire ("wang" hits exactly one external entry).
    author = PureAuthor("p1", "L.", "Wang")
    entry, method = match(author, [_oa("A888", "Wei Wang"), _oa("A889", "Anna Maas")], None, set())
    assert entry is None and method is None
    # Fuzzy would fire (tight forms "jwzhang"/"jzhang" ratio 0.92 >= floor).
    fuzzy = PureAuthor("p1", "J.W.", "Zhang")
    entry, method = match(fuzzy, [_oa("A890", "Jian Zhang")], None, set())
    assert entry is None and method is None
    # Full-name evidence stays live for CJK names.
    exact = PureAuthor("p1", "Wei", "Wang")
    entry, method = match(exact, [_oa("A891", "Wei Wang")], None, set())
    assert entry is not None and method == METHOD_NAME
    # Initials-forms evidence stays live too (the big-bucket bridge).
    initials = PureAuthor("p1", "J.", "Wang")
    entry, method = match(initials, [_oa("A892", "Jian Wang")], None, set())
    assert entry is not None and method == METHOD_INITIALS


def test_initials_beats_family_unique_precedence():
    """The initials rung labels the link even when the family form would
    also have been unique in the external list."""
    author = PureAuthor("p1", "Jeroen", "van Erp")
    entries = [_oa("A930", "J. van Erp"), _oa("A931", "Wei Wang")]
    entry, method = match(author, entries, None, set())
    assert entry is not None and entry.id == "A930"
    assert method == METHOD_INITIALS


def test_genuinely_absent_author_stays_unmatched():
    """A pure author absent from the external list must stay unmatched —
    no rung invents a link."""
    author = PureAuthor("p1", "J.B.F.", "van Erp")
    entries = [_oa("A940", "Wei Wang"), _oa("A941", "Bo Li"), _oa("A942", "Anna Maas")]
    entry, method = match(author, entries, None, set())
    assert entry is None
    assert method is None


def test_ambiguous_stays_unmatched():
    """Two same-family-same-initial external entries: the initials rung is
    not unique, so no match."""
    author = PureAuthor("p1", "Michael", "Velthuis")
    entries = [_oa("A444", "M. Velthuis"), _oa("A555", "Max Velthuis")]
    entry, method = match(author, entries, None, set())
    assert entry is None
    assert method is None


def test_idless_entry_matches_by_name_but_stores_no_id():
    """An authorship with no A-id still matches by name; the matched entry
    carries id None (nothing to collect)."""
    author = PureAuthor("p1", "Mandy", "Velthuis")
    entries = [_oa(None, "Mandy Velthuis"), _oa("A999", "M. Velthuis")]
    entry, method = match(author, entries, None, set())
    assert entry is not None and entry.id is None
    assert method == METHOD_NAME


def test_aggregate_prefers_id_bearing_at_equal_rank():
    """Equal rank + equal count: an id-bearing outcome beats an id-less one
    (a stored A-id is strictly more useful than orphan evidence). Rank
    still dominates: a better-ranked id-less outcome wins outright."""
    tie = [
        (_oa(None, "Mandy Velthuis"), METHOD_NAME),
        (_oa("A999", "M. Velthuis"), METHOD_NAME),
    ]
    agg = aggregate(tie)
    assert agg is not None
    chosen, method, conflicts = agg
    assert chosen is not None and chosen.id == "A999"
    assert method == METHOD_NAME
    assert conflicts == 0  # the id-less entry adds no conflict
    outranked = [
        (_oa(None, "Mandy Velthuis"), METHOD_NAME),
        (_oa("A999", "M. Velthuis"), METHOD_INITIALS),
    ]
    agg = aggregate(outranked)
    assert agg is not None
    chosen, method, _conflicts = agg
    assert chosen is not None and chosen.id is None
    assert method == METHOD_NAME


# ── aggregation across works ──────────────────────────────────────────────


def test_cross_work_conflict_counting():
    """Work 1 links A111 by orcid-exact, work 2 links A999 by name-exact:
    orcid-exact wins, the other distinct id counts as a conflict."""
    outcomes = [
        (_oa("A111", "M. Velthuis", ORCID_P1), METHOD_ORCID),
        (_oa("A999", "Mandy Velthuis"), METHOD_NAME),
    ]
    agg = aggregate(outcomes)
    assert agg is not None
    chosen, method, conflicts = agg
    assert chosen is not None and chosen.id == "A111"
    assert method == METHOD_ORCID
    assert conflicts == 1


def test_aggregate_most_frequent_id_and_ties():
    """Equal rank: the most frequent id wins, ties break lexicographic,
    id-bearing beats id-less."""
    outcomes = [
        (_oa("A2", "X Y"), METHOD_NAME),
        (_oa("A1", "X Y"), METHOD_NAME),
        (_oa("A1", "X Y"), METHOD_NAME),
    ]
    agg = aggregate(outcomes)
    assert agg is not None
    chosen, _method, conflicts = agg
    assert chosen.id == "A1"
    assert conflicts == 1
    assert aggregate([]) is None
