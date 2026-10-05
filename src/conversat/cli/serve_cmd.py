"""``conversat serve`` / ``conversat connectors`` / ``conversat assertions``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from conversat.cli.common import Option, console_for
from conversat.connectors.registry import BUILTINS, available, describe_connector


def register(app: typer.Typer) -> None:
    @app.command("serve")
    def serve(
        host: Annotated[str, Option("--host", help="Bind address.")] = "127.0.0.1",
        port: Annotated[int, Option("--port", "-p", help="TCP port.")] = 8080,
        reports: Annotated[
            Path, Option("--reports", "-r", help="Directory holding run JSON reports.")
        ] = Path("reports"),
        suites: Annotated[
            Path, Option("--suites", help="Directory of YAML suites the UI can trigger.")
        ] = Path("suites"),
        static: Annotated[
            Path | None,
            Option("--static", help="Serve the built UI from here instead of dashboard/dist."),
        ] = None,
        reload: Annotated[bool, Option("--reload", help="Auto-reload on code changes.")] = False,
        log_level: Annotated[str, Option("--log-level", help="uvicorn log level.")] = "info",
    ) -> None:
        """Serve the dashboard (API + built web UI) over the stored run reports."""
        console = console_for()
        try:
            import uvicorn

            from conversat.dashboard.app import _ui_dir, create_app
        except ImportError as exc:  # pragma: no cover - deps are declared
            console.print(f"[red]dashboard dependencies missing: {exc}[/red]", stderr=True)
            raise typer.Exit(code=2) from exc

        app = create_app(reports, suites=suites, static_dir=static)
        console.print(f"[cyan]conversat dashboard[/cyan] on [bold]http://{host}:{port}[/bold]")
        console.print(f"  reports: {reports.resolve()}")
        console.print(f"  suites:  {suites.resolve()}")
        if _ui_dir(static) is None:
            console.print(
                "  [yellow]ui:[/yellow] not built -- run "
                "[bold]npm --prefix dashboard install && npm --prefix dashboard run build[/bold]"
            )
        console.print(f"  api docs: http://{host}:{port}/docs")
        uvicorn.run(app, host=host, port=port, log_level=log_level)

        if reload:  # pragma: no cover - reload mode restarts the process
            console.print("[yellow]note: --reload is handled by uvicorn when a import string is used[/yellow]")

    @app.command("connectors")
    def connectors() -> None:
        """List the available bot connectors."""
        console = console_for()
        console.print("[bold]built-in connectors[/bold]")
        for name in sorted(BUILTINS):
            console.print(f"  [cyan]{name:<10}[/cyan] {describe_connector(name)}")
        console.print("\n[bold]example[/bold]")
        console.print("  connector:")
        console.print("    type: http")
        console.print("    config:")
        console.print('      url: "http://127.0.0.1:8099/chat"')
        console.print("      response_text_path: reply")
        console.print(f"\n[dim]{len(available())} connector(s) registered[/dim]")

    @app.command("assertions")
    def assertions() -> None:
        """List the available assertion strategies."""
        from conversat.assertions.registry import available as strategies

        console = console_for()
        console.print("[bold]assertion strategies[/bold] (use as YAML shorthand keys)")
        for name in strategies():
            console.print(f"  [cyan]{name}[/cyan]")
        console.print("\n[bold]example[/bold]")
        console.print("  - send: 'hello'")
        console.print("    expect:")
        console.print("      - contains: hello")
        console.print("      - not_contains: error")
        console.print("      - type: response_time_under")
        console.print("        value: 2000")
