"""conversat -- a conversational testing platform.

conversat lets you describe a chatbot conversation declaratively in YAML,
run it against a real bot (HTTP, WebSocket or a browser) and assert on the
replies. It ships a pluggable connector + assertion architecture, a bounded
conversation crawler and a test runner that reports like a real test suite.

Quick start::

    from conversat import load_suite, TestRunner

    suite = load_suite("examples/suites/smoke.yaml")
    report = await TestRunner(suite).run()
    print(report.summary_line())
"""

from __future__ import annotations

from conversat.engine.loader import load_suite, load_suites
from conversat.engine.runner import TestRunner, run_suite
from conversat.models import (
    AssertionSpec,
    BotResponse,
    CaseResult,
    ConnectorConfig,
    CrawlConfig,
    CrawlReport,
    RetryPolicy,
    RunReport,
    TestCase,
    TestSuite,
    Turn,
    TurnResult,
    TurnStatus,
)

__version__ = "0.1.0"

__all__ = [
    "AssertionSpec",
    "BotResponse",
    "CaseResult",
    "ConnectorConfig",
    "CrawlConfig",
    "CrawlReport",
    "RetryPolicy",
    "RunReport",
    "TestCase",
    "TestRunner",
    "TestSuite",
    "Turn",
    "TurnResult",
    "TurnStatus",
    "__version__",
    "load_suite",
    "load_suites",
    "run_suite",
]
