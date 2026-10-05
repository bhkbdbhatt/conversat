"""Dashboard API + stores.

The dashboard is the only consumer of the JSON reports on disk, so most of these
tests are really about the disk -> model -> JSON contract staying intact.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from conversat.dashboard.app import create_app
from conversat.dashboard.store import CrawlStore, RunStore, read_crawl_report, read_run_report

ECHO_SUITE = "examples/suites/echo.yaml"


@pytest.fixture
def reports_dir(tmp_path: Path) -> Path:
    target = tmp_path / "reports"
    target.mkdir()
    return target


@pytest.fixture
def client(reports_dir: Path, tmp_path: Path):
    from fastapi.testclient import TestClient

    # A copy of the examples, so suite CRUD tests never touch the repository.
    suite_dir = tmp_path / "suites"
    shutil.copytree("examples/suites", suite_dir)
    app = create_app(reports_dir, suites=suite_dir)
    with TestClient(app) as test_client:
        test_client.suite_dir = suite_dir  # type: ignore[attr-defined]
        yield test_client


def run_echo(client, **options) -> dict:
    """Queue a run and wait for it to land in the store."""
    response = client.post("/api/runs", json={"suites": [ECHO_SUITE], "options": options})
    assert response.status_code == 202, response.text
    started = response.json()["started"]
    assert started
    run_id = started[0]["run_id"]

    for _ in range(200):
        detail = client.get(f"/api/runs/{run_id}")
        if detail.status_code == 200:
            return detail.json()
        asyncio.sleep(0)  # let the background task progress on the server loop
        import time

        time.sleep(0.02)
    raise AssertionError(f"run {run_id} never finished")


# -- stores -------------------------------------------------------------- #
def test_run_store_round_trips_reports_on_disk(reports_dir: Path) -> None:
    from conversat.engine import TestRunner, load_suite
    from conversat.reporting.writer import save_report

    report = asyncio.run(TestRunner(load_suite(ECHO_SUITE)).run())
    save_report(report, reports_dir / "run.json", formatter="json")

    store = RunStore(reports_dir)
    assert store.load_disk() == 1
    assert store.latest() is not None
    assert store.latest().run_id == report.run_id
    assert [row["run_id"] for row in store.list()] == [report.run_id]


def test_crawl_store_reads_crawl_reports(reports_dir: Path) -> None:
    from conversat.crawler.crawler import crawl
    from conversat.models.crawler import CrawlConfig
    from conversat.models.suite import ConnectorConfig

    report = asyncio.run(
        crawl(
            CrawlConfig(seeds=["hello"], max_depth=1, max_turns=2, branching=1),
            ConnectorConfig(type="echo", config={"prefix": "> "}),
        )
    )
    path = reports_dir / "crawl-demo.json"
    path.write_text(report.model_dump_json(), encoding="utf-8")

    store = CrawlStore(reports_dir)
    assert store.load_disk() == 1
    tree = store.tree("crawl-demo")
    assert tree is not None
    assert tree["nodes"]
    assert set(tree["roots"]).issubset(tree["nodes"])
    # every child is reachable from a root
    for node in tree["nodes"].values():
        for child in node["children"]:
            assert tree["nodes"][child]["parent"] == node["id"]


def test_readers_reject_foreign_json(tmp_path: Path) -> None:
    path = tmp_path / "other.json"
    path.write_text('{"hello": "world"}', encoding="utf-8")
    assert read_run_report(path) is None
    assert read_crawl_report(path) is None


def test_case_history_tracks_one_case_over_runs(reports_dir: Path) -> None:
    from conversat.engine import TestRunner, load_suite
    from conversat.reporting.writer import save_report

    store = RunStore(reports_dir)
    for index in range(3):
        report = asyncio.run(TestRunner(load_suite(ECHO_SUITE)).run())
        report.run_id = f"run-{index}"
        store.add(report)
        save_report(report, reports_dir / f"run-{index}.json", formatter="json")

    name = store.latest().cases[0].name  # type: ignore[union-attr]
    history = store.case_history(name)
    assert [row["run_id"] for row in history] == ["run-0", "run-1", "run-2"]
    assert history[0]["turn_rows"]


# -- read-only endpoints -------------------------------------------------- #
def test_health(client) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["runs"] == 0
    assert body["suites"] > 0


def test_stats_and_trends_start_empty(client) -> None:
    assert client.get("/api/stats").json()["runs"] == 0
    assert client.get("/api/trends").json() == []


def test_unknown_run_is_404(client) -> None:
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/nope/turns").status_code == 404
    assert client.get("/api/runs/nope/cases").status_code == 404


def test_root_serves_a_page_without_a_built_ui(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "conversat" in response.text


def test_cors_allows_the_dev_server(client) -> None:
    response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_connector_and_assertion_catalogue(client) -> None:
    types = [row["type"] for row in client.get("/api/connectors").json()]
    assert {"http", "websocket", "web", "echo", "scripted"} <= set(types)
    strategies = {row["type"] for row in client.get("/api/assertions").json()}
    assert {"contains", "not_contains", "matches"} <= strategies


# -- triggering runs ------------------------------------------------------ #
def test_post_run_executes_a_suite(client) -> None:
    run = run_echo(client)
    assert run["suite"] == "echo-offline"
    assert run["totals"]["cases"] == 5
    assert run["totals"]["assertions"] > 0

    summary = client.get("/api/runs").json()
    assert len(summary) == 1
    assert summary[0]["status"] == "passed"

    turns = client.get(f"/api/runs/{run['run_id']}/turns").json()
    assert turns and all("reply" in row for row in turns)

    cases = client.get(f"/api/runs/{run['run_id']}/cases").json()
    assert len(cases) == 5
    assert cases[0]["transcript"]

    history = client.get("/api/cases/history", params={"name": cases[0]["name"]}).json()
    assert len(history) == 1


def test_post_run_writes_a_report_file(client, reports_dir: Path) -> None:
    run = run_echo(client)
    files = list(reports_dir.glob("*.json"))
    assert files
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["run_id"] == run["run_id"]


def test_post_run_with_a_case_filter(client) -> None:
    run = run_echo(client, cases=["templating"])
    assert run["totals"]["cases"] == 1
    assert run["cases"][0]["name"] == "templating"


def test_post_run_with_a_tag_filter(client) -> None:
    run = run_echo(client, tags=["offline"])
    assert run["totals"]["cases"] == 5
    assert run_echo(client, tags=["no-such-tag"])["totals"]["cases"] == 0


def test_post_run_rejects_a_missing_suite(client) -> None:
    response = client.post("/api/runs", json={"suites": ["does-not-exist.yaml"]})
    assert response.status_code == 400
    assert "does-not-exist" in response.json()["detail"]


def test_post_run_requires_a_suite(client) -> None:
    assert client.post("/api/runs", json={}).status_code == 422


def test_dry_run_selects_without_sending(client) -> None:
    run = run_echo(client, dry_run=True)
    assert run["totals"]["cases"] == 5
    assert all(case["status"] == "skipped" for case in run["cases"])


# -- suite library -------------------------------------------------------- #
def test_list_suites(client) -> None:
    body = client.get("/api/suites").json()
    names = [row["name"] for row in body["suites"]]
    assert "echo-offline" in names
    assert all(row["error"] is None for row in body["suites"])


def test_get_suite_returns_yaml(client) -> None:
    body = client.get("/api/suites/echo-offline").json()
    assert body["name"] == "echo-offline"
    assert body["cases"]
    assert "name: echo-offline" in body["yaml"]


def test_unknown_suite_is_404(client) -> None:
    assert client.get("/api/suites/nope").status_code == 404


def test_create_update_and_delete_a_suite(client) -> None:
    created = client.post(
        "/api/suites",
        json={
            "name": "from-the-ui",
            "connector": {"type": "echo", "config": {"prefix": ">> "}},
            "cases": [
                {"name": "greets", "steps": [{"send": "hi", "expect": [{"contains": "hi"}]}]}
            ],
        },
    )
    assert created.status_code == 201, created.text
    path = client.suite_dir / created.json()["path"]
    assert path.is_file()

    updated = client.put(
        "/api/suites/from-the-ui",
        json={
            "name": "from-the-ui",
            "connector": {"type": "echo", "config": {"prefix": "### "}},
            "cases": [
                {"name": "greets", "steps": [{"send": "hi"}]},
                {"name": "second", "steps": [{"send": "yo"}]},
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    assert len(updated.json()["cases"]) == 2

    # the file really changed on disk
    disk = client.get("/api/suites/from-the-ui").json()
    assert disk["connector"]["config"]["prefix"] == "### "
    assert len(disk["cases"]) == 2

    assert client.delete("/api/suites/from-the-ui").status_code == 204
    assert client.get("/api/suites/from-the-ui").status_code == 404
    assert client.delete("/api/suites/from-the-ui").status_code == 404


def test_a_suite_written_by_the_api_is_runnable(client) -> None:
    """The YAML the editor saves must load straight back into the engine."""
    from conversat.engine.loader import load_suite

    created = client.post(
        "/api/suites",
        json={
            "name": "round-trips",
            "connector": {"type": "echo", "config": {"prefix": "echo: "}},
            "cases": [
                {
                    "name": "keeps-assertions",
                    "steps": [
                        {
                            "send": "hi",
                            "expect": [
                                {"contains_any": ["hi", "hello"]},
                                {"matches": "h."},
                                {"response_time_under": 2000},
                                {"any_of": [{"contains": "hi"}, {"is_empty": True}]},
                            ],
                        }
                    ],
                }
            ],
        },
    )
    assert created.status_code == 201, created.text

    suite = load_suite(client.suite_dir / created.json()["path"])
    turn = suite.cases[0].steps[0]
    kinds = [type(spec).__name__ for spec in turn.expect]
    assert kinds == [
        "ContainsAnyAssertion",
        "MatchesAssertion",
        "ResponseTimeUnderAssertion",
        "AnyOfAssertion",
    ]
    assert turn.expect[0].values == ["hi", "hello"]
    assert turn.expect[1].pattern == "h."


def test_create_suite_rejects_an_invalid_payload(client) -> None:
    response = client.post(
        "/api/suites",
        json={"name": "broken", "connector": {"type": "echo"}, "cases": "not-a-list"},
    )
    assert response.status_code == 400
    assert "cases" in response.json()["detail"]


def test_validate_suite_reports_errors(client) -> None:
    bad = client.post(
        "/api/suites/validate", json={"name": "x", "connector": {"type": "echo"}, "cases": []}
    ).json()
    assert bad["valid"] is False
    assert bad["errors"]

    good = client.post(
        "/api/suites/validate",
        json={
            "name": "x",
            "connector": {"type": "echo"},
            "cases": [{"name": "a", "steps": [{"send": "hi"}]}],
        },
    ).json()
    assert good["valid"] is True
    assert good["cases"] == ["a"]


YAML_SUITE = """
name: typed-in-the-browser
connector:
  type: echo
  config:
    prefix: '>> '
cases:
  - name: greets
    steps:
      - send: hi
        expect:
          - contains_any: [hi, hello]
"""


def test_validate_accepts_raw_yaml(client) -> None:
    """The editor posts YAML text so the browser needs no YAML parser."""
    result = client.post("/api/suites/validate", json={"yaml": YAML_SUITE}).json()
    assert result["valid"] is True, result
    assert result["cases"] == ["greets"]
    assert result["connector"] == "echo"


def test_validate_reports_yaml_syntax_errors(client) -> None:
    result = client.post("/api/suites/validate", json={"yaml": "name: [oops\ncases: *"}).json()
    assert result["valid"] is False
    assert result["errors"]


def test_create_a_suite_from_raw_yaml(client) -> None:
    created = client.post("/api/suites", json={"yaml": YAML_SUITE})
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "typed-in-the-browser"

    from conversat.engine.loader import load_suite

    suite = load_suite(client.suite_dir / created.json()["path"])
    assert suite.connector.config["prefix"] == ">> "
    assert suite.cases[0].steps[0].expect[0].values == ["hi", "hello"]


def test_run_a_suite_created_through_the_api(client) -> None:
    path = client.post(
        "/api/suites",
        json={
            "name": "ui-made-suite",
            "connector": {"type": "echo", "config": {"prefix": "echo: "}},
            "cases": [{"name": "greets", "steps": [{"send": "hi", "expect": [{"not_empty": True}]}]}],
        },
    ).json()["path"]
    run = run_echo(client)
    assert run["totals"]["cases_passed"] == 5
    assert path.endswith(".yaml")


# -- crawls --------------------------------------------------------------- #
def test_crawl_endpoints_are_empty_without_crawls(client) -> None:
    assert client.get("/api/crawl").json() == []
    assert client.get("/api/crawl/nope").status_code == 404


# -- conversation import -------------------------------------------------- #
def test_list_importers(client) -> None:
    names = {row["name"] for row in client.get("/api/importers").json()}
    assert {"json", "jsonl", "csv", "tsv", "xml", "markdown", "text", "html", "yaml"} <= names
    for row in client.get("/api/importers").json():
        assert row["description"] and row["example"]


@pytest.mark.parametrize(
    "content,filename,expected",
    [
        ('[{"role":"user","content":"hi"}]', "chat.json", "json"),
        ("role,text\nuser,hi\n", "tickets.csv", "csv"),
        ("# Title\n\n**User:** hi\n", "log.md", "markdown"),
        ("User: hi\nBot: hello there\n", "log.txt", "text"),
        ("<chat><user>hi</user></chat>", "dump.xml", "xml"),
    ],
)
def test_detect_import(client, content: str, filename: str, expected: str) -> None:
    response = client.post("/api/importers/detect", json={"content": content, "filename": filename})
    assert response.status_code == 200
    assert response.json()["format"] == expected


def test_detect_rejects_nonsense(client) -> None:
    response = client.post("/api/importers/detect", json={"content": "no structure at all"})
    assert response.status_code == 400
    assert "could not detect" in response.json()["detail"]


def test_import_returns_reviewable_yaml(client) -> None:
    export = json.dumps(
        [
            {"role": "user", "content": "Hi there"},
            {"role": "assistant", "content": "Hello! How can I help you today?"},
        ]
    )
    body = client.post("/api/suites/import", json={"content": export, "filename": "chat.json"}).json()

    assert body["format"] == "json"
    assert body["summary"]["cases"] == 1
    assert body["summary"]["turns"] == 1
    # Roles are normalised to user/bot regardless of the source vocabulary.
    assert body["conversations"][0]["messages"] == [
        {"role": "user", "text": "Hi there"},
        {"role": "bot", "text": "Hello! How can I help you today?"},
    ]
    assert "name:" in body["yaml"]
    assert body["suite"]["connector"]["type"] == "scripted"
    # Nothing is written until the user saves.
    assert not list(client.suite_dir.glob("from-the-ui*"))


def test_imported_yaml_can_be_saved_and_run(client) -> None:
    export = "User: Hello there\nBot: Hi friend, how can I help?\n"
    body = client.post("/api/suites/import", json={"content": export, "filename": "log.txt"}).json()

    saved = client.post("/api/suites", json={"yaml": body["yaml"]})
    assert saved.status_code == 201, saved.text
    name = saved.json()["name"]

    run = run_echo(client)
    assert run["totals"]["cases_passed"] == 5
    assert name in {row["name"] for row in client.get("/api/suites").json()["suites"]}


def test_import_requires_content(client) -> None:
    assert client.post("/api/suites/import", json={}).status_code == 422
    assert client.post("/api/suites/import", json={"content": "  "}).status_code == 422


def test_import_rejects_an_unknown_format(client) -> None:
    response = client.post(
        "/api/suites/import", json={"content": "hi", "format": "parquet"}
    )
    assert response.status_code == 400
    assert "unknown format" in response.json()["detail"]


def test_import_reports_unparseable_content(client) -> None:
    response = client.post("/api/suites/import", json={"content": "just some prose"})
    assert response.status_code == 400
    assert "detail" in response.json()


def test_import_accepts_an_explicit_format(client) -> None:
    body = client.post(
        "/api/suites/import", json={"content": "User: hi\nBot: hello there", "format": "text"}
    ).json()
    assert body["format"] == "text"


def test_import_can_target_a_live_connector(client) -> None:
    body = client.post(
        "/api/suites/import",
        json={
            "content": "User: hi\nBot: hello there",
            "format": "text",
            "connector": "http:url=http://127.0.0.1:8099/chat",
            "assertions": "exact",
            "name": "live-import",
            "tags": "chat, regression",
        },
    ).json()
    assert body["suite"]["connector"]["type"] == "http"
    # No per-case replay script when a live connector is requested.
    assert body["suite"]["cases"][0].get("connector") is None
    # `steps` is dumped under its alias, `turns`.
    assert body["suite"]["cases"][0]["turns"][0]["expect"][0]["type"] == "equals"