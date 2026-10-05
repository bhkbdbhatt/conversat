"""Machine-readable JSON report."""

from __future__ import annotations

import json
from typing import Any

from conversat.models.report import RunReport
from conversat.reporting.base import Formatter, register


class _Encoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:  # pragma: no cover - safety net
        if hasattr(o, "model_dump"):
            return o.model_dump(mode="json")
        if isinstance(o, set):
            return sorted(o)
        return str(o)


@register("json")
class JsonFormatter(Formatter):
    """Pretty-printed JSON: feed it to CI tooling or the dashboard."""

    name = "json"
    extension = "json"

    def __init__(self, *, indent: int = 2) -> None:
        self.indent = indent

    def format(self, report: RunReport) -> str:
        return json.dumps(report.model_dump(mode="json"), indent=self.indent, cls=_Encoder)


@register("jsonl")
class JsonLinesFormatter(Formatter):
    """One JSON object per turn -- handy for streaming into a data store."""

    name = "jsonl"
    extension = "jsonl"

    def format(self, report: RunReport) -> str:
        rows: list[dict[str, Any]] = []
        for case in report.cases:
            for turn in case.turns:
                rows.append(
                    {
                        "run_id": report.run_id,
                        "suite": report.suite,
                        "case": case.name,
                        "case_status": case.status.value,
                        "tags": case.tags,
                        "turn": turn.index,
                        "status": turn.status.value,
                        "request": turn.request,
                        "reply": turn.response.text if turn.response else None,
                        "latency_ms": turn.response.latency_ms if turn.response else None,
                        "duration_ms": turn.duration_ms,
                        "attempts": turn.attempts,
                        "error": turn.error,
                        "assertions": [a.model_dump(mode="json") for a in turn.assertions],
                    }
                )
        return "\n".join(json.dumps(row, cls=_Encoder) for row in rows)
