"""Report model round-trips.

A report is written to JSON by ``conversat run`` and read back by the dashboard,
``conversat report`` and ``conversat summary``. Serialising must therefore not
produce a document the models reject -- that regression silently emptied the
dashboard because ``load_disk`` swallows validation errors.
"""

from __future__ import annotations

import json

import pytest

from conversat.engine import TestRunner, load_suite
from conversat.errors import ConversatError
from conversat.models.report import (
    AssertionOutcome,
    CaseResult,
    RunReport,
    TurnResult,
    TurnStatus,
)
from conversat.reporting.writer import load_report, save_report, write_reports


def sample_report() -> RunReport:
    turn = TurnResult(
        index=0,
        name="greeting",
        request="hello",
        status=TurnStatus.PASSED,
        assertions=[
            AssertionOutcome(
                type="contains",
                description="contains 'hi'",
                passed=True,
                expected="hi",
                actual="hi",
            ),
            AssertionOutcome(
                type="not_empty", description="not empty", passed=False, message="empty reply"
            ),
        ],
        duration_ms=12.5,
    )
    case = CaseResult(
        name="greeting",
        status=TurnStatus.FAILED,
        tags=["smoke"],
        connector="echo",
        turns=[turn],
    )
    return RunReport(
        run_id="run-1", suite="demo", connector="echo", cases=[case]
    ).recompute_totals()


def test_assertion_count_is_serialised() -> None:
    payload = sample_report().model_dump(mode="json")
    assert payload["cases"][0]["turns"][0]["assertion_count"] == 2


def test_report_round_trips_through_dict() -> None:
    report = sample_report()
    restored = RunReport.model_validate(json.loads(report.model_dump_json()))
    assert restored == report
    assert restored.cases[0].turns[0].assertion_count == 2


def test_report_round_trips_through_file(tmp_path) -> None:
    report = sample_report()
    path = save_report(report, tmp_path / "report.json", formatter="json")
    assert load_report(path) == report


def test_write_reports_output_is_loadable(tmp_path) -> None:
    report = sample_report()
    written = write_reports(report, formats=["json"], output_dir=tmp_path)
    assert [w.filename for w in written]
    assert load_report(written[0].filename) == report


def test_load_report_rejects_foreign_json(tmp_path) -> None:
    path = tmp_path / "other.json"
    path.write_text('{"hello": "world"}', encoding="utf-8")
    with pytest.raises(ConversatError):
        load_report(path)


def test_unknown_fields_are_still_rejected() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        TurnResult.model_validate({"index": 0, "nonsense": True})


async def test_echo_suite_run_round_trips(tmp_path) -> None:
    report = await TestRunner(load_suite("examples/suites/echo.yaml")).run()
    path = save_report(report, tmp_path / "echo.json", formatter="json")
    restored = load_report(path)
    assert restored.totals == report.totals
    assert [c.name for c in restored.cases] == [c.name for c in report.cases]
