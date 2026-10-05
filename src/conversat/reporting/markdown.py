"""Markdown formatter: a shareable summary with conversation transcripts."""

from __future__ import annotations

from conversat.models.report import RunReport, TurnStatus
from conversat.reporting.base import Formatter, register
from conversat.utils import format_duration, truncate

STATUS_ICON = {
    TurnStatus.PASSED: "PASS",
    TurnStatus.FAILED: "FAIL",
    TurnStatus.ERROR: "ERR ",
    TurnStatus.SKIPPED: "SKIP",
}


@register("markdown")
class MarkdownFormatter(Formatter):
    """Markdown that reads well in a PR comment or a CI job summary."""

    name = "markdown"
    extension = "md"

    def __init__(self, *, include_transcripts: bool = True, transcript_limit: int = 60) -> None:
        self.include_transcripts = include_transcripts
        self.transcript_limit = transcript_limit

    def format(self, report: RunReport) -> str:
        t = report.totals
        verdict = "PASS" if report.ok else "FAIL"
        lines: list[str] = [
            f"# conversat run: {report.suite}",
            "",
            f"**{verdict}** &middot; run `{report.run_id}` &middot; {report.summary_line()}",
            "",
            f"- started: {report.started_at.isoformat(timespec='seconds')}",
            f"- connector: `{report.connector}`",
            f"- duration: {format_duration(report.duration_ms)}",
            f"- assertions: {t.assertions_passed}/{t.assertions} passed",
            f"- latency: p50 {format_duration(t.response_p50_ms)}, p95 {format_duration(t.response_p95_ms)}",
        ]
        if report.labels:
            lines.append(f"- labels: {', '.join(f'`{label}`' for label in report.labels)}")
        lines.append("")

        lines.extend(self._case_table(report))
        if not report.ok:
            lines.extend(["", "## Failures", ""])
            for case in report.failed_cases:
                lines.extend(self._failure_block(case))

        if self.include_transcripts:
            lines.extend(["", "## Transcripts", ""])
            for case in report.cases:
                lines.extend(self._transcript(case))

        return "\n".join(lines).rstrip() + "\n"

    def _case_table(self, report: RunReport) -> list[str]:
        rows = [
            "| | case | turns | duration | tags |",
            "|---|---|---:|---:|---|",
        ]
        for case in report.cases:
            icon = STATUS_ICON[case.status]
            rows.append(
                f"| {icon} | {case.name} | {len(case.turns)} | "
                f"{format_duration(self._ms(case))} | {', '.join(case.tags) or '-'} |"
            )
        return rows

    def _failure_block(self, case: object) -> list[str]:
        lines = [f"### {case.name}", ""]  # type: ignore[attr-defined]
        if getattr(case, "error", None):
            lines.extend([f"> {truncate(case.error, 300)}", ""])  # type: ignore[attr-defined]
        for turn in getattr(case, "turns", []):  # type: ignore[attr-defined]
            if turn.status is TurnStatus.PASSED:
                continue
            lines.append(f"**turn {turn.index}** &mdash; {STATUS_ICON[turn.status]}")
            if turn.request:
                lines.append(f"- you: `{truncate(turn.request, self.transcript_limit)}`")
            if turn.response and turn.response.text:
                lines.append(f"- bot: `{truncate(turn.response.text, self.transcript_limit)}`")
            if turn.error:
                lines.append(f"- error: {turn.error}")
            for assertion in turn.failed_assertions:
                lines.append(f"  - x `{assertion.description}` &mdash; {assertion.message or 'failed'}")
            lines.append("")
        return lines

    def _transcript(self, case: object) -> list[str]:
        lines = [f"<details><summary>{case.name}</summary>", ""]  # type: ignore[attr-defined]
        for turn in getattr(case, "turns", []):  # type: ignore[attr-defined]
            reply = turn.response.text if turn.response else ""
            lines.append(f"- **you**: {truncate(turn.request or '', self.transcript_limit)}")
            lines.append(f"  **bot**: {truncate(reply.replace(chr(10), ' '), self.transcript_limit)}")
        lines.extend(["", "</details>", ""])
        return lines

    @staticmethod
    def _ms(case: object) -> float:
        return getattr(case, "duration_ms", 0.0) or 0.0
