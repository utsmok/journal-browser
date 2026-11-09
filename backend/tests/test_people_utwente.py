"""people.utwente.nl harvest: pure parsing/matching transforms.

Tiles, profile pages, the portal-uuid oracle, portrait sniffing, name
tiers, and org resolution — no DB, no network."""

from journal_browser.harvest.people_utwente import (
    MAX_AVATAR_BYTES,
    name_match_tier,
    parse_profile,
    parse_tiles,
    portal_uuid,
    resolve_org_uuids,
    sniff_image,
    tile_clean_name,
    tile_common_name,
)

TILE_HTML = """
<div class="ut-person-tile" data-link="j.jong">
  <button class="ut-person-accordionheader" type="button">
    <img src="/.wh/ea/uc/x/f-2021.avif" class="ut-person-tile__image" alt=""/>
    <div class="ut-person-tile__names">
      <h3 class="ut-person-tile__title">Jong, J.J. de (Jan)</h3>
      <div class="ut-person-tile__roles">Associate Professor</div>
    </div>
  </button>
  <div class="ut-person-tile__specs">
    <div class="ut-person-tile__orgs"><div>EEMCS-DMMP</div></div>
  </div>
</div>
<div class="ut-person-tile" data-link="a.other">
  <h3 class="ut-person-tile__title">Other, A.</h3>
</div>
"""

PROFILE_HTML = """
<html><body>
<h1 class="pageheader__title">dr. J.J. de Jong
<span class="pageheader__title__suffix"> (Jan)</span></h1>
<a href="mailto:j.jong@utwente.nl">j.jong@utwente.nl</a>
<div class="widget-linklist--smallicons">
  <a href="https://www.utwente.nl/en/eemcs"><span class="widget-linklist__text">
    Faculty of Electrical Engineering, Mathematics and Computer Science (EEMCS)</span></a>
  <a href="https://www.utwente.nl/dmmp"><span class="widget-linklist__text">
    Discrete Mathematics and Korteweg-de Vries Instituut (EEMCS-DMMP)</span></a>
  <a href="https://www.utwente.nl/en/techmed"><span class="widget-linklist__text">
    TechMed Centre</span></a>
  <a href="https://research.utwente.nl/en/persons/xyz-uuid">research.utwente.nl profile</a>
  <a href="https://www.linkedin.com/in/janjong">LinkedIn</a>
  <a href="#vcard">Business card (vCard)</a>
</div>
</body></html>
"""


def test_tile_clean_name():
    assert tile_clean_name("Jong, J.J. de (Jan)") == "j j de jong"
    assert tile_clean_name("Knight, L.A. (Louise)") == "l a knight"
    assert tile_clean_name("Alice Author") == "alice author"
    assert tile_clean_name("Boekhout, A.H.") == "a h boekhout"


def test_tile_common_name():
    assert tile_common_name("Jong, J.J. de (Jan)") == "jan"
    assert tile_common_name("Other, A.") is None


def _tile(name: str, common: str | None = None) -> dict:
    return {
        "name": name,
        "name_clean": tile_clean_name(name),
        "common_name": common,
    }


def test_name_match_tier_exact_both_orders():
    author_key, author_rev = "jan de jong", "de jong jan"
    assert name_match_tier(author_key, author_rev, _tile("Jong, Jan de")) == 2
    assert name_match_tier(author_key, author_rev, _tile("de Jong, Jan")) == 2


def test_name_match_tier_initials_with_particles():
    # "Jan de Jong" vs tile "J.J. de (Jan)": initials tier; the common
    # name "jan" equals the author's first token, so the match stands.
    author_key, author_rev = "jan de jong", "de jong jan"
    assert name_match_tier(author_key, author_rev, _tile("Jong, J.J. de (Jan)", "jan")) == 1


def test_name_match_tier_initials_prefix_of_tile():
    # Tile may carry middle initials the roster name lacks.
    author_key, author_rev = "jan de jong", "de jong jan"
    assert name_match_tier(author_key, author_rev, _tile("Jong, J.M. de")) == 1


def test_name_match_tier_common_name_mismatch_blocks():
    # Initials "jj" alone would match any J.; the tile's common name
    # names someone else ("joke"), so no match.
    author_key, author_rev = "jan de jong", "de jong jan"
    assert name_match_tier(author_key, author_rev, _tile("Jong, J.J. de (Joke)", "joke")) == 0


def test_name_match_tier_wrong_surname_or_initials():
    author_key, author_rev = "jan de jong", "de jong jan"
    assert name_match_tier(author_key, author_rev, _tile("Jansen, J.J. de")) == 0
    assert name_match_tier(author_key, author_rev, _tile("Jong, T. de")) == 0


def test_portal_uuid():
    assert portal_uuid("https://research.utwente.nl/en/persons/abc-123") == "abc-123"
    assert portal_uuid("https://research.utwente.nl/en/persons/abc-123/") == "abc-123"
    assert portal_uuid(None) is None


def test_sniff_image():
    assert sniff_image(b"\x89PNG\r\n\x1a\n" + b"x" * 8) == "image/png"
    assert sniff_image(b"\xff\xd8\xff\xe0" + b"x" * 8) == "image/jpeg"
    assert sniff_image(b"\x00\x00\x00\x20ftypavif\x00\x00\x00\x00") == "image/avif"
    assert sniff_image(b"<html>") is None
    assert MAX_AVATAR_BYTES == 1_000_000


def test_parse_tiles():
    tiles = parse_tiles(TILE_HTML)
    assert len(tiles) == 2
    jan = tiles[0]
    assert jan["slug"] == "j.jong"
    assert jan["name_clean"] == "j j de jong"
    assert jan["common_name"] == "jan"
    assert jan["url"].endswith("/j.jong")
    assert jan["photo_url"].endswith("f-2021.avif")
    assert jan["org_abbrs"] == ["EEMCS-DMMP"]
    assert tiles[1]["common_name"] is None


def test_parse_profile():
    profile = parse_profile(PROFILE_HTML, {"slug": "j.jong", "name": "Jong, J.J. de (Jan)"})
    assert profile["slug"] == "j.jong"
    assert profile["canonical_name"] == "dr. J.J. de Jong (Jan)"
    assert profile["email"] == "j.jong@utwente.nl"
    # Faculty row first; institutes stay in the display list.
    assert profile["orgs"][0] == {
        "name": "Faculty of Electrical Engineering, Mathematics and Computer Science",
        "abbr": "EEMCS",
    }
    assert profile["faculty_abbr"] == "EEMCS"
    assert {"name": "TechMed Centre", "abbr": None} in profile["orgs"]
    assert {"name": "Business card (vCard)", "abbr": "vCard"} not in profile["orgs"]
    assert len(profile["orgs"]) == 3
    assert profile["portal_person_url"] == "https://research.utwente.nl/en/persons/xyz-uuid"
    assert portal_uuid(profile["portal_person_url"]) == "xyz-uuid"


def test_resolve_org_uuids_ambiguous_and_missing():
    from journal_browser.harvest.pure_portal import name_key

    dept = "Discrete Mathematics and Korteweg-de Vries Instituut"
    candidates = {name_key(dept): ["org-1"]}
    bare = {name_key("TechMed Centre"): ["org-2"]}
    resolved = resolve_org_uuids(
        [
            {"name": dept, "abbr": "EEMCS-DMMP"},
            {"name": "TechMed Centre", "abbr": None},
            {"name": "Not In The Tree", "abbr": None},
        ],
        candidates,
        bare,
        org_aliases={},
    )
    assert resolved == {dept: "org-1", "TechMed Centre": "org-2"}
