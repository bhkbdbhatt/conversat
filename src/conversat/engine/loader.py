"""YAML suite loading.

Supports three shapes of file:

1. A single suite (``name`` + ``cases``).
2. A list of suites.
3. A multi-document file (``---`` separated).
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from conversat.errors import SuiteParseError
from conversat.models.suite import ConnectorConfig, TestSuite

YAML_SUFFIXES = (".yaml", ".yml")
_SUITE_KEYS = {"name", "cases", "connector"}


def _read_yaml(path: Path) -> list[Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SuiteParseError(f"cannot read suite file ({exc})", path=str(path)) from exc
    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:
        raise SuiteParseError(_yaml_error(exc), path=str(path)) from exc
    return [doc for doc in documents if doc is not None]


def _yaml_error(exc: yaml.YAMLError) -> str:
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or str(exc)
    if mark is not None:
        return f"invalid YAML at line {mark.line + 1}, column {mark.column + 1}: {problem}"
    return f"invalid YAML: {problem}"


def _looks_like_suite(payload: Any) -> bool:
    return isinstance(payload, dict) and bool(_SUITE_KEYS & set(payload))


def _validate(payload: Any, *, path: str, location: str | None = None) -> TestSuite:
    try:
        return TestSuite.model_validate(payload)
    except ValidationError as exc:
        raise SuiteParseError(_format_validation_error(exc), path=path, location=location) from exc


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "<root>"
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return "; ".join(parts) or str(exc)


def suite_from_dict(payload: Any, *, name: str | None = None) -> TestSuite:
    """Validate a single suite payload (already-loaded YAML/JSON)."""
    if not isinstance(payload, dict):
        raise SuiteParseError(
            f"a suite must be a mapping, got {type(payload).__name__}",
            location=name,
        )
    data = dict(payload)
    if name and "name" not in data:
        data["name"] = name
    try:
        return TestSuite.model_validate(data)
    except ValidationError as exc:
        raise SuiteParseError(_format_validation_error(exc), location=name) from exc


def load_suite(
    path: str | os.PathLike[str],
    *,
    overrides: dict[str, Any] | None = None,
) -> TestSuite:
    """Load exactly one suite from a YAML file.

    Raises :class:`SuiteParseError` when the file holds zero or many suites.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise SuiteParseError("suite file not found", path=str(file_path))

    suites = load_suites(file_path, overrides=overrides)
    if len(suites) != 1:
        raise SuiteParseError(
            f"expected exactly one suite, found {len(suites)}; use load_suites() for multi-suite files",
            path=str(file_path),
        )
    return suites[0]


def load_suites(
    path: str | os.PathLike[str] | Iterable[str | os.PathLike[str]],
    *,
    overrides: dict[str, Any] | None = None,
) -> list[TestSuite]:
    """Load one or more suites from a file, a directory or a glob pattern."""
    paths = resolve_paths(path)
    if not paths:
        raise SuiteParseError("no suite files matched", path=str(path))

    suites: list[TestSuite] = []
    for file_path in paths:
        suites.extend(_load_file(file_path, overrides=overrides))

    seen: dict[str, Path] = {}
    for suite in suites:
        previous = seen.get(suite.name)
        if previous is not None:
            raise SuiteParseError(
                f"duplicate suite name {suite.name!r} (also defined in {previous})",
                path=str(file_path),
            )
        seen[suite.name] = file_path
    return suites


def _load_file(file_path: Path, *, overrides: dict[str, Any] | None) -> list[TestSuite]:
    documents = _read_yaml(file_path)
    if not documents:
        raise SuiteParseError("file is empty", path=str(file_path))

    out: list[TestSuite] = []
    for index, document in enumerate(documents):
        location = f"document #{index + 1}"
        if isinstance(document, list):
            for item in document:
                out.append(_finalize(_validate(item, path=str(file_path), location=location), overrides))
            continue
        out.append(
            _finalize(_validate(document, path=str(file_path), location=location), overrides)
        )
    return out


def _finalize(suite: TestSuite, overrides: dict[str, Any] | None) -> TestSuite:
    if not overrides:
        return suite
    updates: dict[str, Any] = {}
    connector_override = overrides.get("connector") or overrides.get("connector_config")
    if connector_override:
        updates["connector"] = ConnectorConfig.model_validate(connector_override)
    variables = overrides.get("variables")
    if isinstance(variables, dict):
        updates["variables"] = {**suite.variables, **variables}
    timeout = overrides.get("timeout")
    if timeout is not None:
        updates["defaults"] = suite.defaults.model_copy(update={"timeout": float(timeout)})
    name = overrides.get("name")
    if name:
        updates["name"] = str(name)
    return suite.model_copy(update=updates) if updates else suite


def resolve_paths(path: str | os.PathLike[str] | Iterable[str | os.PathLike[str]]) -> list[Path]:
    """Normalise the CLI/loader input into a sorted list of existing files."""
    candidates: list[str | os.PathLike[str]]
    if isinstance(path, (str, os.PathLike)):
        candidates = [path]
    else:
        candidates = list(path)

    out: list[Path] = []
    for candidate in candidates:
        text = str(candidate)
        if any(ch in text for ch in "*?["):
            import glob

            out.extend(Path(match) for match in sorted(glob.glob(text, recursive=True)))
            continue
        target = Path(text)
        if target.is_dir():
            out.extend(sorted(p for p in target.rglob("*") if p.suffix.lower() in YAML_SUFFIXES))
        elif target.exists():
            out.append(target)
        else:
            raise SuiteParseError("path does not exist", path=text)
    return [p for p in out if p.suffix.lower() in YAML_SUFFIXES or p.is_file()]


def dump_suite(suite: TestSuite, path: str | os.PathLike[str], *, overwrite: bool = True) -> Path:
    """Write a suite back to YAML (used by the crawler and ``conversat init``)."""
    target = Path(path)
    if target.exists() and not overwrite:
        raise SuiteParseError("refusing to overwrite existing file", path=str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = suite.model_dump(mode="json", by_alias=True, exclude_none=True)
    target.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    return target


def suite_to_dict(suite: TestSuite) -> dict[str, Any]:
    """JSON-safe dict for a suite (round-trips through ``suite_from_dict``)."""
    return suite.model_dump(mode="json", by_alias=True, exclude_none=True)


def merge_case_names(suites: Sequence[TestSuite]) -> list[str]:
    return [case.name for suite in suites for case in suite.cases]
