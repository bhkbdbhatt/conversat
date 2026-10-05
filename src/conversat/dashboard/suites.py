"""Browse and edit the YAML suites the dashboard can trigger.

Suites are the unit of work in conversat, so the UI edits them directly as YAML
on disk rather than through a database. Every mutation writes a real
``suites/*.yaml`` file that ``conversat run`` can consume unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from conversat.engine.loader import YAML_SUFFIXES, suite_from_dict, suite_to_dict
from conversat.errors import ConversatError
from conversat.models.suite import TestSuite

MAX_SUITES = 500


class SuiteLibrary:
    """A directory of YAML suite files, loaded on demand."""

    def __init__(self, directory: str | Path = "suites") -> None:
        self.directory = Path(directory)

    # -- discovery -------------------------------------------------------- #
    def files(self) -> list[Path]:
        if self.directory.is_file():
            return [self.directory]
        if not self.directory.is_dir():
            return []
        out: list[Path] = []
        for path in self.directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in YAML_SUFFIXES:
                out.append(path)
        return sorted(out)

    def entries(self) -> Iterator[tuple[Path, int, TestSuite]]:
        """Yield every parseable suite, with its source location."""
        for path, index, suite, error in self.scan():
            if suite is not None and error is None:
                yield path, index, suite

    def scan(self) -> Iterator[tuple[Path, int, TestSuite | None, str | None]]:
        """Yield ``(path, document, suite, error)`` for every candidate.

        Files that fail to parse are reported rather than skipped: a silently
        invisible suite is worse than a visible error in the UI.
        """
        count = 0
        for path in self.files():
            try:
                documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
            except (OSError, yaml.YAMLError) as exc:
                yield path, 0, None, _reason(exc)
                continue
            if not documents:
                yield path, 0, None, "file is empty"
                continue
            for index, document in enumerate(documents):
                candidates = _flatten(document)
                if not candidates:
                    continue
                for candidate in candidates:
                    count += 1
                    if count > MAX_SUITES:  # pragma: no cover - runaway directory
                        return
                    try:
                        suite = suite_from_dict(candidate, name=path.stem)
                    except ConversatError as exc:
                        yield path, index, None, str(exc)
                        continue
                    yield path, index, suite, None

    def list(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path, index, suite, error in self.scan():
            rows.append(self._row(path, index, suite, error))
        return sorted(rows, key=lambda row: (row["error"] is not None, row["name"].lower()))

    @staticmethod
    def _row(path: Path, index: int, suite: TestSuite | None, error: str | None) -> dict[str, Any]:
        if suite is None:
            return {
                "name": path.stem,
                "path": _relative(path),
                "document": index,
                "error": error,
                "modified": _mtime(path),
            }
        tags = sorted({tag for case in suite.cases for tag in suite.effective_tags(case)})
        return {
            "name": suite.name,
            "path": _relative(path),
            "document": index,
            "description": suite.description,
            "connector": suite.connector.label,
            "cases": len(suite.cases),
            "turns": sum(len(case.all_turns()) for case in suite.cases),
            "assertions": sum(
                len(turn.expect) for case in suite.cases for turn in case.all_turns()
            ),
            "tags": tags,
            "enabled": sum(1 for case in suite.cases if case.enabled),
            "modified": _mtime(path),
            "error": None,
        }

    def get(self, name: str) -> dict[str, Any] | None:
        for path, index, suite in self.entries():
            if suite.name == name:
                payload = suite_to_dict(suite)
                payload["path"] = _relative(path)
                payload["document"] = index
                payload["modified"] = _mtime(path)
                payload["yaml"] = yaml.safe_dump(
                    payload, sort_keys=False, allow_unicode=True, width=100
                )
                return payload
        return None

    def path_for(self, name: str) -> Path | None:
        for path, _index, suite in self.entries():
            if suite.name == name:
                return path
        return None

    # -- mutations -------------------------------------------------------- #
    def save(self, payload: dict[str, Any], *, name: str | None = None) -> dict[str, Any]:
        """Create or replace one suite; writes YAML back to disk.

        ``payload`` may be a suite mapping or ``{"yaml": "<text>"}`` -- the
        dashboard editor sends raw YAML so it never needs a YAML parser in the
        browser.
        """
        data = self._as_mapping(payload)
        suite = suite_from_dict(data, name=name)  # raises ConversatError with a field-level message
        target_name = suite.name
        existing = self.path_for(target_name)
        document_index = self._document_index(existing, target_name) if existing else None

        target = existing or self._new_path(target_name)
        documents = self._read_documents(existing) if existing else []
        encoded = suite_to_dict(suite)
        if document_index is None:
            documents.append(encoded)
        else:
            documents[document_index] = encoded

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                yaml.safe_dump_all(documents, sort_keys=False, allow_unicode=True, width=100),
                encoding="utf-8",
            )
        except OSError as exc:
            raise ConversatError(f"cannot write {target}: {exc}") from exc

        saved = self.get(target_name)
        if saved is None:  # pragma: no cover - the file was just written
            raise ConversatError(f"suite {target_name!r} could not be read back")
        return saved

    def delete(self, name: str) -> bool:
        """Delete a suite; removes the whole file when it held only that one."""
        target = self.path_for(name)
        if target is None:
            return False
        documents = [doc for doc in self._read_documents(target) if not _is_suite(doc, name)]
        if not documents:
            target.unlink(missing_ok=True)
            return True
        target.write_text(
            yaml.safe_dump_all(documents, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
        return True

    def _new_path(self, name: str) -> Path:
        target = self.directory / f"{_slug(name)}.yaml"
        counter = 2
        while target.exists():
            target = self.directory / f"{_slug(name)}-{counter}.yaml"
            counter += 1
        return target

    def _document_index(self, path: Path | None, name: str) -> int | None:
        if path is None:
            return None
        for index, document in enumerate(self._read_documents(path)):
            if _is_suite(document, name):
                return index
        return None

    @staticmethod
    def _read_documents(path: Path | None) -> list[Any]:
        if path is None or not path.is_file():
            return []
        try:
            documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except (OSError, yaml.YAMLError) as exc:
            raise ConversatError(f"cannot read {path}: {exc}") from exc
        return [doc for doc in documents if doc is not None]

    def validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Check a suite without writing it (used by the editor as you type).

        Never raises: the editor wants a list of problems, not an exception.
        """
        try:
            suite = suite_from_dict(self._as_mapping(payload))
        except ConversatError as exc:
            return {"valid": False, "errors": [str(exc)], "cases": []}

        errors: list[str] = []
        if not suite.cases:
            errors.append("a suite needs at least one case")
        for case in suite.cases:
            if not case.name.strip():
                errors.append("every case needs a name")
            if not case.all_turns() and case.enabled:
                errors.append(f"case {case.name!r} has no turns to run")
        return {
            "valid": not errors,
            "errors": errors,
            "suite": suite_to_dict(suite),
            "cases": [case.name for case in suite.cases],
            "tags": sorted({tag for case in suite.cases for tag in suite.effective_tags(case)}),
            "connector": suite.connector.label,
        }

    @staticmethod
    def _as_mapping(payload: dict[str, Any] | None) -> dict[str, Any]:
        """Accept either a suite mapping or ``{"yaml": "<text>"}``."""
        payload = payload or {}
        if isinstance(payload.get("yaml"), str):
            try:
                document = yaml.safe_load(payload["yaml"])
            except yaml.YAMLError as exc:
                raise ConversatError(_reason(exc)) from exc
            if document is None:
                raise ConversatError("the suite is empty")
            if not isinstance(document, dict):
                raise ConversatError("a suite must be a YAML mapping")
            payload = document
        return {
            k: v for k, v in payload.items() if k not in ("path", "document", "modified", "yaml")
        }


def _flatten(document: Any) -> list[Any]:
    if isinstance(document, list):
        return [item for item in document if isinstance(item, dict)]
    return [document] if isinstance(document, dict) else []


def _is_suite(document: Any, name: str) -> bool:
    candidates = document if isinstance(document, list) else [document]
    return any(isinstance(item, dict) and item.get("name") == name for item in candidates)


def _slug(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name.strip().lower())
    return "-".join(part for part in cleaned.split("-") if part) or "suite"


def _reason(exc: Exception) -> str:
    mark = getattr(exc, "problem_mark", None)
    if mark is not None:
        return f"invalid YAML at line {mark.line + 1}: {getattr(exc, 'problem', exc)}"
    return str(exc)


def _relative(path: Path) -> str:
    return path.name


def _mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    except OSError:  # pragma: no cover - race with deletion
        return None
