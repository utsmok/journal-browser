"""resolve_root's ladder: name match, university fallback, ambiguity, and
the duplicate-root tiebreak (live pure_orgs carried two "University of
Twente" rows; the one other orgs hang under must win so the closure keeps
the whole tree). Pure functions: no database."""

from journal_browser.harvest.org_closure import resolve_root
from journal_browser.models import Institution, PureOrg


def _org(uuid: str, name: str, org_type: str | None = "university") -> PureOrg:
    return PureOrg(institution_id=1, uuid=uuid, name=name, org_type=org_type)


def _inst(name: str = "University of Twente", short: str | None = "UT") -> Institution:
    return Institution(name=name, short_name=short)


def test_duplicate_named_roots_prefer_children():
    # Both roots match the institution name; only one has children. The
    # childless duplicate must not win (else every chain disconnects).
    with_kids, childless, child = "b-root", "a-root", "child"
    orgs = {
        with_kids: _org(with_kids, "University of Twente"),
        childless: _org(childless, "University of Twente"),
        child: _org(child, "MESA+ Institute", "institute"),
    }
    parents = {child: with_kids}
    assert resolve_root(orgs, parents, _inst()) == with_kids


def test_duplicate_named_roots_no_children_still_deterministic():
    orgs = {
        "a-root": _org("a-root", "University of Twente"),
        "b-root": _org("b-root", "University of Twente"),
    }
    # sorted order keeps the pick stable; not None (that would be a silent
    # empty roster for a name-matching pair).
    assert resolve_root(orgs, {}, _inst()) == "a-root"


def test_single_named_root_wins():
    orgs = {"root": _org("root", "University of Twente"), "other": _org("other", "Some U")}
    assert resolve_root(orgs, {"other": "root"}, _inst()) == "root"


def test_short_name_match_wins():
    orgs = {"root": _org("root", "UT")}
    assert resolve_root(orgs, {}, _inst()) == "root"


def test_university_fallback_single_root():
    orgs = {"root": _org("root", "Some University")}
    assert resolve_root(orgs, {}, _inst(name="Unrelated")) == "root"


def test_ambiguous_university_roots_stay_none():
    # No name match and two university-typed roots: refuse rather than
    # guess (degrade loudly, per the module docstring).
    orgs = {"a": _org("a", "Alpha University"), "b": _org("b", "Beta University")}
    assert resolve_root(orgs, {}, _inst(name="Unrelated")) is None


def test_single_root_last_resort():
    orgs = {"root": _org("root", "Anything")}
    assert resolve_root(orgs, {}, _inst(name="Unrelated")) == "root"


def test_no_roots_none():
    assert resolve_root({}, {}, _inst()) is None
