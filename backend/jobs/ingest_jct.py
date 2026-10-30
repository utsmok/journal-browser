"""Ingest the cOAlition S Journal Checker Tool public dump into deals tables."""

from journal_browser.harvest.jct import main
from journal_browser.jobrunner import run_job

if __name__ == "__main__":
    run_job(main)
