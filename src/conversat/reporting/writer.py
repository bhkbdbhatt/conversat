"""Write reports to disk in one or more formats."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from conversat.models.report import RunReport
from conversat.reporting.base import Formatter, FormatterResult, resolve


def write_reports(
    report: RunReport,
    *,
    formats: Sequence[str] | str | None = ("json",),
    output_dir: str | Path = "reports",
    prefix: str | None = None,
    formatters: Sequence[Formatter] | None = None,
) -> list[FormatterResult]:
    """Render ``report`` in every requested format and write the files.

    Formatters without an extension (e.g. ``console``) are rendered but not
    written. Returns one :class:`FormatterResult` per formatter.
    """
    chosen = list(formatters) if formatters is not None else resolve(formats)
    target = Path(output_dir)
    results: list[FormatterResult] = []

    for formatter in chosen:
        content = formatter.format(report)
        filename = formatter.filename_for(report)
        if prefix:
            stem, _, ext = filename.rpartition(".")
            filename = f"{prefix}{'-' if stem else ''}{filename}" if stem else f"{prefix}{filename}"
        if formatter.extension:
            target.mkdir(parents=True, exist_ok=True)
            path = target / filename
            path.write_text(content + ("" if content.endswith("\n") else "\n"), encoding="utf-8")
            results.append(FormatterResult(name=formatter.name, filename=str(path), content=content))
        else:
            results.append(FormatterResult(name=formatter.name, filename="", content=content))
    return results


def save_report(
    report: RunReport,
    path: str | Path,
    *,
    formatter: Formatter | str = "json",
) -> Path:
    """Write a single report to an explicit path."""
    from conversat.reporting.base import get

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved = get(formatter) if isinstance(formatter, str) else formatter
    target.write_text(resolved.format(report) + "\n", encoding="utf-8")
    return target


def load_report(path: str | Path) -> RunReport:
    """Read back a JSON report written by :func:`write_reports`."""
    from conversat.errors import ConversatError
    from conversat.models.report import RunReport as _RunReport

    target = Path(path)
    try:
        return _RunReport.model_validate_json(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConversatError(f"cannot read report: {exc}") from exc
    except ValueError as exc:
        raise ConversatError(f"{target} is not a conversat JSON report: {exc}") from exc


def crawl_payload(report: object) -> str:
    """Serialise a crawl report to YAML (used by ``conversat crawl``)."""
    import yaml

    payload = report.to_suite()  # type: ignore[attr-defined]
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100)
