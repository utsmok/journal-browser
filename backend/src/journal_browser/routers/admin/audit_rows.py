"""Shared audit-row helpers for admin writes that predate named reviewers.

Settings PUTs, institution PUTs, and feedback priority/delete changes
append status_changes rows so /admin/audit can answer "who moved the data
window" the same way it answers identity flips. Values are stringified
for the Text columns; secret-valued settings are masked by the caller
before a row is built, so a password value never reaches the log.
"""

import json
from typing import Any

from ...models import StatusChangeLog

MASKED = "(masked)"
CLEARED = "(cleared)"


def audit_value(value: Any) -> str | None:
    """None stays None (old value column is nullable); non-strings become
    JSON so true/false/2020 stay machine-readable."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def audit_row(
    *,
    table_name: str,
    row_key: Any,
    field: str,
    old: Any = None,
    new: Any,
    note: str | None = None,
    changed_by: str | None = None,
) -> StatusChangeLog:
    return StatusChangeLog(
        table_name=table_name,
        row_key=row_key,
        field=field,
        old_value=audit_value(old),
        new_value=audit_value(new) if new is not None else CLEARED,
        note=note,
        changed_by=changed_by,
    )
