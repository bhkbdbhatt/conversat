"""In-memory stores over the reports directory.

``conversat run`` writes JSON reports to disk; ``conversat crawl --json`` writes
crawl reports next to them. Both stores ingest their files on startup and keep
the most recent N in memory, so the API can answer questions about history
without a database.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from conversat.models.crawler import CrawlNode, CrawlReport
from conversat.models.report import RunReport

DEFAULT_HISTORY = 50


class RunStore:
    """Keeps the most recent runs in memory, backed by a reports directory."""

    def __init__(
        self, directory: str | Path = "reports", *, history: int = DEFAULT_HISTORY
    ) -> None:
        self.directory = Path(directory)
        self.history = history
        self._runs: dict[str, RunReport] = {}
        self._order: list[str] = []

    # -- ingestion -------------------------------------------------------- #
    def add(self, report: RunReport) -> RunReport:
        if report.run_id in self._runs:
            self._order.remove(report.run_id)
        self._runs[report.run_id] = report
        self._order.append(report.run_id)
        while len(self._order) > self.history:
            self._runs.pop(self._order.pop(0), None)
        return report

    def load_disk(self, *, limit: int | None = None) -> int:
        """Ingest JSON report files from the reports directory."""
        loaded = 0
        for path in self._report_files(limit):
            report = read_run_report(path)
            if report is not None:
                self.add(report)
                loaded += 1
        return loaded

    def _report_files(self, limit: int | None) -> list[Path]:
        if not self.directory.is_dir():
            return []
        files = sorted(
            self.directory.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return files[: limit or self.history]

    # -- queries ---------------------------------------------------------- #
    def get(self, run_id: str) -> RunReport | None:
        return self._runs.get(run_id)

    def latest(self) -> RunReport | None:
        return self._runs.get(self._order[-1]) if self._order else None

    def list(self) -> list[dict[str, Any]]:
        return [self.summary(self._runs[run_id]) for run_id in reversed(self._order)]

    @staticmethod
    def summary(report: RunReport) -> dict[str, Any]:
        return {
            "run_id": report.run_id,
            "suite": report.suite,
            "connector": report.connector,
            "started_at": report.started_at.isoformat(),
            "duration_ms": round(report.duration_ms, 1),
            "status": "passed" if report.ok else "failed",
            "labels": report.labels,
            "totals": report.totals.model_dump(mode="json"),
        }

    def turns(self, run_id: str) -> list[dict[str, Any]]:
        from conversat.engine.runner import case_summary

        report = self._runs.get(run_id)
        return case_summary(report) if report else []

    def trends(self, *, limit: int = 30) -> list[dict[str, Any]]:
        """Pass-rate series, oldest first, for the dashboard sparkline."""
        out: list[dict[str, Any]] = []
        for run_id in self._order[-limit:]:
            report = self._runs[run_id]
            totals = report.totals
            out.append(
                {
                    "run_id": run_id,
                    "suite": report.suite,
                    "started_at": report.started_at.isoformat(),
                    "status": "passed" if report.ok else "failed",
                    "pass_rate": round(totals.pass_rate, 2),
                    "cases": totals.cases,
                    "cases_passed": totals.cases_passed,
                    "turns": totals.turns,
                    "assertions": totals.assertions,
                    "duration_ms": round(report.duration_ms, 1),
                    "p95_ms": round(totals.response_p95_ms, 1),
                }
            )
        return out

    def case_history(self, name: str, *, limit: int = 25) -> list[dict[str, Any]]:
        """Every recorded outcome for one case name, oldest first."""
        out: list[dict[str, Any]] = []
        for run_id in self._order:
            report = self._runs[run_id]
            case = report.case(name)
            if case is None:
                continue
            out.append(
                {
                    "run_id": run_id,
                    "suite": report.suite,
                    "started_at": report.started_at.isoformat(),
                    "status": case.status.value,
                    "turns": len(case.turns),
                    "assertions": sum(len(t.assertions) for t in case.turns),
                    "failed_assertions": sum(len(t.failed_assertions) for t in case.turns),
                    "duration_ms": round(case.duration_ms, 1),
                    "error": case.error,
                    "turn_rows": [
                        {
                            "index": turn.index,
                            "name": turn.name,
                            "request": turn.request,
                            "reply": turn.response.text if turn.response else None,
                            "status": turn.status.value,
                            "duration_ms": round(turn.duration_ms, 1),
                            "assertions": [a.model_dump(mode="json") for a in turn.assertions],
                            "error": turn.error,
                        }
                        for turn in case.turns
                    ],
                }
            )
        return out[-limit:]

    def __len__(self) -> int:
        return len(self._order)

    def __iter__(self) -> Iterator[RunReport]:
        return (self._runs[run_id] for run_id in self._order)


class CrawlStore:
    """Same idea as :class:`RunStore`, for crawl reports."""

    def __init__(
        self, directory: str | Path = "reports", *, history: int = DEFAULT_HISTORY
    ) -> None:
        self.directory = Path(directory)
        self.history = history
        self._crawls: dict[str, CrawlReport] = {}
        self._order: list[str] = []

    def add(self, report: CrawlReport, *, crawl_id: str | None = None) -> str:
        key = crawl_id or f"crawl-{report.started_at.strftime('%Y%m%d-%H%M%S')}"
        suffix = 1
        while key in self._crawls and self._crawls[key] is not report:
            suffix += 1
            key = f"{crawl_id or 'crawl'}-{suffix}"
        if key in self._crawls:
            self._order.remove(key)
        self._crawls[key] = report
        self._order.append(key)
        while len(self._order) > self.history:
            self._crawls.pop(self._order.pop(0), None)
        return key

    def load_disk(self, *, limit: int | None = None) -> int:
        if not self.directory.is_dir():
            return 0
        files = sorted(self.directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        loaded = 0
        for path in files[: limit or self.history]:
            report = read_crawl_report(path)
            if report is not None:
                self.add(report, crawl_id=path.stem)
                loaded += 1
        return loaded

    def get(self, crawl_id: str) -> CrawlReport | None:
        if crawl_id in self._crawls:
            return self._crawls[crawl_id]
        # Allow looking a crawl up by the suite it explored.
        for report in self._crawls.values():
            if report.suite == crawl_id:
                return report
        return None

    def latest(self) -> CrawlReport | None:
        return self._crawls.get(self._order[-1]) if self._order else None

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "crawl_id": key,
                "suite": report.suite,
                "connector": report.connector,
                "started_at": report.started_at.isoformat(),
                "duration_ms": round(report.duration_ms, 1),
                "nodes": report.coverage.nodes,
                "max_depth": report.coverage.max_depth_reached,
                "unique_responses": report.coverage.unique_responses,
                "issues": len(report.issues),
                "suggested_cases": len(report.suggested_cases),
                "error_rate": round(report.coverage.error_rate, 3),
            }
            for key, report in ((k, self._crawls[k]) for k in reversed(self._order))
        ]

    def tree(self, crawl_id: str) -> dict[str, Any] | None:
        """Nest a flat node list into the forest the UI renders."""
        report = self.get(crawl_id)
        if report is None:
            return None
        nodes = {node.id: _node_payload(node) for node in report.nodes}
        roots: list[str] = []
        for node in report.nodes:
            if node.parent and node.parent in nodes:
                nodes[node.parent]["children"].append(node.id)
            else:
                roots.append(node.id)
        return {
            "crawl_id": crawl_id,
            "suite": report.suite,
            "connector": report.connector,
            "connector_config": report.connector_config,
            "started_at": report.started_at.isoformat(),
            "finished_at": report.finished_at.isoformat(),
            "duration_ms": round(report.duration_ms, 1),
            "config": report.config.model_dump(mode="json"),
            "roots": roots,
            "nodes": nodes,
            "coverage": report.coverage.model_dump(mode="json"),
            "issues": [issue.model_dump(mode="json") for issue in report.issues],
            "suggested_cases": [
                case.model_dump(mode="json", by_alias=True) for case in report.suggested_cases
            ],
            "suite_yaml": report.to_suite(name=report.suite),
            "ok": report.ok,
        }

    def __len__(self) -> int:
        return len(self._order)

    def __iter__(self) -> Iterator[CrawlReport]:
        return (self._crawls[key] for key in self._order)


def _node_payload(node: CrawlNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "parent": node.parent,
        "depth": node.depth,
        "request": node.request,
        "reply": node.response.text if node.response else None,
        "status": str(node.status),
        "duration_ms": round(node.duration_ms, 1),
        "error": node.error,
        "follow_ups": list(node.follow_ups),
        "children": [],
    }


# -- disk readers --------------------------------------------------------- #
# Both report kinds share one directory and one ``.json`` extension, so each
# file is probed against both models; an unreadable file is simply skipped.


def _load_payload(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def read_run_report(path: str | Path) -> RunReport | None:
    payload = _load_payload(Path(path))
    if payload is None or "nodes" in payload or "coverage" in payload:
        return None
    try:
        return RunReport.model_validate(payload)
    except ValueError:
        return None


def read_crawl_report(path: str | Path) -> CrawlReport | None:
    payload = _load_payload(Path(path))
    if payload is None or ("nodes" not in payload and "coverage" not in payload):
        return None
    try:
        return CrawlReport.model_validate(payload)
    except ValueError:
        return None


def store_from_reports(reports: Iterable[str | Path]) -> RunStore:
    """Build a store from explicit JSON report paths."""
    paths = list(reports)
    store = RunStore(directory=".", history=len(paths) or 1)
    for path in paths:
        report = read_run_report(path)
        if report is not None:
            store.add(report)
    return store
