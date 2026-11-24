"""CSV streaming primitives shared by the export endpoints.

Formula-injection guard, filename sanitizer, and the chunked CSV
StreamingResponse. The flush cadence (FLUSH_EVERY) matches the
server-side cursor's yield_per in the callers, so one buffer flush
serves one cursor partition.
"""

import csv
import io
import re
from collections.abc import AsyncIterator, Sequence

from fastapi.responses import StreamingResponse

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
