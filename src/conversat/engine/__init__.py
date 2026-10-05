"""Engine: connector contract, suite loading and the test runner."""

from __future__ import annotations

from conversat.engine.base import Connector, ConnectorSequence, Exchange, SyncFunctionConnector
from conversat.engine.loader import (
    dump_suite,
    load_suite,
    load_suites,
    resolve_paths,
    suite_from_dict,
    suite_to_dict,
)
from conversat.engine.runner import (
    Listener,
    NullListener,
    RunOptions,
    TestRunner,
    case_summary,
    run_many,
    run_suite,
)

__all__ = [
    "Connector",
    "ConnectorSequence",
    "Exchange",
    "Listener",
    "NullListener",
    "RunOptions",
    "SyncFunctionConnector",
    "TestRunner",
    "case_summary",
    "dump_suite",
    "load_suite",
    "load_suites",
    "resolve_paths",
    "run_many",
    "run_suite",
    "suite_from_dict",
    "suite_to_dict",
]
