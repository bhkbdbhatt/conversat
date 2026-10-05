"""``conversat crawl`` -- explore a bot and generate a suite."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from conversat.cli.common import Option, console_for, console_error
from conversat.crawler.crawler import CrawlOptions, crawl
from conversat.crawler.followups import DEFAULT_FOLLOW_UPS
from conversat.crawler.suggest import common_responses
from conversat.engine.loader import load_suite
from conversat.errors import ConversatError
from conversat.models.crawler import CrawlConfig
from conversat.models.suite import ConnectorConfig


def register(app: typer.Typer) -> None:
    @app.command("crawl")
    def crawl_cmd(
        suite: Annotated[
            Path | None,
            Option("--suite", "-s", help="Suite whose connector should be crawled."),
        ] = None,
        connector: Annotated[
            str | None,
            Option("--connector", "-c", help="Connector override, e.g. http:url=http://host/chat"),
        ] = None,
        seeds: Annotated[
            list[str] | None, Option("--seed", help="Opening message (repeatable).")
        ] = None,
        max_depth: Annotated[int, Option("--max-depth", "-d", help="Maximum conversation depth.")] = 2,
        max_turns: Annotated[int, Option("--max-turns", "-n", help="Hard budget of bot calls.")] = 20,
        branching: Annotated[
            int, Option("--branching", "-b", help="Follow-ups explored per reply.")
        ] = 2,
        concurrency: Annotated[int, Option("--concurrency", "-j", help="Parallel branches.")] = 2,
        timeout: Annotated[float | None, Option("--timeout", help="Per-turn timeout in seconds.")] = None,
        follow_ups: Annotated[
            list[str] | None, Option("--follow-up", help="Extra follow-up template (repeatable).")
        ] = None,
        error_keywords: Annotated[
            list[str] | None, Option("--error-keyword", help="Extra error phrase to flag.")
        ] = None,
        output: Annotated[
            Path | None, Option("--output", "-o", help="Write the generated suite here.")
        ] = None,
        json_output: Annotated[
            bool, Option("--json", help="Print the crawl report as JSON instead of YAML.")
        ] = False,
        no_cases: Annotated[
            bool, Option("--no-cases", help="Do not generate test cases from the crawl.")
        ] = False,
        suite_name: Annotated[
            str, Option("--name", help="Name for the generated suite.")
        ] = "crawled-bot",
        quiet: Annotated[bool, Option("--quiet", "-q", help="Only print the summary.")] = False,
        no_color: Annotated[bool, Option("--no-color", help="Disable ANSI colours.")] = False,
    ) -> None:
        """Explore a bot breadth-first and emit findings plus test cases."""
        console = console_for(quiet=quiet, no_color=no_color)

        connector_config, seed_list = _resolve_target(suite, connector, seeds)
        if connector_config is None:
            console_error(
                "no connector to crawl",
                hint="pass --suite <file> or --connector http:url=http://host/chat",
                quiet=quiet,
                no_color=no_color,
            )
            raise typer.Exit(code=2)

        config = CrawlConfig(
            seeds=seed_list or ["Hello!"],
            max_depth=max_depth,
            max_turns=max_turns,
            branching=branching,
            concurrency=concurrency,
            timeout=timeout,
            follow_ups=[*DEFAULT_FOLLOW_UPS, *(follow_ups or [])],
            error_keywords=list(error_keywords or []),
        )

        options = CrawlOptions(
            max_parallel=concurrency,
            collect_cases=not no_cases,
            suite_name=suite_name,
        )

        async def _run() -> Any:
            return await crawl(
                config,
                connector_config,
                options=options,
                on_event=_progress(console, quiet),
            )

        try:
            report = asyncio.run(_run())
        except ConversatError as exc:
            console_error(str(exc), quiet=quiet, no_color=no_color)
            raise typer.Exit(code=2) from exc

        _print_summary(console, report, quiet=quiet)

        payload = report.model_dump(mode="json")
        if json_output:
            import json

            text = json.dumps(payload, indent=2)
        else:
            text = yaml.safe_dump(
                report.to_suite(name=suite_name), sort_keys=False, allow_unicode=True, width=100
            )

        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text, encoding="utf-8")
            if not quiet:
                console.print(f"[green]wrote[/green] {output}")
        elif not quiet:
            console.print(text)

        raise typer.Exit(code=0 if report.ok else 1)


def _resolve_target(
    suite: Path | None,
    connector: str | None,
    seeds: list[str] | None,
) -> tuple[ConnectorConfig | None, list[str] | None]:
    if connector:
        name, _, rest = connector.partition(":")
        config: dict[str, Any] = {}
        for pair in rest.split(","):
            if pair.strip():
                key, _, value = pair.partition("=")
                config[key.strip()] = value.strip()
        return ConnectorConfig(type=name.strip(), config=config), seeds

    if suite:
        loaded = load_suite(suite)
        connector_config = loaded.connector
        if seeds:
            return connector_config, seeds
        return connector_config, _seed_from_cases(loaded)

    return None, seeds


def _seed_from_cases(loaded: object) -> list[str]:
    """Use the first user message of each case as a crawl seed."""
    seeds: list[str] = []
    for case in loaded.cases:  # type: ignore[attr-defined]
        turns = case.all_turns()
        if not turns:
            continue
        first = turns[0].send
        if first and first not in seeds:
            seeds.append(first)
    return seeds


def _progress(console: Any, quiet: bool):
    if quiet:
        return None

    def on_event(event: str, payload: Any) -> None:
        if event == "crawl_node":
            status = getattr(payload, "status", "?")
            style = {"passed": "green", "error": "red"}.get(str(status), "yellow")
            reply = payload.response.text if payload.response else ""
            console.print(
                f"  [{style}]{status}[/{style}] d{payload.depth} "
                f"[cyan]>[/cyan] {payload.request[:60]} [dim]|[/dim] "
                f"[white]{reply.replace(chr(10), ' ')[:80]}[/white]",
                highlight=False,
            )

    return on_event


def _print_summary(console: Any, report: Any, *, quiet: bool = False) -> None:
    coverage = report.coverage
    console.print(
        f"[bold]crawl[/bold] {report.connector}: {coverage.nodes} turns, "
        f"depth {coverage.max_depth_reached}, {coverage.unique_responses} unique replies, "
        f"p95 {coverage.response_p95_ms:.0f}ms"
    )
    if coverage.errored:
        console.print(f"[red]{coverage.errored} errored turn(s)[/red]")
    for kind, count in sorted(_count_kinds(report)):
        console.print(f"  [yellow]{kind}[/yellow]: {count}")

    if not quiet:
        repeated = [item for item in common_responses(report) if item[1] > 1]
        if repeated:
            console.print("  [dim]repeated replies:[/dim]")
            for text, count in repeated[:3]:
                console.print(f"    x{count} [white]{text[:70]}[/white]")
    if report.suggested_cases:
        console.print(
            f"[green]generated {len(report.suggested_cases)} test case(s)[/green] "
            f"from {len(report.transcripts())} transcript(s)"
        )


def _count_kinds(report: Any) -> list[tuple[str, int]]:
    counter: dict[str, int] = {}
    for issue in report.issues:
        counter[issue.kind] = counter.get(issue.kind, 0) + 1
    return list(counter.items())

