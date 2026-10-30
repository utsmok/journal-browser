"""Pure unit tests for harvest.common helpers (no network, no DB)."""

import pytest

from journal_browser.harvest.common import (
    HarvestDataError,
    normalize_issn,
    parse_csv_rows,
    require_headers,
)


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("0043-1397", "0043-1397"),
        ("00431397", "0043-1397"),
        ("1944-7973", "1944-7973"),
        ("2049-3630", "2049-3630"),
        ("1234-567X", "1234-567X"),
        ("123456789", None),
        ("not-an-issn", None),
        (None, None),
        ("", None),
    ],
)
def test_normalize_issn(raw, want):
    assert normalize_issn(raw) == want


def test_parse_csv_rows_handles_bom_and_semicolons():
    data = "\ufeffa;b\n1;two\n".encode("utf-8")
    rows = parse_csv_rows(data, delimiter=";")
    assert rows == [{"a": "1", "b": "two"}]


def test_require_headers_missing_column_names_source():
    with pytest.raises(HarvestDataError, match=r"doaj journals.*Journal URL"):
        require_headers([{"Journal title": "x"}], {"Journal title", "Journal URL"}, "doaj journals")


def test_require_headers_empty_rows():
    with pytest.raises(HarvestDataError, match="no rows"):
        require_headers([], {"a"}, "scimagojr export")


def test_require_headers_passes_on_complete_headers():
    require_headers([{"a": "1", "b": "2"}], {"a", "b"}, "openapc ta")
