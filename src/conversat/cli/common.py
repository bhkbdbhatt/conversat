"""Shared CLI helpers: config files, key=value overrides, Typer plumbing."""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from conversat.reporting.console import make_console

APP_NAME = "conversat"

Option = typer.Option
Argument = typer.Argument


def parse_key_value(pairs: list[str] | None) -> dict[str, Any]:
    """Parse ``--var name=Bob`` / ``--var token=abc`` style options.

    Values are decoded as JSON when possible (``true``, ``3``, ``[1,2]``), so
    numbers and booleans arrive at the connector as their real type.
    """
    out: dict[str, Any] = {}
    for raw in pairs or []:
        if "=" not in raw:
            raise typer.BadParameter(f"expected key=value, got {raw!r}")
        key, _, value = raw.partition("=")
        key = key.strip()
        if not key:
            raise typer.BadParameter(f"empty key in {raw!r}")
        try:
            out[key] = json.loads(value)
        except json.JSONDecodeError:
            out[key] = value
    return out


def split_tags(values: list[str] | None) -> set[str]:
    tags: set[str] = set()
    for raw in values or []:
        tags.update(part.strip() for part in raw.split(",") if part.strip())
    return tags


def load_env_file(path: str | os.PathLike[str] | None, *, override: bool = False) -> dict[str, str]:
    """Read a ``.env`` file into ``os.environ`` (missing file is fine)."""
    if path is None:
        return {}
    target = Path(path)
    if not target.is_file():
        raise typer.BadParameter(f"env file not found: {target}")
    loaded: dict[str, str] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        loaded[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return loaded


def template_environment(values: dict[str, Any], *, redact: bool = True) -> dict[str, Any]:
    """Build the variable context exposed to suite templates and connectors."""
    from conversat.utils import redact as redact_value

    context: dict[str, Any] = {key: value for key, value in os.environ.items() if key.startswith("CONVERSAT_")}
    context.update({key: value for key, value in values.items()})
    if redact:
        return redact_value(context)
    return context


def system_environment() -> dict[str, Any]:
    """Small, non-sensitive environment snapshot stored in every report."""
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "os": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "cwd": str(Path.cwd()),
    }


def console_for(quiet: bool = False, no_color: bool = False) -> Any:
    return make_console(quiet=quiet, no_color=no_color)


def error_console(*, quiet: bool = False, no_color: bool = False) -> Any:
    """A rich console bound to stderr (rich only supports that on the Console)."""
    import sys

    from rich.console import Console

    return Console(
        quiet=quiet,
        no_color=no_color or bool(os.environ.get("NO_COLOR")),
        highlight=False,
        file=sys.stderr,
    )


def console_error(
    message: str,
    *,
    hint: str | None = None,
    quiet: bool = False,
    no_color: bool = False,
) -> None:
    """Print a user-facing error to stderr with an optional hint."""
    console = error_console(quiet=quiet, no_color=no_color)
    console.print(f"[bold red]error:[/bold red] {message}")
    if hint:
        console.print(f"[dim]hint: {hint}[/dim]")


def resolve_output_dir(value: str | None, default: str = "reports") -> Path:
    return Path(value) if value else Path(default)


def write_text_file(path: Path, content: str, *, overwrite: bool = False) -> Path:
    """Write a file, refusing to clobber by default."""
    if path.exists() and not overwrite:
        raise typer.BadParameter(f"{path} already exists (use --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def version_option() -> Annotated[str, typer.Option("--version", help="Show the version and exit.")]:
    return Annotated[str, typer.Option("--version", callback=_version_callback, is_eager=True)]


def _version_callback(value: bool) -> None:
    if not value:
        return
    from conversat import __version__

    typer.echo(f"{APP_NAME} {__version__}")
    raise typer.Exit
