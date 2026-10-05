"""Report formatters and writers."""

from __future__ import annotations

from conversat.reporting.base import (
    Formatter,
    FormatterResult,
    available,
    dump,
    get,
    register,
    render,
    resolve,
)
from conversat.reporting.console import ConsoleFormatter, ConsoleListener, make_console
from conversat.reporting.json_report import JsonFormatter, JsonLinesFormatter
from conversat.reporting.junit import JUnitFormatter
from conversat.reporting.markdown import MarkdownFormatter
from conversat.reporting.writer import (
    crawl_payload,
    load_report,
    save_report,
    write_reports,
)

__all__ = [
    "ConsoleFormatter",
    "ConsoleListener",
    "Formatter",
    "FormatterResult",
    "JUnitFormatter",
    "JsonFormatter",
    "JsonLinesFormatter",
    "MarkdownFormatter",
    "available",
    "crawl_payload",
    "dump",
    "get",
    "load_report",
    "make_console",
    "register",
    "render",
    "resolve",
    "save_report",
    "write_reports",
]
