"""ISSN check-digit gate at the ingest boundaries (no network, no DB)."""

import pytest

from journal_browser.harvest.common import issn_checksum_ok, normalize_issn
from journal_browser.harvest.openalex_journals import journal_values
from journal_browser.harvest.scimagojr import issn_candidates


@pytest.mark.parametrize(
    ("issn", "want"),
    [
        # Real: Water Research, a valid plain one, and X-parity cases.
        ("0043-1354", True),
        ("1234-5679", True),
        ("2434-561X", True),
        ("1234561X", True),
        # Transposed/typo'd check digits and non-ISSNs.
        ("0043-1355", False),
        ("1234-567X", False),
        ("not-an-issn", False),
        (None, False),
        ("", False),
    ],
)
def test_issn_checksum_ok(issn, want):
    assert issn_checksum_ok(issn) is want


def test_normalize_then_check_roundtrip():
    assert normalize_issn("00431354") == "0043-1354"
    assert issn_checksum_ok(normalize_issn("00431354"))
    assert not issn_checksum_ok(normalize_issn("1234-567X"))


def test_scimago_candidates_drop_invalid():
    # The export separates ISSNs without hyphens; candidates come back normalized.
    assert issn_candidates("00431354;1234567X;2434561X") == ["0043-1354", "2434-561X"]
    assert issn_candidates("") == []


def test_openalex_journal_skipped_on_bad_issn_l():
    good = journal_values({"id": "S1", "issn_l": "0043-1354", "display_name": "WR"})
    assert good is not None and good["issn_l"] == "0043-1354"
    bad = journal_values({"id": "S2", "issn_l": "1234-567X", "display_name": "X"})
    assert bad is None
    # Valid issn_l with a bogus variant list: variants dropped, row kept.
    mixed = journal_values(
        {"id": "S3", "issn_l": "1234-5679", "issn": ["1234-5679", "1234-567X"], "display_name": "M"}
    )
    assert mixed is not None and mixed["issns"] == ["1234-5679"]
