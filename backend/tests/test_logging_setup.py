"""RedactionFilter must not break lazy %-formatting."""

import logging

from journal_browser.logging_setup import RedactionFilter


def test_filter_preserves_non_str_args_for_lazy_formatting():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "x",
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.1", "POST", "/api/v1/usage/events", "1.1", 204),
        None,
    )
    RedactionFilter().filter(record)
    assert record.getMessage() == '10.0.0.1 - "POST /api/v1/usage/events HTTP/1.1" 204'


def test_filter_redacts_secret_in_msg_and_str_args():
    record = logging.LogRecord(
        "app",
        logging.INFO,
        "x",
        1,
        "auth with %s",
        ("Bearer abc.def.ghi",),
        None,
    )
    RedactionFilter().filter(record)
    assert "Bearer ***" in record.getMessage()


def test_filter_keeps_mapping_args_renderable():
    record = logging.LogRecord(
        "harvest",
        logging.INFO,
        "x",
        1,
        "reconcile: %s",
        {"matched": 5, "secret": "Bearer abc.def.ghi"},
        None,
    )
    RedactionFilter().filter(record)
    rendered = record.getMessage()
    assert "matched" in rendered and "'secret'" in rendered
    assert "Bearer ***" in rendered


def test_configure_logging_gives_app_logger_an_info_path(monkeypatch, capsys):
    monkeypatch.setenv("JB_LOG_FORMAT", "text")
    app_logger = logging.getLogger("journal_browser")
    saved_handlers, saved_level, saved_propagate = (
        app_logger.handlers,
        app_logger.level,
        app_logger.propagate,
    )
    app_logger.handlers, app_logger.propagate = [], False
    try:
        from journal_browser.logging_setup import configure_logging

        configure_logging()
        assert app_logger.level == logging.INFO
        assert app_logger.handlers, "app logger needs its own handler"
        app_logger.info("usage ip retention: nulled ip on %d event(s)", 3)
        err = capsys.readouterr().err
        assert "nulled ip on 3 event(s)" in err
    finally:
        app_logger.handlers, app_logger.propagate = saved_handlers, saved_propagate
        app_logger.setLevel(saved_level)
