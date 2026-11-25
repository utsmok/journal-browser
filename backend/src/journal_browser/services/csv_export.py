"""CSV streaming primitives shared by the export endpoints.

Formula-injection guard, filename sanitizer, and the chunked CSV
StreamingResponse. csv_stream reads a statement from a server-side
cursor in partitions of FLUSH_EVERY, the flush cadence of csv_response,
so one buffer flush serves one cursor partition.
"""

import csv
import io
import re
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

#: Rows buffered per streaming chunk (both the server-side cursor's
#: yield_per and the CSV flush cadence).
FLUSH_EVERY = 500

#: Spreadsheet-active leading characters (OWASP CSV injection): a cell
#: starting with one of these would evaluate as a formula in Excel, so it
#: gets a leading apostrophe. Text comes from OpenAlex/Pure and is not
#: trusted.
FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: str) -> str:
    """One cell of CSV output: neutralize spreadsheet formula injection
    by prefixing a `'` to dangerous leading characters."""
    return "'" + value if value.startswith(FORMULA_LEADS) else value


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "export"


def csv_cells(values: Sequence[Any]) -> list[str]:
    """One CSV line; every cell goes through the formula guard."""
    return ["" if v is None else csv_safe(str(v)) for v in values]


async def csv_stream(
    session: AsyncSession, stmt: Any, to_row: Callable[[Any], Sequence[Any]]
) -> AsyncIterator[list[str]]:
    """One line per row of `stmt`, read from a server-side cursor.
    `stmt` is the statement an .all() would run, so the rows and their
    order stay the same; only the fetch is batched."""
    result = await session.stream(stmt.execution_options(yield_per=FLUSH_EVERY))

    async def lines() -> AsyncIterator[list[str]]:
        async for partition in result.partitions(FLUSH_EVERY):
            for row in partition:
                yield csv_cells(to_row(row))

    return lines()


def csv_response(
    filename: str, rows: AsyncIterator[list[str]], header: Sequence[str]
) -> StreamingResponse:
    """CSV attachment; the csv module owns the quoting, rows arrive
    lazily (one flush per FLUSH_EVERY rows)."""

    async def _stream() -> AsyncIterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(header)
        yield buf.getvalue()
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        written = 0
        async for row in rows:
            writer.writerow(row)
            written += 1
            if written % FLUSH_EVERY == 0:
                yield buf.getvalue()
                buf = io.StringIO()
                writer = csv.writer(buf, lineterminator="\n")
        if written % FLUSH_EVERY:
            yield buf.getvalue()

    return StreamingResponse(
        _stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
