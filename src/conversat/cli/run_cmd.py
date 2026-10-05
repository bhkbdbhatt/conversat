"""``conversat run`` -- execute suites and render reports."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Annotated

import typer

from conversat.cli.common import (
    Argument,
    Option,
    console_for,
    console_error,
    parse_key_value,
    split_tags,
    system_environment,
)
from conversat.engine.loader import load_suites
from conversat.engine.runner import RunOptions, TestRunner
from conversat.errors import ConversatError
from conversat.models.report import RunReport
from conversat.reporting.base import resolve
from conversat.reporting.console import ConsoleFormatter, ConsoleListener
from conversat.reporting.writer import write_reports
from conversat.utils import redact


def register(app: typer.Typer) -> None:
    @app.command("run")
    def run(
suites: Annotated[
            list[Path],
            Argument(metavar="SUITE [SUITE ...]", help="Suite file, directory or glob (repeatable)."),
        ],
        tags: Annotated[
            list[str] | None,
            Option("--tags", "-t", help="Only run cases with these tags (repeatable/comma-separated)."),
        ] = None,
        exclude_tags: Annotated[
            list[str] | None, Option("--exclude-tags", help="Skip cases with these tags.")
        ] = None,
        case_names: Annotated[
            list[str] | None, Option("--case", "-c", help="Run only these case names.")
        ] = None,
        name_pattern: Annotated[
            str | None, Option("--name-pattern", help="Regex filter on case names.")
        ] = None,
        concurrency: Annotated[
            int, Option("--concurrency", "-j", help="Cases executed in parallel.")
        ] = 4,
        fail_fast: Annotated[
            bool, Option("--fail-fast", help="Stop starting new cases after the first failure.")
        ] = False,
        timeout: Annotated[
            float | None, Option("--timeout", help="Default per-turn timeout in seconds.")
        ] = None,
        variables: Annotated[
            list[str] | None, Option("--var", help="Suite variable as key=value (repeatable).")
        ] = None,
        connector: Annotated[
            str | None, Option("--connector", help="Override the connector, e.g. http:url=http://...")
        ] = None,
        env_file: Annotated[
            Path | None, Option("--env-file", help="Load KEY=VALUE pairs from a .env file.")
        ] = None,
        formats: Annotated[
            list[str] | None,
            Option("--format", "-f", help="Report formats: console, json, jsonl, junit, markdown."),
        ] = None,
        output_dir: Annotated[
            Path | None, Option("--output-dir", "-o", help="Where to write report files.")
        ] = None,
        report_name: Annotated[
            str | None, Option("--report-name", help="Base filename for written reports.")
        ] = None,
        no_write: Annotated[
            bool, Option("--no-write", help="Render reports but do not write files.")
        ] = False,
        quiet: Annotated[bool, Option("--quiet", "-q", help="Only print the summary.")] = False,
        no_color: Annotated[bool, Option("--no-color", help="Disable ANSI colours.")] = False,
        verbose: Annotated[bool, Option("--verbose", "-v", help="Show every turn and reply.")] = False,
        dry_run: Annotated[
            bool, Option("--dry-run", help="Select cases and print them without running.")
        ] = False,
        label: Annotated[
            list[str] | None, Option("--label", help="Attach a CI label to the report.")
        ] = None,
    ) -> None:
        """Run one or more suites against a bot."""
        console = console_for(quiet=quiet, no_color=no_color)
        chosen = resolve(formats or ["console", "json"])
        names = [fmt.name for fmt in chosen]

        try:
            loaded = load_suites(list(suites))
        except ConversatError as exc:
            console_error(str(exc), quiet=quiet, no_color=no_color)
            raise typer.Exit(code=2) from exc

        overrides: dict[str, object] = {}
        variables_map = parse_key_value(variables)
        if variables_map:
            overrides["variables"] = variables_map
        connector_override = _parse_connector(connector)
        if connector_override:
            overrides["connector"] = connector_override

        environment = {**system_environment(), **({} if not env_file else _load_env(env_file))}
        if variables_map:
            environment["variables"] = redact(variables_map)

        options = RunOptions(
            concurrency=max(1, concurrency),
            fail_fast=fail_fast,
            include_tags=split_tags(tags),
            exclude_tags=split_tags(exclude_tags),
            names=set(case_names or []),
            name_pattern=name_pattern,
            default_timeout=timeout,
        )

        listener = (
            None
            if "console" not in names or quiet
            else ConsoleListener(console=console, verbose=verbose)
        )

        async def _execute() -> list[RunReport]:
            reports: list[RunReport] = []
            for suite in loaded:
                runner = TestRunner(
                    suite,
                    listener=listener,
                    options=options,
                    version=_version(),
                    environment=environment,
                    labels=label or [],
                )
                reports.append(await runner.run())
            return reports

        started = time.perf_counter()
        try:
            reports = asyncio.run(_execute())
        except ConversatError as exc:
            console_error(str(exc), quiet=quiet, no_color=no_color)
            raise typer.Exit(code=2) from exc
        except KeyboardInterrupt:  # pragma: no cover - interactive only
            console.print("[yellow]interrupted[/yellow]", stderr=True)
            raise typer.Exit(code=130) from None
        elapsed = (time.perf_counter() - started) * 1000

        for report in reports:
            if "console" in names and not quiet:
                console.print(ConsoleFormatter(console=console, verbose=verbose).format(report))

            if not no_write:
                target = output_dir or Path("reports")
                try:
                    written = write_reports(
                        report,
                        formatters=[fmt for fmt in chosen if fmt.extension],
                        output_dir=target,
                        prefix=report_name,
                    )
                except OSError as exc:
                    console_error(f"cannot write reports: {exc}", quiet=quiet, no_color=no_color)
                    raise typer.Exit(code=2) from exc
                for item in written:
                    console.print(f"[dim]wrote[/dim] {item.filename}")

        for report in reports:
            console.print(report.summary_line())

        if not any(report.cases for report in reports):
            console.print("[yellow]no cases matched the filters[/yellow]", stderr=True)

        ran_cases = sum(len(report.cases) for report in reports)
        if ran_cases == 0:
            exit_code = 5
        elif any(report.totals.cases_errored for report in reports):
            exit_code = 2
        elif any(report.totals.cases_failed for report in reports):
            exit_code = 1
        else:
            exit_code = 0
        console.print(f"[dim]finished in {elapsed:.0f}ms[/dim]")
        raise typer.Exit(code=exit_code)


def _parse_connector(value: str | None) -> dict | None:
    """Accept ``http`` or ``http:url=http://x,timeout=5`` overrides."""
    if not value:
        return None
    name, _, rest = value.partition(":")
    config: dict[str, str] = {}
    for pair in rest.split(","):
        if not pair.strip():
            continue
        key, _, item = pair.partition("=")
        config[key.strip()] = item.strip()
    return {"type": name.strip(), "config": config}


def _load_env(path: Path) -> dict[str, str]:
    from conversat.cli.common import load_env_file

    try:
        return load_env_file(path)
    except typer.BadParameter as exc:
        raise ConversatError(str(exc)) from exc


def _version() -> str:
    from conversat import __version__

    return __version__

