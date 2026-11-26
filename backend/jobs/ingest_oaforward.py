"""Ingest hosted institutions' own agreements from the OA Forward registry."""

from journal_browser.harvest.oaforward import main
from journal_browser.jobrunner import run_job

if __name__ == "__main__":
    run_job(main)
