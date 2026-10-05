"""``conversat report`` -- re-render a stored JSON report."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from conversat.cli.common import Argument, Option, console_for, console_error
from conversat.errors import ConversatError
from conversat.reporting.base import resolve
from conversat.reporting.console import ConsoleFormatter
from conversat.reporting.writer import load_report, write_reports


def register(app: typer.Typer) -> None:
    @app.command("report")
    def report_cmd(
        report: Annotated[
            Path, Argument(metavar="REPORT", help="JSON report written by 'conversat run'.")
        ],
        formats: Annotated[
            list[str] | None,
            Option("--format", "-f", help="Output formats: console, markdown, junit, json, jsonl."),
        ] = None,
        output_dir: Annotated[
            Path | None, Option("--output-dir", "-o", help="Where to write converted reports.")
        ] = None,
        quiet: Annotated[bool, Option("--quiet", "-q", help="Do not print to stdout.")] = False,
        no_color: Annotated[bool, Option("--no-color", help="Disable ANSI colours.")] = False,
        stdout: Annotated[
            bool, Option("--stdout", help="Force writing to stdout instead of files.")
        ] = False,
    ) -> None:
        """Convert a stored run report into other formats."""
        console = console_for(quiet=quiet, no_color=no_color)

        try:
            loaded = load_report(report)
        except ConversatError as exc:
            console_error(str(exc), quiet=quiet, no_color=no_color)
            raise typer.Exit(code=2) from exc

        chosen = resolve(formats or ["console"])
        for formatter in chosen:
            if formatter.extension and not stdout:
                continue
            console.print(formatter.format(loaded))

        writers = [fmt for fmt in chosen if fmt.extension and not stdout]
        if writers:
            target = output_dir or report.parent
            try:
                for item in write_reports(loaded, formatters=writers, output_dir=target):
                    console.print(f"[green]wrote[/green] {item.filename}")
            except OSError as exc:
                console_error(f"cannot write reports: {exc}", quiet=quiet, no_color=no_color)
                raise typer.Exit(code=2) from exc

        if "console" not in [fmt.name for fmt in chosen] and not writers:
            console.print(
                f"nothing to do: pass --stdout to print [dim]{', '.join(f.name for f in chosen)}[/dim]"
            )

        raise typer.Exit(code=0 if loaded.ok else 1)


def register_summary(app: typer.Typer) -> None:
    """Print only the summary line of a report (used by CI wrappers)."""

    @app.command("summary")
    def summary_cmd(
        report: Annotated[Path, Argument(metavar="REPORT", help="JSON report to summarise.")],
    ) -> None:
        """Print a compact summary of a stored report."""
        console = console_for()
        try:
            loaded = load_report(report)
        except ConversatError as exc:
            console_error(str(exc))
            raise typer.Exit(code=2) from exc
        console.print(ConsoleFormatter(console=console).header(loaded))
        console.print(loaded.summary_line())
