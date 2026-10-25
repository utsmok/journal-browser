"""Parser + upsert tests for the openaccess.nl harvester (live-structure fixtures)."""

from sqlalchemy import func, select

from conftest import requires_db
from journal_browser.harvest.openaccess_nl import (
    _upsert_deal,
    _upsert_publisher,
    parse_deal_page,
    parse_duration,
    parse_overview,
    parse_publisher_page,
)
from journal_browser.models import Deal

OVERVIEW_HTML = """
<html><body>
<div class="tab-content">
  <div class="tab-pane active" id="current"><table><tbody>
    <tr class="row-id-1 row-header">
      <td class="views-field views-field-title" headers="view-title-table-column">
        <a href="/en/publisher/elsevier" hreflang="en">Elsevier</a> </td>
      <td class="views-field views-field-field-inleiding"><p>Summary text.</p> </td>
      <td class="views-field views-field-field-looptijd-deal"> 2025-2027 </td>
      <td class="views-field views-field-nothing"><button class="btn">open</button></td>
    </tr>
  </tbody></table></div>
  <div class="tab-pane" id="prospective"></div>
  <div class="tab-pane" id="archive"><table><tbody>
    <tr class="row-id-2 row-header">
      <td class="views-field views-field-title">
        <a href="/en/publisher/brill">Brill</a> </td>
      <td class="views-field views-field-field-inleiding"><p>Old deal.</p> </td>
      <td class="views-field views-field-field-looptijd-deal"> 2016-2018 </td>
      <td class="views-field views-field-nothing"><button class="btn">open</button></td>
    </tr>
  </tbody></table></div>
</div>
</body></html>
"""

PUBLISHER_HTML = """
<html><body>
<div class="licence-data-item">
<table><tbody>
<tr><th>Deal duration:</th><td>  2025-2027
</td></tr>
<tr><th>
    2025
  </th><td>
    7429
  </td></tr>
<tr><th>
    2026
  </th><td>
    4530
  </td></tr>
<tr><th>Status licence:</th><td> <div class="status-licentie-99">
    Current
  </div>
</td></tr>
</tbody></table>
<a class="licence-data-item__read-more btn btn-sm btn-primary my-4"
   href="/en/publisherdeal/elsevier-2025-2027">Read more</a>
</div>
<div class="licence-data-item">
<table><tbody>
<tr><th>Deal duration:</th><td> 2022-2024 </td></tr>
<tr><th>Status licence:</th><td><div class="status-licentie-98"> Archive </div></td></tr>
</tbody></table>
<a class="licence-data-item__read-more" href="/en/publisherdeal/elsevier-2022-2024">Read more</a>
</div>
</body></html>
"""

DEAL_HTML = """<html><body><article>
<h1>Elsevier (2025-2027)</h1>
<div class="node__content container">
  <div class="body-text">
    <p>No publishing costs for Dutch authors in more than 2200 'hybrid' and full open
    access journals.</p>
  </div>
</div>
<div class="node__content container">
  <div class="body-text">
    <p><em><strong>License and conditions</strong></em></p>
    <ul>
      <li>This agreement is for the period of 2025-2026.</li>
      <li>The agreement applies to the following types of publications: original
      articles, review articles.</li>
      <li>Note: capped deal! The cap for hybrid journals has been reached.</li>
      <li>In 2024, all participants together are allowed to publish a maximum of 733
      articles. In 2025, they are allowed to publish 707 articles, and in 2026, 680.</li>
    </ul>
    <p><em><strong>How does it work?</strong></em></p>
    <ul>
      <li>Indicate in the publication stage of your article that your research is to
      be published open access.</li>
    </ul>
    <p>This
    <a href="https://www.openaccess.nl/sites/default/files/documents/contract.pdf">
    <strong>contract</strong></a> and its
    <a href="https://main-bvxea6i-fus33rfligxco.ch-1.platformsh.site/sites/default/files/contract.pdf">
    duplicate</a> disclose the agreement.</p>
  </div>
</div>
</article></body></html>"""

DEAL_MISSING_SECTIONS_HTML = """<html><body>
<div class="node__content container">
  <div class="body-text">
    <p><em><strong>License and conditions</strong></em></p>
    <ul><li>Only conditions, capped deal with a shared pool of 500 in total for both
    2025 and 2026.</li></ul>
  </div>
</div>
</body></html>"""

DEAL_MARKER_VARIANTS_HTML = """<html><body>
<div class="node__content container">
  <div class="body-text">
    <p>Variant summary.</p>
  </div>
</div>
<div class="node__content container">
  <div class="body-text">
    <p><em><strong>Details and conditions of the licence</strong></em></p>
    <ul><li>AIP conditions line.</li></ul>
    <p><em><strong>License and conditions</strong></em> :</p>
    <ul><li>De Gruyter conditions line.</li></ul>
    <p><em><strong>How does it work?</strong></em></p>
    <ul><li>Workflow line.</li></ul>
  </div>
</div>
</body></html>"""


def test_parse_duration():
    assert parse_duration("2025-2027") == (2025, 2027)
    assert parse_duration("  2025 ") == (2025, 2025)
    assert parse_duration("unknown") == (None, None)
    assert parse_duration(None) == (None, None)


def test_parse_overview_current_and_archive():
    pubs = parse_overview(OVERVIEW_HTML)
    assert pubs == [
        {
            "slug": "elsevier",
            "name": "Elsevier",
            "duration_text": "2025-2027",
            "status": "current",
        },
        {
            "slug": "brill",
            "name": "Brill",
            "duration_text": "2016-2018",
            "status": "archive",
        },
    ]


def test_parse_publisher_page():
    deals = parse_publisher_page(PUBLISHER_HTML)
    assert len(deals) == 2
    current = deals[0]
    assert current["duration_text"] == "2025-2027"
    assert current["start_year"] == 2025
    assert current["end_year"] == 2027
    assert current["per_year_oa_counts"] == {"2025": 7429, "2026": 4530}
    assert current["status"] == "current"
    assert current["deal_path"] == "/en/publisherdeal/elsevier-2025-2027"
    assert deals[1]["status"] == "archive"
    assert deals[1]["per_year_oa_counts"] is None


def _norm(text: str) -> str:
    return " ".join(text.split())


def test_parse_deal_page():
    url = "https://www.openaccess.nl/en/publisherdeal/elsevier-2025-2027"
    page = parse_deal_page(DEAL_HTML, url)
    assert _norm(page["summary"]) == (
        "No publishing costs for Dutch authors in more than 2200 'hybrid' and full "
        "open access journals."
    )
    assert page["conditions_text"] is not None
    assert _norm(page["workflow_text"]).startswith("Indicate in the publication stage")
    assert _norm(page["article_types_text"]) == (
        "The agreement applies to the following types of publications: "
        "original articles, review articles."
    )
    assert page["cap_numbers"] == {"2024": 733, "2025": 707, "2026": 680}
    assert (
        page["contract_url"]
        == "https://www.openaccess.nl/sites/default/files/documents/contract.pdf"
    )
    assert page["openaccess_nl_url"] == url
    assert page["curation_reasons"] == []


def test_parse_deal_page_missing_sections_and_ambiguous_cap():
    page = parse_deal_page(
        DEAL_MISSING_SECTIONS_HTML, "https://www.openaccess.nl/en/publisherdeal/x"
    )
    assert page["summary"] is None
    assert page["workflow_text"] is None
    assert page["cap_numbers"] is None
    assert page["curation_reasons"] == [
        "missing summary",
        "missing 'How does it work?' section",
        "ambiguous cap numbers",
    ]


def test_parse_deal_page_number_before_year_caps():
    html = DEAL_HTML.replace(
        "a maximum of 733\n      articles. In 2025, they are allowed to publish 707 "
        "articles, and in 2026, 680.",
        "a maximum per year: 270 in 2024, 273 in 2025 and 276 in 2026.",
    )
    page = parse_deal_page(html, "https://www.openaccess.nl/en/publisherdeal/lww")
    assert page["cap_numbers"] == {"2024": 270, "2025": 273, "2026": 276}


def test_parse_deal_page_marker_variants():
    page = parse_deal_page(
        DEAL_MARKER_VARIANTS_HTML, "https://www.openaccess.nl/en/publisherdeal/x"
    )
    assert page["summary"] == "Variant summary."
    assert page["conditions_text"] == "AIP conditions line.\nDe Gruyter conditions line."
    assert page["workflow_text"] == "Workflow line."
    assert page["curation_reasons"] == []


@requires_db
async def test_upsert_publisher_and_deal_natural_key(db):
    item = {
        "duration_text": "2025-2027",
        "start_year": 2025,
        "end_year": 2027,
        "per_year_oa_counts": {"2025": 7429},
        "status": "current",
    }
    page = {
        "url": "https://www.openaccess.nl/en/publisherdeal/elsevier-2025-2027",
        "summary": "s",
        "conditions_text": "c",
        "workflow_text": "w",
        "article_types_text": None,
        "cap_text": None,
        "cap_numbers": None,
        "contract_url": None,
        "openaccess_nl_url": "https://www.openaccess.nl/en/publisherdeal/elsevier-2025-2027",
        "curation_reasons": [],
    }
    pub = await _upsert_publisher(db, "elsevier", "Elsevier")
    assert await _upsert_deal(db, pub.id, item, page) is False
    # second run: same natural key -> update in place, no duplicate row
    page["summary"] = None
    page["curation_reasons"] = ["missing summary"]
    pub2 = await _upsert_publisher(db, "elsevier", "Elsevier")
    assert pub2.id == pub.id
    assert await _upsert_deal(db, pub.id, item, page) is True
    await db.flush()
    rows = (await db.execute(select(func.count()).select_from(Deal))).scalar_one()
    assert rows == 1
    deal = await db.scalar(select(Deal))
    assert deal.needs_curation is True
    assert deal.needs_curation_reason == "missing summary"
    assert deal.provenance[0]["source"] == "openaccess.nl"
