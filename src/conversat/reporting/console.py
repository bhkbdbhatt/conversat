"""Rich console output (live progress + summary) and the listener hook."""

from __future__ import annotations

import os
import sys
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from conversat.models.report import CaseResult, RunReport, TurnResult, TurnStatus
from conversat.models.suite import TestCase
from conversat.reporting.base import Formatter, register
from conversat.utils import format_duration, truncate

STYLE = {
    TurnStatus.PASSED: "green",
    TurnStatus.FAILED: "red",
    TurnStatus.ERROR: "yellow",
    TurnStatus.SKIPPED: "dim",
}
ICON = {
    TurnStatus.PASSED: "PASS",
    TurnStatus.FAILED: "FAIL",
    TurnStatus.ERROR: "ERR",
    TurnStatus.SKIPPED: "SKIP",
}


def _force_utf8_streams() -> None:
    """Stop Windows' cp1252 console from raising on the box-drawing output.

    A legacy code page makes ``print`` raise ``UnicodeEncodeError`` on the first
    non-ASCII glyph, which would abort a run *after* the tests already ran. Only
    the encoding is changed; nothing is written before this point.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if reconfigure is None or encoding in ("utf8", ""):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - exotic stream types
            pass


def make_console(*, quiet: bool = False, no_color: bool = False, force_terminal: bool = False) -> Console:
    """Build a rich console honouring the usual env vars and CLI flags."""
    _force_utf8_streams()
    return Console(
        quiet=quiet,
        no_color=no_color or bool(os.environ.get("NO_COLOR")),
        force_terminal=force_terminal,
        highlight=False,
        soft_wrap=False,
    )


@register("console")
class ConsoleFormatter(Formatter):
    """Human-readable terminal report."""

    name = "console"
    extension = ""

    def __init__(self, console: Console | None = None, *, verbose: bool = False) -> None:
        self.console = console or make_console()
        self.verbose = verbose

    def format(self, report: RunReport) -> str:
        with self.console.capture() as capture:
            self.print_report(report, self.console)
        return capture.get()

    # -- rendering -------------------------------------------------------- #
    def print_report(self, report: RunReport, console: Console | None = None) -> None:
        console = console or self.console
        console.print(self.header(report))
        console.print(self.case_table(report))
        for case in report.cases:
            if case.status is TurnStatus.PASSED and not self.verbose:
                continue
            console.print(self.case_detail(case))
        console.print(self.summary(report))

    def header(self, report: RunReport) -> Panel:
        verdict = Text("PASSED", style="bold green") if report.ok else Text("FAILED", style="bold red")
        body = Table.grid(padding=(0, 2))
        body.add_column()
        body.add_column()
        body.add_row(Text("suite", style="dim"), report.suite)
        body.add_row(Text("run", style="dim"), report.run_id)
        body.add_row(Text("connector", style="dim"), report.connector)
        body.add_row(Text("started", style="dim"), report.started_at.strftime("%Y-%m-%d %H:%M:%S"))
        body.add_row(
            Text("duration", style="dim"),
            f"{format_duration(report.duration_ms)}  p95 {format_duration(report.totals.response_p95_ms)}",
        )
        return Panel(Group(body, Text(""), verdict), title="conversat", border_style="cyan")

    def case_table(self, report: RunReport) -> Table:
        table = Table(box=None, pad_edge=False, expand=False)
        table.add_column("", width=4)
        table.add_column("case", overflow="ellipsis")
        table.add_column("turns", justify="right")
        table.add_column("asserts", justify="right")
        table.add_column("time", justify="right")
        table.add_column("tags", style="dim")

        for case in report.cases:
            passed = sum(1 for t in case.turns if t.status is TurnStatus.PASSED)
            asserts = len([a for t in case.turns for a in t.assertions])
            ok_asserts = len([a for t in case.turns for a in t.assertions if a.passed])
            table.add_row(
                Text(ICON[case.status], style=STYLE[case.status]),
                case.name,
                f"{passed}/{len(case.turns)}",
                f"{ok_asserts}/{asserts}",
                format_duration(case.duration_ms),
                ", ".join(case.tags),
            )
        return table

    def case_detail(self, case: CaseResult) -> Panel:
        lines: list[Text] = []
        if case.error:
            lines.append(Text(f"error: {case.error}", style="bold red"))

        for turn in case.turns:
            head = Text()
            head.append(f"turn {turn.index}", style="bold")
            if turn.name:
                head.append(f" · {turn.name}", style="dim")
            head.append(f"  [{ICON[turn.status]}]", style=STYLE[turn.status])
            head.append(f"  {format_duration(turn.duration_ms)}", style="dim")
            if turn.attempts > 1:
                head.append(f"  ({turn.attempts} attempts)", style="dim yellow")
            lines.append(head)

            if turn.request:
                lines.append(Text(f"  > {truncate(turn.request.replace(chr(10), ' '), 100)}", style="cyan"))
            reply = turn.response.text if turn.response else ""
            lines.append(
                Text(
                    f"  < {truncate(reply.replace(chr(10), ' '), 100) if reply else '<no reply>'}",
                    style="white" if reply else "dim",
                )
            )
            if turn.error:
                lines.append(Text(f"  ! {turn.error}", style="yellow"))
            for assertion in turn.assertions:
                mark = Text(
                    "    PASS " if assertion.passed else "    FAIL ",
                    style="bold green" if assertion.passed else "bold red",
                )
                mark.append(f"{assertion.description}", style="dim" if assertion.passed else "")
                if not assertion.passed and assertion.message:
                    mark.append(f"  {assertion.message}", style="red")
                lines.append(mark)
            lines.append(Text(""))

        border = STYLE[case.status]
        return Panel(Group(*lines), title=case.name, border_style=border, title_align="left")

    def summary(self, report: RunReport) -> Panel:
        t = report.totals
        table = Table.grid(padding=(0, 2))
        table.add_column()
        table.add_column(justify="right")
        table.add_row("cases", f"{t.cases_passed}/{t.cases}")
        table.add_row("assertions", f"{t.assertions_passed}/{t.assertions}")
        table.add_row("latency p50 / p95", f"{format_duration(t.response_p50_ms)} / {format_duration(t.response_p95_ms)}")
        table.add_row("duration", format_duration(report.duration_ms))

        if report.failed_cases:
            names = ", ".join(c.name for c in report.failed_cases[:6])
            more = f" (+{len(report.failed_cases) - 6} more)" if len(report.failed_cases) > 6 else ""
            table.add_row(Text("failing", style="red"), Text(f"{names}{more}", style="red"))

        verdict = Text("PASS", style="bold green") if report.ok else Text("FAIL", style="bold red")
        return Panel(Group(table, Text(""), verdict), title="summary", border_style="bold")


class ConsoleListener:
    """Live, one-line-per-turn output while a run is in flight.

    Pass it to ``TestRunner(listener=ConsoleListener(...))``.
    """

    def __init__(self, console: Console | None = None, *, verbose: bool = False, stream: Any = None) -> None:
        self.console = console or make_console()
        self.verbose = verbose
        self.stream = stream if stream is not None else sys.stderr

    def on_run_start(self, report: RunReport) -> None:
        self.console.print(
            f"[cyan]conversat[/cyan] running [bold]{report.suite}[/bold] "
            f"via [magenta]{report.connector}[/magenta] (run {report.run_id})"
        )

    def on_case_start(self, case: TestCase, index: int, total: int) -> None:
        if self.verbose:
            self.console.print(f"[dim]({index}/{total})[/dim] [bold]{case.name}[/bold]", highlight=False)

    def on_turn_result(self, case: TestCase, turn: TurnResult) -> None:
        icon = ICON[turn.status]
        style = STYLE[turn.status]
        reply = turn.response.text if turn.response else ""
        self.console.print(
            f"  [dim]{case.name}[/dim] turn {turn.index} "
            f"[{style}]{icon}[/{style}] [cyan]>[/cyan] {truncate(turn.request or '', 60)} "
            f"[dim]|[/dim] [white]{truncate(reply.replace(chr(10), ' '), 80)}[/white] "
            f"[dim]{format_duration(turn.duration_ms)}[/dim]",
            highlight=False,
        )
        for assertion in turn.assertions:
            if not assertion.passed:
                self.console.print(
                    f"      [red]x {assertion.description}[/red] [dim]{assertion.message or ''}[/dim]",
                    highlight=False,
                )
        if turn.error:
            self.console.print(f"      [yellow]! {turn.error}[/yellow]", highlight=False)

    def on_case_end(self, result: CaseResult) -> None:
        if self.verbose and result.status is not TurnStatus.PASSED:
            self.console.print(f"  [{STYLE[result.status]}]{ICON[result.status]}[/] {result.name}")

    def on_run_end(self, report: RunReport) -> None:
        verdict = "[bold green]PASSED[/bold green]" if report.ok else "[bold red]FAILED[/bold red]"
        self.console.print(f"{verdict} [dim]{report.summary_line()}[/dim]")
