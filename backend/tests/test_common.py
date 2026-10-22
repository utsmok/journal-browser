"""Pure unit tests for harvest.common helpers (no network, no DB)."""

import pytest

from journal_browser.harvest.common import normalize_issn, parse_csv_rows


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
