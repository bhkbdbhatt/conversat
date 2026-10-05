"""FastAPI dashboard API for conversat.

Phase 7: ``conversat run`` writes JSON reports to disk, this module exposes them
over HTTP -- and, when the SvelteKit app has been built, serves that app from
the same origin so ``conversat serve`` is the only command a user needs.

    conversat serve --reports reports --suites examples/suites

Everything is local and single-user by design: no auth, no database.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from conversat.dashboard.runs import RunService
from conversat.dashboard.store import CrawlStore, RunStore, store_from_reports
from conversat.dashboard.suites import SuiteLibrary
from conversat.errors import ConversatError

DEFAULT_HISTORY = 50
#: Origins allowed by the dev server (Vite) and any local SPA build.
DEFAULT_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
)


def create_app(
    directory: str | Path = "reports",
    *,
    load_history: bool = True,
    suites: str | Path = "suites",
    static_dir: str | Path | None = None,
    cors_origins: tuple[str, ...] = DEFAULT_ORIGINS,
    history: int = DEFAULT_HISTORY,
) -> Any:
    """Build the FastAPI application."""
    store = RunStore(directory, history=history)
    crawls = CrawlStore(directory, history=history)
    library = SuiteLibrary(suites)
    runs = RunService(store, output_dir=directory, history=history)
    if load_history:
        store.load_disk()
        crawls.load_disk()

    app = FastAPI(
        title="conversat dashboard API",
        version="0.1.0",
        description="Run conversational test suites and inspect the results.",
    )
    app.state.store = store
    app.state.crawls = crawls
    app.state.suites = library
    app.state.runs = runs

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def bad_request(exc: ConversatError) -> HTTPException:
        return HTTPException(status_code=400, detail=str(exc))

    # -- meta -------------------------------------------------------------- #
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": _version(),
            "runs": len(store),
            "crawls": len(crawls),
            "suites": len(library.list()),
            "reports_dir": str(store.directory),
            "suites_dir": str(library.directory),
            "ui": _ui_dir(static_dir) is not None,
            "live": [
                item["run_id"] for item in runs.list() if item["status"] in ("queued", "running")
            ],
        }

    @app.get("/api/stats")
    def stats() -> dict[str, Any]:
        reports = list(store)
        return {
            "runs": len(reports),
            "cases": sum(len(r.cases) for r in reports),
            "failed_cases": sum(len(r.failed_cases) for r in reports),
            "assertions": sum(r.totals.assertions for r in reports),
            "avg_duration_ms": (
                round(sum(r.duration_ms for r in reports) / len(reports), 1) if reports else 0.0
            ),
        }

    @app.get("/api/trends")
    def trends(limit: Annotated[int, Query(ge=1, le=200)] = 30) -> list[dict[str, Any]]:
        return store.trends(limit=limit)

    # -- runs -------------------------------------------------------------- #
    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        return store.list()

    @app.post("/api/runs", status_code=202)
    async def start_run(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        """Queue a run and return immediately; follow it over the WebSocket."""
        suites = payload.get("suites") or payload.get("suite")
        if isinstance(suites, str):
            suites = [suites]
        if not suites:
            raise HTTPException(status_code=422, detail="pass at least one suite path")
        try:
            started = runs.start(suites, payload.get("options") or {})
        except ConversatError as exc:
            raise bad_request(exc) from exc
        return {"started": [item.snapshot() for item in started]}

    @app.get("/api/runs/active")
    def active_runs() -> list[dict[str, Any]]:
        return [item for item in runs.list() if item["status"] in ("queued", "running")]

    @app.get("/api/runs/{run_id}")
    def run(run_id: str) -> dict[str, Any]:
        report = store.get(run_id)
        if report is None:
            raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
        return json.loads(report.model_dump_json())

    @app.get("/api/runs/{run_id}/turns")
    def run_turns(run_id: str) -> list[dict[str, Any]]:
        if store.get(run_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
        return store.turns(run_id)

    @app.get("/api/runs/{run_id}/cases")
    def run_cases(run_id: str) -> list[dict[str, Any]]:
        """Per-case results for one run, including each case's turns."""
        report = store.get(run_id)
        if report is None:
            raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
        return [
            {
                "name": case.name,
                "status": case.status.value,
                "tags": case.tags,
                "connector": case.connector,
                "turns": len(case.turns),
                "duration_ms": round(case.duration_ms, 1),
                "error": case.error,
                "transcript": [
                    {
                        "index": turn.index,
                        "name": turn.name,
                        "status": turn.status.value,
                        "request": turn.request,
                        "reply": turn.response.text if turn.response else None,
                        "error": turn.error,
                        "duration_ms": round(turn.duration_ms, 1),
                        "attempts": turn.attempts,
                        "assertions": [a.model_dump(mode="json") for a in turn.assertions],
                    }
                    for turn in case.turns
                ],
            }
            for case in report.cases
        ]

    @app.get("/api/cases")
    def cases() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for report in store:
            for case in report.cases:
                out.append(
                    {
                        "run_id": report.run_id,
                        "suite": report.suite,
                        "name": case.name,
                        "status": case.status.value,
                        "tags": case.tags,
                        "turns": len(case.turns),
                        "duration_ms": round(case.duration_ms, 1),
                    }
                )
        return out

    @app.get("/api/cases/history")
    def case_history(
        name: Annotated[str, Query(min_length=1)],
        limit: Annotated[int, Query(ge=1, le=200)] = 25,
    ) -> list[dict[str, Any]]:
        """Every recorded run of one case, for the scenario detail page."""
        return store.case_history(name, limit=limit)

    # -- live progress ----------------------------------------------------- #
    @app.websocket("/ws/runs/{run_id}")
    async def live_run(websocket: WebSocket, run_id: str) -> None:
        await websocket.accept()
        live = runs.get(run_id)
        if live is None:
            report = store.get(run_id)
            if report is None:
                await websocket.send_json({"type": "error", "error": f"unknown run {run_id!r}"})
                await websocket.close()
                return
            await websocket.send_json(
                {
                    "type": "replay",
                    "run_id": run_id,
                    "status": "passed" if report.ok else "failed",
                    "finished": True,
                    "totals": report.totals.model_dump(mode="json"),
                }
            )
            await websocket.close()
            return

        queue = live.subscribe()
        try:
            await websocket.send_json({"type": "snapshot", **live.snapshot()})
            for event in list(live.events):
                await websocket.send_json(event)
            if not live.active:
                await websocket.close()
                return
            while True:
                event = await queue.get()
                await websocket.send_json(event)
                if event.get("type") == "done":
                    await websocket.close()
                    return
        except (WebSocketDisconnect, RuntimeError):  # pragma: no cover - client went away
            pass
        finally:
            live.unsubscribe(queue)

    # -- suites ------------------------------------------------------------ #
    @app.get("/api/suites")
    def list_suites() -> dict[str, Any]:
        return {"directory": str(library.directory), "suites": library.list()}

    @app.get("/api/suites/{name}")
    def get_suite(name: str) -> dict[str, Any]:
        payload = library.get(name)
        if payload is None:
            raise HTTPException(status_code=404, detail=f"unknown suite {name!r}")
        return payload

    @app.post("/api/suites", status_code=201)
    def create_suite(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return library.save(payload)
        except ConversatError as exc:
            raise bad_request(exc) from exc

    @app.put("/api/suites/{name}")
    def update_suite(name: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return library.save(payload, name=name)
        except ConversatError as exc:
            raise bad_request(exc) from exc

    @app.delete("/api/suites/{name}", status_code=204, response_class=Response, response_model=None)
    def delete_suite(name: str) -> Response:
        if not library.delete(name):
            raise HTTPException(status_code=404, detail=f"unknown suite {name!r}")
        return Response(status_code=204)

    @app.post("/api/suites/validate")
    def validate_suite(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return library.validate(payload)

    # -- conversation import ---------------------------------------------- #
    @app.get("/api/importers")
    def importers() -> list[dict[str, Any]]:
        """Input formats the importer understands, for the upload UI."""
        from conversat.importer import available_formats

        return [
            {
                "name": info.name,
                "extensions": list(info.extensions),
                "description": info.description,
                "example": info.example,
            }
            for info in available_formats()
        ]

    @app.post("/api/importers/detect")
    def detect_import(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Report which parser would be used, without building a suite."""
        from conversat.errors import ConversatError as _ConversatError
        from conversat.importer import detect_format as _detect

        try:
            detected = _detect(str(payload.get("content") or ""), payload.get("filename"))
        except _ConversatError as exc:
            raise bad_request(exc) from exc
        return {"format": detected}

    @app.post("/api/suites/import")
    def import_suite(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Convert a conversation export into suite YAML, ready to review.

        Accepts ``content`` plus an optional ``format`` (``null`` means detect),
        ``filename``, ``name``, ``connector`` and ``assertions``. Nothing is
        written to disk: the response carries the YAML so the editor can show it
        before the user saves.
        """
        import yaml

        from conversat.errors import ConversatError as _ConversatError
        from conversat.importer import import_conversation

        content = payload.get("content")
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(status_code=422, detail="pass the conversation as 'content'")

        tags = payload.get("tags") or ["imported"]
        if isinstance(tags, str):
            tags = [tag.strip() for tag in tags.split(",") if tag.strip()]

        try:
            result = import_conversation(
                content,
                fmt=payload.get("format"),
                filename=payload.get("filename"),
                name=payload.get("name") or None,
                connector=payload.get("connector"),
                assertions=payload.get("assertions") or "contains",
                tags=tags,
            )
        except _ConversatError as exc:
            raise bad_request(exc) from exc

        from conversat.engine.loader import suite_to_dict

        return {
            "format": result.format,
            "summary": result.summary(),
            "warnings": result.warnings,
            "conversations": [
                {
                    "name": item.name,
                    "messages": [
                        {"role": message.role, "text": message.text} for message in item.messages
                    ],
                }
                for item in result.conversations
            ],
            "suite": suite_to_dict(result.suite),
            "yaml": yaml.safe_dump(
                suite_to_dict(result.suite), sort_keys=False, allow_unicode=True, width=100
            ),
        }

    # -- crawls ------------------------------------------------------------ #
    @app.get("/api/crawl")
    def list_crawls() -> list[dict[str, Any]]:
        return crawls.list()

    @app.get("/api/crawl/{crawl_id}")
    def crawl_tree(crawl_id: str) -> dict[str, Any]:
        tree = crawls.tree(crawl_id)
        if tree is None:
            raise HTTPException(status_code=404, detail=f"unknown crawl {crawl_id!r}")
        return tree

    # -- discovery for the settings page ----------------------------------- #
    @app.get("/api/connectors")
    def connectors() -> list[dict[str, Any]]:
        from conversat.connectors.registry import BUILTINS, connector_defaults, describe_connector

        return [
            {
                "type": name,
                "description": describe_connector(name),
                "builtin": name in BUILTINS,
                "defaults": connector_defaults(name),
            }
            for name in sorted(BUILTINS)
        ]

    @app.get("/api/assertions")
    def assertions() -> list[dict[str, Any]]:
        from conversat.assertions.registry import available

        return [{"type": name} for name in available()]

    _mount_ui(app, static_dir)
    return app


def _mount_ui(app: Any, static_dir: str | Path | None) -> None:
    """Serve the built SvelteKit app, falling back to a pointer page.

    Registered last so it never shadows ``/api`` or ``/ws``. Unknown paths
    return ``index.html`` -- the SPA router resolves them client-side.
    """
    directory = _ui_dir(static_dir)
    if directory is None:

        @app.get("/", response_class=HTMLResponse)
        def placeholder() -> str:
            latest = _latest_summary(app.state.store)
            body = (
                "<p>The dashboard UI has not been built yet.</p>"
                "<p>Build it with <code>npm --prefix dashboard install &amp;&amp; "
                "npm --prefix dashboard run build</code>, or run "
                "<code>npm --prefix dashboard run dev</code> for hot reloading.</p>"
            )
            if latest:
                body += f"<p>{latest}</p>"
            return _PAGE.replace("__BODY__", body)

        return

    index = directory / "index.html"
    root = directory.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Any:
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)


def _ui_dir(static_dir: str | Path | None) -> Path | None:
    """Locate the built UI: explicit path, packaged copy, then repo checkout."""
    if static_dir is not None:
        candidate = Path(static_dir)
        return candidate if (candidate / "index.html").is_file() else None
    for candidate in (
        Path(__file__).resolve().parent / "dist",
        Path(__file__).resolve().parents[3] / "dashboard" / "dist",
    ):
        if (candidate / "index.html").is_file():
            return candidate
    return None
    candidate = Path(__file__).resolve().parents[3] / "dashboard" / "dist"
    return candidate if (candidate / "index.html").is_file() else None


def _latest_summary(store: RunStore) -> str | None:
    latest = store.latest()
    if latest is None:
        return None
    from html import escape

    return f"{escape(latest.suite)}: {escape(latest.summary_line())}"


def _version() -> str:
    from conversat import __version__

    return __version__


_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>conversat</title>
<style>
 body{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;margin:2rem;background:#0f1115;color:#e6e6e6}
 h1{color:#7dd3fc} table{border-collapse:collapse;margin-top:1rem}
 th,td{border:1px solid #2a2f3a;padding:.35rem .75rem;text-align:left}
 th{color:#a78bfa} code{background:#1b1f27;padding:.1rem .3rem;border-radius:3px}
</style></head>
<body>__BODY__<hr><p><small>conversat dashboard API &middot; see <code>/docs</code></small></p></body></html>
"""

__all__ = [
    "CrawlStore",
    "RunService",
    "RunStore",
    "SuiteLibrary",
    "create_app",
    "store_from_reports",
]
