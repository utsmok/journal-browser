"""Institution alias matching unit tests (pure functions, no DB)."""

import logging

import pytest

from journal_browser.harvest.institution_aliases import (
    CANONICAL_NAME,
    log_unknown_institution,
    match_institution,
)


@pytest.mark.parametrize(
    ("raw", "variant"),
    [
        ("University of Twente", "University of Twente"),
        ("university of twente", "University of Twente"),
        ("UNIVERSITY OF TWENTE", "University of Twente"),
        ("Twente University", "Twente University"),
        ("twente university", "Twente University"),
        ("Utwente", "Utwente"),
        ("UTWENTE", "Utwente"),
        ("Universiteit Twente", "University of Twente"),
        ("UT", "UT"),
        ("ut", "UT"),
        ("U.T.", "UT"),
        (" University of Twente ", "University of Twente"),
    ],
)
def test_known_variants(raw: str, variant: str) -> None:
    assert match_institution(raw) == (CANONICAL_NAME, variant)


def test_unknown_returns_raw_for_review() -> None:
    raw = "Universiteit van Amsterdam"
    assert match_institution(raw) == (None, raw)


def test_empty_string_is_unknown() -> None:
    assert match_institution("") == (None, "")


def test_unknown_is_loggable_not_dropped(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        log_unknown_institution("Twentse Universiteit", context="jct ingest")
    assert "Twentse Universiteit" in caplog.text
    assert "institution_aliases" in caplog.text
