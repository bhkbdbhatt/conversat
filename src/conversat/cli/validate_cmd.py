"""``conversat validate`` -- parse and check suites without running them."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from conversat.cli.common import Argument, Option, console_for
from conversat.connectors.registry import BUILTINS, available
from conversat.engine.loader import load_suites
from conversat.errors import ConversatError


def register(app: typer.Typer) -> None:
    @app.command("validate")
    def validate(
        suites: Annotated[
            list[Path], Argument(metavar="SUITE [SUITE ...]", help="Suite file, directory or glob.")
        ],
        strict: Annotated[
            bool,
            Option("--strict", help="Also fail on warnings (unknown connector tags, no assertions...)."),
        ] = False,
        quiet: Annotated[bool, Option("--quiet", "-q", help="Only print problems.")] = False,
        no_color: Annotated[bool, Option("--no-color", help="Disable ANSI colours.")] = False,
    ) -> None:
        """Validate suite files, connector settings and assertion strategies."""
        console = console_for(quiet=quiet, no_color=no_color)
        try:
            loaded = load_suites(list(suites))
        except ConversatError as exc:
            console.print(f"[bold red]error:[/bold red] {exc}", stderr=True)
            raise typer.Exit(code=2) from exc

        from conversat.assertions.registry import available as assertion_names

        problems = 0
        warnings = 0

        for suite in loaded:
            issues: list[tuple[str, str]] = []
            case_names: list[str] = []

            if suite.connector.type not in BUILTINS and suite.connector.type not in available():
                issues.append(("$", f"unknown connector type {suite.connector.type!r}"))

            for case in suite.cases:
                case_names.append(case.name)
                turns = case.all_turns()
                assert_turns = [turn for turn in turns if turn.expect]
                if not assert_turns:
                    issues.append((case.name, "no turn has assertions (the bot is never checked)"))
                for turn in turns:
                    for spec in turn.expect:
                        if spec.type not in assertion_names():
                            issues.append((case.name, f"unknown assertion {spec.type!r}"))
                    if turn.send is None and turn.payload:
                        issues.append(
                            (case.name, "turn sends 'payload' only: connector support varies")
                        )
                if case.connector and case.connector.type not in available():
                    issues.append((case.name, f"unknown connector {case.connector.type!r}"))
                for var in _template_names(case):
                    if var.split(".")[0] in {"vars", "case", "suite", "run", "turn"}:
                        continue
                    issues.append((case.name, f"suspicious template variable {var!r}"))

            hard = [item for item in issues if "suspicious" not in item[1]]
            soft = [item for item in issues if "suspicious" in item[1]]
            problems += len(hard)
            warnings += len(soft)

            if quiet and not issues:
                continue

            console.print(
                f"[bold cyan]{suite.name}[/bold cyan] "
                f"[dim]({len(case_names)} cases, connector: {suite.connector.type})[/dim]"
            )
            for name, message in hard:
                console.print(f"  [red]error[/red]   {name}: {message}")
            for name, message in soft:
                console.print(f"  [yellow]warning[/yellow] {name}: {message}")
            if not issues:
                console.print("  [green]ok[/green]")

        total = problems + (warnings if strict else 0)
        if problems:
            console.print(f"[red]{problems} problem(s)[/red], {warnings} warning(s)", stderr=True)
            raise typer.Exit(code=1)
        if warnings and strict:
            console.print(f"[yellow]{warnings} warning(s) (--strict)[/yellow]", stderr=True)
            raise typer.Exit(code=1)
        console.print(f"[green]ok[/green] {len(loaded)} suite(s) validated ({warnings} warning(s))")


def _template_names(case: object) -> set[str]:
    import re


    pattern = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.\-]*)\s*\}\}")
    names: set[str] = set()
    for turn in case.all_turns():  # type: ignore[attr-defined]
        if turn.send:
            names.update(pattern.findall(turn.send))
    return names

