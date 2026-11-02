"""Database schema: harvest bookkeeping, landing store, and domain tables.

Landing store (ut-metadata pattern): verbatim payloads in `source_records`
(content-hash versioned, append-only) plus file-level raw copies in
`raw_files`. Normalized domain tables are rebuildable from the landing
store; `manual_overrides` survives every re-ingestion.
"""

from .app_data import CacheEpoch, DocEdit, Feedback, Limitation, ManualOverride, StatusChangeLog
from .authors import Author, AuthorWork
from .base import Base, _tstamp
from .deals import Deal, DealInstitution, DealJournal
from .evidence import ApcEvidence, InstitutionTrend, InstitutionWorksStats, JournalApcAggregate
from .harvest import HarvestRun, HarvestState, RawFile, SourceRecord
from .jisc import (
    JiscFunder,
    JiscFunderGroup,
    JiscPolicy,
    JiscPublication,
    JiscPublisher,
    JiscRepository,
)
from .journals import Journal, JournalFlags, ScimagojrMetric
from .openalex import AuthorIdentity, OpenalexWork
from .pure import PureOrg, PureOrgParent, PurePerson, PurePersonOrg, WorkPureAuthor
from .reference import Institution, IssnMap, OpenalexPublisher, Publisher
from .works import WORK_IDENTITY_UQ, Work, WorkIdentity

__all__ = [
    "WORK_IDENTITY_UQ",
    "ApcEvidence",
    "Author",
    "AuthorIdentity",
    "AuthorWork",
    "Base",
    "CacheEpoch",
    "Deal",
    "DealInstitution",
    "DealJournal",
    "DocEdit",
    "Feedback",
    "HarvestRun",
    "HarvestState",
    "Institution",
    "InstitutionTrend",
    "InstitutionWorksStats",
    "IssnMap",
    "JiscFunder",
    "JiscFunderGroup",
    "JiscPolicy",
    "JiscPublication",
    "JiscPublisher",
    "JiscRepository",
    "Journal",
    "JournalApcAggregate",
    "JournalFlags",
    "Limitation",
    "ManualOverride",
    "OpenalexPublisher",
    "OpenalexWork",
    "Publisher",
    "PureOrg",
    "PureOrgParent",
    "PurePerson",
    "PurePersonOrg",
    "RawFile",
    "ScimagojrMetric",
    "SourceRecord",
    "StatusChangeLog",
    "Work",
    "WorkIdentity",
    "WorkPureAuthor",
    "_tstamp",
]
