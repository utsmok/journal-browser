"""Pure portal org-tree harvest: RSS parsing, name matching, and the
apply contract (fill gaps only, institutes pinned, partners untouched)."""

from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.pure_portal import (
    apply_portal_tree,
    classification_to_type,
    name_key,
    parse_portal_feed,
    walk_portal_orgs,
)
from journal_browser.ingest import IngestSession
from journal_browser.models import PureOrg, PureOrgParent

EEMCS = "Faculty of Electrical Engineering, Mathematics and Computer Science"

_ITEM = """<item>
  <title>{name}</title>
  <link>https://research.utwente.nl/en/organisations/{slug}/</link>
  <description>{description}</description>
</item>"""

_RELATIONS = (
    "&lt;p class=&quot;relations&quot;&gt;&lt;a rel=&quot;Organisation&quot; "
    "href=&quot;https://research.utwente.nl/en/organisations/{parent_slug}/&quot; "
    "class=&quot;link organisation&quot;&gt;&lt;span&gt;{parent_name}&lt;/span&gt;"
    "&lt;/a&gt;&lt;/p&gt;"
)


def _item(
    name: str, slug: str, classification: str, parent_slug: str | None, parent_name: str | None
) -> str:
    description = (
        "&lt;p class=&quot;type&quot;&gt;&lt;span class=&quot;type_classification&quot;&gt;"
        f"{classification}&lt;/span&gt;&lt;/p&gt;"
    )
    if parent_slug:
        description = (
            _RELATIONS.format(parent_slug=parent_slug, parent_name=parent_name) + description
        )
    return _ITEM.format(name=name, slug=slug, description=description)


def _feed() -> str:
    items = "\n".join(
        [
            _item(
                "Stochastic Operations Research",
                "stochastic-operations-research",
                "Department",
                "faculty-of-eemcs-2",
                EEMCS,
            ),
            _item("MESA+ Institute", "mesa-institute-2", "Institute", "ut", "University of Twente"),
            # A hypothetical bad portal layout: DSI nested under EEMCS.
            _item(
                "Digital Society Institute",
                "digital-society-institute-3",
                "Institute",
                "faculty-of-eemcs-2",
                EEMCS,
            ),
            _item("Old Closed Unit", "old-closed-unit", "Department", None, None),
            _item(
                "Mathematics of Imaging &amp; AI",
                "mathematics-of-imaging-ai",
                "Department",
                "faculty-of-eemcs-2",
                EEMCS,
            ),
        ]
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0">'
        f"<channel><title>Research units</title>{items}</channel></rss>"
    )


def test_parse_portal_feed():
    units = parse_portal_feed(_feed())
    assert [u.name for u in units] == [
        "Stochastic Operations Research",
        "MESA+ Institute",
        "Digital Society Institute",
        "Old Closed Unit",
        "Mathematics of Imaging & AI",
    ]
    sor, mesa, dsi, old, moai = units
    assert sor.slug == "stochastic-operations-research"
    assert (sor.parent_slug, sor.parent_name) == ("faculty-of-eemcs-2", EEMCS)
    assert sor.classification == "Department"
    assert (mesa.parent_slug, mesa.parent_name) == ("ut", "University of Twente")
    assert mesa.classification == "Institute"
    assert (dsi.parent_slug, dsi.parent_name) == ("faculty-of-eemcs-2", EEMCS)
    assert old.parent_name is None and old.classification == "Department"
    assert (moai.parent_name, moai.classification) == (EEMCS, "Department")
    payload = sor.payload()
    assert payload["portal_slug"] == sor.slug and payload["parent_name"] == EEMCS


def test_name_key_matching():
    # Diacritics fold; ampersands and plus signs unify with spelled forms.
    assert name_key("Föllmer") == name_key("Follmer")
    assert name_key("Datamanagement & Biometrics") == name_key("Datamanagement and Biometrics")
    assert name_key("MESA+ Institute") == name_key("mesa plus institute")
    assert name_key(None) == ""


def test_classification_to_type():
    assert classification_to_type("Faculty") == "faculty"
    assert classification_to_type("Research Center") == "research_centre"
    assert classification_to_type("institute") == "institute"
    assert classification_to_type("Vice Dean's Office") is None
    assert classification_to_type(None) is None


async def test_walk_portal_orgs_dedupes_until_empty():
    def _channel(items: list[str]) -> bytes:
        body = "".join(items)
        return (
            '<?xml version="1.0" encoding="utf-8"?><rss version="2.0">'
            f"<channel><title>Research units</title>{body}</channel></rss>"
        ).encode()

    pages = [
        _channel(
            [
                _item("Alpha", "a", "Department", None, None),
                _item("Beta", "b", "Department", None, None),
            ]
        ),
        _channel(
            [
                _item("Beta", "b", "Department", None, None),
                _item("Gamma", "c", "Institute", None, None),
            ]
        ),
        _channel([]),
    ]

    async def fetch_page(page: int) -> bytes:
        return pages[page - 1]

    units = await walk_portal_orgs(fetch_page, page_delay=0)
    assert [(u.slug, u.name) for u in units] == [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")]


@requires_db
async def test_apply_portal_tree_contract(db, institution_factory):
    """Edges fill gaps only; institutes stay root-pinned; partners and
    already-parented orgs are untouched; types upgrade on UT-side orgs."""
    inst = await institution_factory(
        code="ut", name="University of Twente", ror="https://ror.org/006hf6230"
    )
    db.add_all(
        [
            PureOrg(
                institution_id=inst.id,
                uuid="ut-root",
                name="University of Twente",
                org_type="university",
            ),
            PureOrg(institution_id=inst.id, uuid="eemcs-uuid", name=EEMCS, org_type="faculty"),
            # Flat: no parent row (the OAI gap the portal repairs).
            PureOrg(institution_id=inst.id, uuid="sor-uuid", name="Stochastic Operations Research"),
            PureOrg(institution_id=inst.id, uuid="moai-uuid", name="Mathematics of Imaging & AI"),
            # Institute, flat: the feed's EEMCS parent must be refused.
            PureOrg(
                institution_id=inst.id,
                uuid="dsi-uuid",
                name="Digital Society Institute",
                org_type="institute",
            ),
            # Institute with the root parent (current live shape).
            PureOrg(
                institution_id=inst.id,
                uuid="mesa-uuid",
                name="MESA+ Institute",
                org_type="institute",
            ),
            PureOrgParent(
                institution_id=inst.id,
                org_uuid="mesa-uuid",
                parent_uuid="ut-root",
                parent_name="University of Twente",
            ),
            # Partner with its own parent: never touched.
            PureOrg(
                institution_id=inst.id,
                uuid="delft-uuid",
                name="Delft University of Technology",
                org_type="university",
            ),
            PureOrgParent(institution_id=inst.id, org_uuid="delft-uuid", parent_uuid="delft-root"),
            PureOrg(institution_id=inst.id, uuid="delft-root", name="Delft"),
            # Flat closed unit without a parent in the feed: no edge.
            PureOrg(institution_id=inst.id, uuid="old-uuid", name="Old Closed Unit"),
        ]
    )
    await db.flush()

    stats = await apply_portal_tree(
        db, inst, parse_portal_feed(_feed()), IngestSession(db), store_payloads=False
    )
    await db.commit()

    assert stats["matched"] == 5
    assert stats["edges_added"] == 2  # SOR + MoAI -> EEMCS
    assert stats["already_parented"] == 1  # MESA+
    assert stats["institute_pinned"] == 1  # DSI
    assert stats["no_parent_in_portal"] == 1  # Old Closed Unit
    assert stats["types_updated"] == 3  # SOR + Old + MoAI -> department
    assert stats["unmatched"] == 0

    parents = {
        row.org_uuid: row.parent_uuid for row in (await db.execute(select(PureOrgParent))).scalars()
    }
    assert parents["sor-uuid"] == "eemcs-uuid"
    assert parents["moai-uuid"] == "eemcs-uuid"
    assert "dsi-uuid" not in parents  # pinned: no parent added
    assert parents["delft-uuid"] == "delft-root"  # untouched
    assert parents["mesa-uuid"] == "ut-root"  # untouched

    orgs = {row.uuid: row.org_type for row in (await db.execute(select(PureOrg))).scalars()}
    assert orgs["sor-uuid"] == "department"
    assert orgs["moai-uuid"] == "department"
    assert orgs["old-uuid"] == "department"
    assert orgs["dsi-uuid"] == "institute"
    assert orgs["mesa-uuid"] == "institute"
    assert orgs["delft-uuid"] == "university"
