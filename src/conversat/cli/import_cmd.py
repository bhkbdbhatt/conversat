"""``conversat import`` -- turn an exported conversation into a suite.

conversat import chat.json
conversat import support-tickets.csv --format csv --name refunds
conversat import chat.md --output suites/chat.yaml --run
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Annotated, Any

import typer

from conversat.cli.common import Argument, Option, console_error, console_for
from conversat.engine.loader import dump_suite
from conversat.errors import ConversatError
from conversat.importer import available_formats, import_conversation

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def register(app: typer.Typer) -> None:
    @app.command("import")
    def import_cmd(
        files: Annotated[
            list[Path],
            Argument(metavar="FILE [FILE ...]", help="Conversation export(s) to import."),
        ],
        fmt: Annotated[
            str | None,
            Option(
                "--format",
                "-f",
                help="Force the input format (default: detect it from the file and content).",
            ),
        ] = None,
        name: Annotated[str | None, Option("--name", help="Name for the generated suite.")] = None,
        connector: Annotated[
            str | None,
            Option(
                "--connector",
                "-c",
                help="Use a live connector instead of replaying the captured replies, "
                "e.g. http:url=http://127.0.0.1:8099/chat",
            ),
        ] = None,
        assertions: Annotated[
            str, Option("--assertions", help="Assertions to generate: contains, exact or none.")
        ] = "contains",
        tags: Annotated[
            str | None, Option("--tags", help="Comma-separated tags for every case.")
        ] = None,
        output: Annotated[
            Path | None, Option("--output", "-o", help="Write the suite here instead of stdout.")
        ] = None,
        list_formats: Annotated[
            bool, Option("--list-formats", help="Show the supported input formats and exit.")
        ] = False,
        run: Annotated[
            bool, Option("--run", help="Run the generated suite straight away.")
        ] = False,
        quiet: Annotated[bool, Option("--quiet", "-q", help="Only print the summary.")] = False,
        no_color: Annotated[bool, Option("--no-color", help="Disable ANSI colours.")] = False,
    ) -> None:
        """Convert a conversation export (JSON, CSV, XML, Markdown, …) into a suite."""
        console = console_for(quiet=quiet, no_color=no_color)

        if list_formats:
            console.print("[bold]supported input formats[/bold]")
            for info in available_formats():
                extensions = ", ".join(info.extensions) or "-"
                console.print(
                    f"  [cyan]{info.name:<10}[/cyan] [dim]{extensions:<28}[/dim] {info.description}"
                )
            console.print("\n[bold]example[/bold]")
            console.print("  conversat import chat.json --output suites/chat.yaml --run")
            raise typer.Exit(code=0)

        if not files:
            console_error("no input file given", hint="pass one or more files, or --list-formats")
            raise typer.Exit(code=2)

        style = assertions.strip().lower()
        if style not in ("contains", "exact", "none"):
            console_error(
                f"unknown --assertions value {assertions!r}",
                hint="use contains, exact or none",
                quiet=quiet,
                no_color=no_color,
            )
            raise typer.Exit(code=2)

        tag_list = [tag.strip() for tag in (tags or "").split(",") if tag.strip()] or ["imported"]
        written: list[Path] = []
        used_names: set[str] = set()
        exit_code = 0

        for path in files:
            suite_name = _disambiguate(name or path.stem, used_names)
            try:
                result = import_conversation(
                    _read(path),
                    fmt=fmt,
                    filename=path.name,
                    name=suite_name,
                    connector=connector,
                    assertions=style,  # type: ignore[arg-type]
                    tags=tag_list,
                )
            except ConversatError as exc:
                console_error(str(exc), quiet=quiet, no_color=no_color)
                raise typer.Exit(code=2) from exc

            used_names.add(result.suite.name)
            target = output or path.with_suffix(".conversat.yaml")
            if output and len(files) > 1:
                target = _unique(output.with_name(f"{output.stem}-{path.stem}{output.suffix}"))

            try:
                dump_suite(result.suite, target)
            except ConversatError as exc:
                console_error(str(exc), quiet=quiet, no_color=no_color)
                raise typer.Exit(code=2) from exc
            written.append(target)

            if not quiet:
                summary = result.summary()
                console.print(
                    f"[green]imported[/green] [cyan]{path.name}[/cyan] "
                    f"as [bold]{summary['name']}[/bold] "
                    f"({summary['format']}, {summary['messages']} message(s) -> "
                    f"{summary['cases']} case(s), {summary['turns']} turn(s))"
                )
                for warning in result.warnings:
                    console.print(f"  [yellow]note:[/yellow] {warning}")

            if run:
                exit_code |= _run(result.suite, console, quiet=quiet, no_color=no_color)

        for target in written:
            console.print(f"[dim]wrote[/dim] {target}")

        if not run and not quiet:
            console.print(
                f"[dim]run it with[/dim] conversat run {written[0]}" if len(written) == 1 else ""
            )
        raise typer.Exit(code=exit_code)

    @app.command("formats")
    def formats_cmd() -> None:
        """List the conversation formats ``conversat import`` understands."""
        console = console_for()
        console.print("[bold]conversation import formats[/bold]")
        for info in available_formats():
            extensions = ", ".join(info.extensions) or "-"
            console.print(
                f"  [cyan]{info.name:<10}[/cyan] [dim]{extensions:<28}[/dim] {info.description}"
            )
            console.print(f"  {'':10} [dim]e.g. {info.example.splitlines()[0][:80]}[/dim]")


def _disambiguate(name: str, used: set[str]) -> str:
    """Two exports can share a stem (``chat.json`` and ``chat.md``)."""
    if name not in used:
        return name
    for index in range(2, 100):
        candidate = f"{name}-{index}"
        if candidate not in used:
            return candidate
    return f"{name}-{uuid.uuid4().hex[:6]}"  # pragma: no cover - 100 collisions


def _unique(path: Path) -> Path:
    """``out-chat.yaml`` -> ``out-chat-2.yaml`` when two sources share a stem."""
    if not path.exists():
        return path
    for index in range(2, 100):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path  # pragma: no cover - 100 collisions on one stem is absurd


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            raise ConversatError(f"{path} is too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB)")
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ConversatError(f"cannot read {path}: {exc}") from exc
    except ConversatError:
        raise


def _run(suite: Any, console: Any, *, quiet: bool, no_color: bool) -> int:
    import asyncio

    from conversat.engine.runner import TestRunner

    try:
        report = asyncio.run(TestRunner(suite).run())
    except ConversatError as exc:
        console_error(str(exc), quiet=quiet, no_color=no_color)
        return 2
    console.print(report.summary_line())
    return report.exit_code()


def _dump_preview(result: Any) -> str:  # pragma: no cover - debugging aid
    return json.dumps(result.summary(), indent=2)
