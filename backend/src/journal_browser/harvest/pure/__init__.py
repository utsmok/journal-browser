"""Harvest Pure (ris.utwente.nl) publications via its anonymous OAI-PMH endpoint.

Port of ut-metadata's pure.py (transport + parsing logic kept 1:1 where the
protocol demands it), trimmed to journal-browser's collect-only publications
corpus:

- ``publications:year{YYYY}`` sets over ``oai_dc`` build canonical ``works``
  (per-year restart granularity: a crash re-runs one year).
- The ``openaire_cris_publications`` set over ``oai_cerif_openaire`` enriches
  ``cerif_issn`` / ``publisher`` / ``doi`` (targeted field extraction; the raw
  CERIF XML stays verbatim in source_records for any future re-parse) and
  stores the pure author list (work_pure_authors).
- The ``openaire_cris_orgunits`` / ``openaire_cris_persons`` sets build the
  standalone author canon (pure_orgs / pure_org_parents / pure_persons).

Live facts inherited from ut-metadata (2026-09-04): publications:* sets serve
oai_dc; cris sets require oai_cerif_openaire; deletedRecord=no; granularity
YYYY-MM-DDThh:mm:ssZ. Pure reports no deletes: periodic full re-baselines mark
absent works retired instead of deleting evidence.
"""

from .doi import _doi_clean, extract_doi
from .entities import harvest_pure_entities
from .pipeline import _consume_oai_pages, harvest_pure_cerif, harvest_pure_years
from .store import retire_absent
from .xmlrecords import _norm_title

__all__ = [
    "_consume_oai_pages",
    "_doi_clean",
    "_norm_title",
    "extract_doi",
    "harvest_pure_cerif",
    "harvest_pure_entities",
    "harvest_pure_years",
    "retire_absent",
]
