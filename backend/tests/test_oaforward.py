"""OA Forward registry: an institution's own agreements."""

from datetime import date

from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.oaforward import (
    NO_JOURNALS_REASON,
    _store_agreement,
    parse_agreement_page,
    parse_registry,
)
from journal_browser.harvest.reconcile import reconcile_deals
from journal_browser.models import Deal, DealInstitution, Institution, Publisher

# The table of https://oaforward.org/community-resources/agreement-registry/acm2021utwente/
# (live 2026-11), trimmed to the row shapes the page uses.
PAGE = """
<table><tbody>
<tr><td>Publisher</td><td><h2>Association for Computing Machinery</h2></td></tr>
<tr><td>Agreement ID</td><td>acm2021utwente</td></tr>
<tr><td>Has the agreement been disclosed and published?</td><td>No</td></tr>
<tr><td>Agreement period</td><td>01/01/2021 &#8211; 12/31/2025</td></tr>
<tr><td><strong>SIZE</strong><p>Approximate range of annual corresponding author
publications</p></td><td>40</td></tr>
<tr><td>Are fully open access journals covered by the agreement?</td><td>Yes</td></tr>
<tr><td><strong>OA LICENSE</strong></td><td>CC BY preference, exceptions allowed</td></tr>
<tr><td><strong>ARTICLE TYPES<br/></strong></td>
<td>Original research articles<br/>Review articles<br/>Proceedings</td></tr>
<tr><td>Request contact to the licensee</td><td><a href="mailto:x@y">x@y</a></td></tr>
</tbody></table>
"""

FETCHED = "2026-11-26T00:00:00+00:00"
TODAY = date(2026, 11, 26)
NO_PAGE = {"conditions_text": None, "article_types_text": None}


def _agreement(esac_id, publisher, start, end):
    return parse_registry(
        [
            {
                "Publisher": publisher,
                "Consortium / Institution": "University of Twente",
                "Start date": start,
                "End date": end,
                "Labeling": "Read and Publish agreement",
                "Agreement ID": esac_id,
                "Link to agreement page": f"https://oaforward.org/x/{esac_id}/",
            }
        ]
    )[0]


def test_agreement_page_keeps_the_terms_and_drops_the_index_fields():
    page = parse_agreement_page(PAGE)
    assert page["article_types_text"] == "Original research articles\nReview articles\nProceedings"
    assert page["conditions_text"] == (
        "Has the agreement been disclosed and published?: No\n"
        "Approximate range of annual corresponding author publications: 40\n"
        "Are fully open access journals covered by the agreement?: Yes\n"
        "OA license: CC BY preference, exceptions allowed"
    )


@requires_db
async def test_local_agreement_stays_separate_from_the_national_deal(db):
    ut = Institution(
        name="University of Twente", ror="https://ror.org/006hf6230", code="ut", active=True
    )
    iop = Publisher(name="IOP Publishing", openaccess_nl_slug="iop-publishing")
    rsc = Publisher(name="Royal Society of Chemistry (RSC)", openaccess_nl_slug="rsc")
    db.add_all([ut, iop, rsc])
    await db.flush()
    # The national IOP deal of the same years, as openaccess.nl lists it.
    national = Deal(
        publisher_id=iop.id,
        status="archive",
        start_year=2020,
        end_year=2022,
        duration_text="2020-2022",
        openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/iop-2020-2022",
        provenance=[],
    )
    db.add(national)
    await db.flush()

    local = await _store_agreement(
        db,
        _agreement("iop2020utwente", "IOP Publishing", "1/1/2020", "12/31/2022"),
        parse_agreement_page(PAGE),
        ut.id,
        TODAY,
        FETCHED,
    )
    current = await _store_agreement(
        db,
        _agreement("trs2026utwente", "The Royal Society", "1/1/2026", "12/31/2027"),
        NO_PAGE,
        ut.id,
        TODAY,
        FETCHED,
    )
    await db.commit()

    assert (local.status, local.start_year, local.end_year) == ("archive", 2020, 2022)
    assert local.publisher_id == iop.id and local.consortium == "utwente"
    assert local.needs_curation is False
    # A current agreement without journals waits for its list, and "The
    # Royal Society" is not the Royal Society of Chemistry.
    assert current.needs_curation and current.needs_curation_reason == NO_JOURNALS_REASON
    assert current.publisher_id != rsc.id
    participation = await db.scalar(
        select(DealInstitution.participation).where(DealInstitution.deal_id == local.id)
    )
    assert participation == "named"

    await reconcile_deals(db)
    national = await db.get(Deal, national.id)
    assert national.esac_id is None
    assert await db.scalar(select(Deal.id).where(Deal.esac_id == "iop2020utwente")) == local.id
