from typing import Any

from sqlalchemy import and_, case, exists, func, or_, select

from ...models import Journal, JournalApcAggregate
from ...vocab import OaType

APC_EXISTS = exists(select(1).where(JournalApcAggregate.issn_l == Journal.issn_l))
#: OpenAlex "fully open access" venue flag, an OA-evidence source beside
#: DOAJ membership (2026-10-27): OpenAlex misses DOAJ membership for real
#: OA journals (e.g. MDPI Water), which used to fall through to
#: "subscription".
_OA_EVIDENCE = or_(
    Journal.is_in_doaj.is_(True),
    Journal.is_oa.is_(True),
    Journal.doaj_in_doaj.is_(True),
)
#: Charge evidence for the gold split: DOAJ's own has_apc declaration,
#: OpenAPC rows, the denormalized OpenAPC cost, or an OpenAlex list price.
_CHARGED = or_(
    Journal.doaj_has_apc.is_(True),
    APC_EXISTS,
    Journal.latest_apc_euro.is_not(None),
    func.coalesce(func.jsonb_array_length(Journal.apc_prices), 0) > 0,
)
#: DOAJ-listed with an explicit no-APC declaration: diamond, per DOAJ canon.
_DOAJ_DIAMOND = and_(Journal.doaj_in_doaj.is_(True), Journal.doaj_has_apc.is_(False))
#: Venue color observed from recent works (harvest/journal_oa.py) when the
#: only evidence is the bare is_oa flag; bronze/closed/green stay NULL
#: (no OA color) so the case falls through to deal/subscription instead of
#: an overeager diamond (owner decision 2026-10-27).
_OBSERVED = case(
    (
        Journal.oa_status_observed.in_((OaType.GOLD, OaType.DIAMOND, OaType.HYBRID)),
        Journal.oa_status_observed,
    ),
    else_=None,
)

#: Per-journal OA type (owner-approved 2026-10-28; supersedes 2026-10-23).
#: DOAJ is the gold/diamond canon: its has_apc declaration (with observed
#: prices as corroboration) splits gold from diamond; a DOAJ-listed venue
#: without charges is diamond. An OA venue with no model evidence at all is
#: "generic" instead of an overeager diamond. Per-work oa_status outside
#: the sample is deliberately unused.
def _oa_type(deal_covered: Any) -> Any:
    return case(
        (and_(_OA_EVIDENCE, _CHARGED), OaType.GOLD),
        (_DOAJ_DIAMOND, OaType.DIAMOND),
        (_OBSERVED.is_not(None), _OBSERVED),
        (deal_covered.is_(True), OaType.HYBRID),
        (_OA_EVIDENCE, OaType.GENERIC),
        else_=OaType.SUBSCRIPTION,
    ).label("oa_type")

#: Journal OA-type vocabulary (the OA_TYPE values); the oa_type facet
#: multi-selects these with OR semantics.
OA_TYPES = tuple(OaType)


def oa_type_value(
    is_in_doaj: bool | None,
    is_oa: bool | None,
    has_charges: bool,
    deal_covered: bool,
    observed: str | None = None,
    doaj_in_doaj: bool | None = None,
    doaj_has_apc: bool | None = None,
) -> str:
    """Python mirror of the OA_TYPE SQL case, for the detail endpoint.
    doaj_has_apc=True is charge evidence on its own, exactly like the SQL
    _CHARGED clause."""
    oa_evidence = bool(is_in_doaj) or bool(is_oa) or bool(doaj_in_doaj)
    if oa_evidence and (has_charges or doaj_has_apc is True):
        return OaType.GOLD
    if doaj_in_doaj and doaj_has_apc is False:
        return OaType.DIAMOND
    if observed in (OaType.GOLD, OaType.DIAMOND, OaType.HYBRID):
        return OaType(observed)
    if deal_covered:
        return OaType.HYBRID
    if oa_evidence:
        return OaType.GENERIC
    return OaType.SUBSCRIPTION
