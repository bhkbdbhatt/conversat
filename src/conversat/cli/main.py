"""The conversat CLI (Typer).

    conversat run examples/suites/smoke.yaml
    conversat crawl --suite examples/suites/smoke.yaml --max-depth 2
    conversat report reports/run.json --format markdown
"""

from __future__ import annotations

import typer

from conversat import __version__
from conversat.cli import (
    crawl_cmd,
    import_cmd,
    init_cmd,
    report_cmd,
    run_cmd,
    serve_cmd,
    validate_cmd,
)
from conversat.cli.common import APP_NAME

app = typer.Typer(
    name=APP_NAME,
    help=(
        "Conversational testing platform: run chatbot conversations described in YAML "
        "and assert on the real replies."
    ),
    add_completion=True,
    no_args_is_help=True,
    rich_markup_mode="rich",
)

init_cmd.register(app)
validate_cmd.register(app)
run_cmd.register(app)
crawl_cmd.register(app)
report_cmd.register(app)
report_cmd.register_summary(app)
import_cmd.register(app)
serve_cmd.register(app)


@app.command("version")
def version() -> None:
    """Print the conversat version."""
    typer.echo(f"{APP_NAME} {__version__}")


def main() -> None:
    """Entry point for the ``conversat`` console script."""
    from conversat.reporting.console import _force_utf8_streams

    # Before Typer renders anything: a legacy Windows code page would raise
    # UnicodeEncodeError on the first non-ASCII glyph in --help.
    _force_utf8_streams()
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
