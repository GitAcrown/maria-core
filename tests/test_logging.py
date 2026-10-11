"""Format du journal, sans brancher les handlers du processus."""

import logging

from maria_core.logging import KeyValueFormatter


def test_formatter_quotes_spaces_and_keeps_the_keys() -> None:
    record = logging.LogRecord(
        name="maria_core.db",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Migration %s appliquée",
        args=("001_init",),
        exc_info=None,
    )
    line = KeyValueFormatter().format(record)
    assert "level=INFO" in line
    assert "logger=maria_core.db" in line
    assert 'msg="Migration 001_init appliquée"' in line
