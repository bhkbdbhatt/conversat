# conversat

**Conversational testing platform.** Describe a chatbot conversation in YAML,
run it against the real bot, and assert on what comes back.

conversat is built for the thing ordinary HTTP test tools do badly: *multi-turn
dialogue*. It keeps conversation state per test case, renders variables into
messages, measures latency per turn, retries flakiness, and produces reports
your CI already understands (console, JSON, JUnit XML, Markdown).

```yaml
name: smoke
connector:
  type: http
  config:
    url: http://127.0.0.1:8099/chat
    json_body: { message: "{{text}}" }
    response_text_path: reply

cases:
  - name: remembers-my-name
    tags: [memory]
    setup:
      - send: My name is Ada
        expect: [{ not_empty: true }]
    steps:
      - send: What is my name?
        expect:
          - type: matches
            pattern: "(?i)\bada\b"
          - type: response_time_under
            value: 3000
```

```console
$ conversat run examples/suites/smoke.yaml
```

---

## Table of contents

- [Why](#why)
- [Install](#install)
- [Quick start](#quick-start)
- [Suite format](#suite-format)
  - [Connectors](#connectors)
  - [Turns](#turns)
  - [Assertions](#assertions)
  - [Variables and templating](#variables-and-templating)
  - [Retries, timeouts and tags](#retries-timeouts-and-tags)
- [CLI](#cli)
- [The crawler](#the-crawler)
- [Reports](#reports)
- [Dashboard API](#dashboard-api)
- [Architecture](#architecture)
- [Extending conversat](#extending-conversat)
- [Development](#development)
- [Project layout](#project-layout)
- [Roadmap](#roadmap)

---

## Why

Testing a chatbot with `curl` gets you one turn and no verdict. conversat
gives you:

| Problem | How conversat handles it |
| --- | --- |
| Conversations are stateful | one connector instance per test case, `setup` + `steps`, optional `clear_context` |
| Replies are unstructured text | 21 assertion strategies, from `contains` to `similar_to` and `json_path` |
| Bot answers move around | fuzzy matching, `contains_any`, `any_of`, latency budgets |
| Bots are slow and flaky | per-turn timeouts, retry policies with backoff, p95 in every report |
| Nobody knows what to test | the crawler explores a bot and generates test cases |
| CI needs standards | console / JSON / JSONL / JUnit XML / Markdown reports, exit codes 0/1/2/5 |
| Every bot is different | pluggable connectors: HTTP, WebSocket, Playwright, or your own |

## Install

Python 3.11 or newer.

```bash
git clone <your-fork> conversat && cd conversat
make install          # venv + editable install + dev extras + chromium
```

<details>
<summary>Manual install / other platforms</summary>

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium         # only needed for the `web` connector
```

</details>

`make` targets: `install`, `test`, `lint`, `run`, `crawl`, `report`
(plus `test-cov`, `fmt`, `typecheck`, `validate`, `serve`, `clean`, `all`).
On Windows without `make`, each target maps to a one-liner, e.g.
`make test` → `.venv\Scripts\python.exe -m pytest`.

## Quick start

```bash
make install

# 1. start the bundled sample bot (rule-based, no API keys)
.venv/bin/python examples/bot/app.py --port 8099

# 2. in another shell: validate, then run
conversat validate examples/suites/http.yaml
conversat run examples/suites/http.yaml
conversat run examples/suites/http.yaml --tags smoke --format markdown
```

No bot handy? Run the offline examples — they need no network at all:

```bash
conversat run examples/suites/echo.yaml
conversat run examples/suites/scripted.yaml
```

Or scaffold your own suite:

```bash
conversat init --connector http
conversat run conversat-suite.yaml
```

Programmatic use:

```python
import asyncio
from conversat import TestRunner, load_suite

report = asyncio.run(TestRunner(load_suite("examples/suites/http.yaml")).run())
print(report.summary_line())
assert report.ok
```

## Suite format

A suite file holds one (or several) suites. Top level keys: `name`,
`connector`, `cases`, plus optional `description`, `defaults`, `variables`
and `metadata`.

```yaml
name: my-suite
description: Conversational smoke tests

connector:
  type: http
  config: {}          # connector-specific settings

defaults:             # inherited by every case
  timeout: 20
  tags: [smoke]
  variables: { user: ada }

cases:
  - name: greeting
    tags: [chat]
    steps:
      - send: Hello!
        expect:
          - contains_any: [hello, hi, hey]
```

### Connectors

| `type` | Talks to | Needs |
| --- | --- | --- |
| `http` | JSON/text HTTP endpoints (incl. OpenAI-style APIs) | – |
| `websocket` | WebSocket servers | – |
| `web` | a chat UI in a real browser | `playwright install chromium` |
| `echo` | in-process echo bot (offline demos) | – |
| `scripted` | replays canned replies (CI smoke tests) | – |

**`http`**

```yaml
connector:
  type: http
  config:
    url: https://api.example.com/chat
    method: POST
    headers: { Authorization: "Bearer {{vars.token}}" }
    json_body: { message: "{{text}}", session: "{{vars.session}}" }
    response_text_path: data.reply      # where the text lives in the response
    fallback_keys: [reply, message]     # probed when the path is not set
    session_id_path: data.session_id    # echoed back on the next turn
    timeout: 20
    expect_status: [200, 201]
```

Send form or raw bodies with `data:` / `content:` instead of `json_body:`.

**`websocket`**

```yaml
connector:
  type: websocket
  config:
    url: ws://127.0.0.1:8099/ws/chat
    request_template: '{"type":"user","text":"{{text}}"}'
    response_text_path: reply
    response_timeout: 15
    handshake_paths: ["start"]          # sent right after connecting
```

**`web`**

```yaml
connector:
  type: web
  config:
    base_url: http://127.0.0.1:3000
    input_selector: "#chat-input"
    send_selector: "#send"              # omit to press Enter
    message_selector: "[data-conversat-msg], .bot-message"
    timeout: 20
    screenshot_dir: reports/screenshots # capture on failure
```

**`echo` / `scripted`** (offline)

```yaml
connector: { type: echo, config: { prefix: "echo: ", uppercase: false } }
connector: { type: scripted, config: { replies: ["hi there", "anything else?"] } }
```

### Turns

```yaml
- send: What is 2 + 2?        # user message (templated)
  expect: [...]               # assertions on the reply
  name: arithmetic            # label in reports
  timeout: 5                  # per-turn override (seconds)
  retry: { attempts: 3, delay: 0.5, backoff: exponential, retry_on: [error, timeout, failed_assertion] }
  clear_context: false        # restart the conversation before this turn
  metadata: { intent: math }  # free-form, ends up in reports
```

A turn may carry `payload:` instead of `send:` for connectors that need extra
fields. `setup:` turns run before `steps:` — that is how you set up
multi-turn context.

### Assertions

Write them as shorthand keys, or explicitly with `type:` when you need
`ignore_case` or extra fields.

| Strategy | Shorthand | Meaning |
| --- | --- | --- |
| `equals` / `iequals` | `- equals: "hi"` | exact reply (case-insensitive variant) |
| `contains` / `not_contains` | `- contains: hello` | substring presence |
| `contains_any` / `contains_all` | `- contains_any: [a, b]` | one of / every alternative |
| `starts_with` / `ends_with` | `- starts_with: Sure` | prefix / suffix |
| `matches` | `- regex: "^order #\\d+"` | regular expression (`re.search`) |
| `min_length` / `max_length` | `- min_length: 10` | reply size bounds |
| `not_empty` / `is_empty` | `- not_empty: true` | emptiness |
| `one_of` / `none_of` | `- one_of: [yes, no]` | exact-match allow/deny lists |
| `similar_to` | `- similar_to: {value: hi, threshold: 0.8}` | fuzzy text similarity |
| `json_path` | `- json_path: {path: data.id, op: exists}` | structure of the raw payload |
| `response_time_under` | `- latency_under: 2000` | latency budget (ms) |
| `no_error` | `- no_error: true` | transport/connector error |
| `any_of` / `all_of` / `not` | `- any_of: [...]` | combinators |

`json_path` supports `data.reply`, `items[0].id`, `$.a.b`, and ops
`exists, missing, eq, ne, contains, gt, gte, lt, lte, in, not_in, len_eq,
len_gt, len_lt, is_true, is_false`.

```yaml
expect:
  - not_empty: true
  - contains_any: ["refund", "return policy"]
  - not_contains: "I am not allowed"
  - json_path: { path: meta.model, op: exists }
  - latency_under: 4000
  - any_of:
      - contains: "agent"
      - contains: "human"
```

### Variables and templating

`{{name}}` / `{{a.b}}` placeholders are resolved in `send`, headers, params and
request bodies. Unknown placeholders are left untouched, so literal `{{ }}` in
bot responses is never mangled.

```yaml
defaults:
  variables:
    user: ada
cases:
  - name: greeting
    variables:
      locale: de
    steps:
      - send: "Hallo {{vars.user}} ({{vars.locale}})"
```

Values come from, in order of precedence: case `variables` → suite
`defaults.variables` → `--var key=value` on the CLI → `CONVERSAT_*` env vars.
`--var` values are JSON-decoded, so `--var retries=3` arrives as a number.
Secrets are redacted before they reach a report.

### Retries, timeouts and tags

```yaml
defaults:
  timeout: 20
  retry: { attempts: 2, backoff: fixed, delay: 0.5 }
```

Select cases at run time:

```bash
conversat run suite.yaml --tags smoke,chat --exclude-tags flaky -j 8 --fail-fast
conversat run suite.yaml --case greeting --name-pattern '^order'
```

`--fail-fast` stops scheduling new cases after the first failure; a turn only
retries when its status is listed in `retry_on`.

## CLI

```console
conversat --help
```

| Command | What it does |
| --- | --- |
| `run` | execute suites, write reports, exit 0/1/2/5 |
| `validate` | parse suites, check connectors/assertions, catch typos |
| `crawl` | explore a bot, print findings, emit a generated suite |
| `report` | re-render a stored JSON report (junit, markdown, ...) |
| `summary` | one-line summary of a stored report |
| `init` | scaffold a starter suite |
| `connectors` | list connectors with a usage example |
| `assertions` | list assertion strategies |
| `serve` | run the dashboard API over stored reports |

Useful `run` flags: `-t/--tags`, `-c/--case`, `-j/--concurrency`,
`--fail-fast`, `--timeout`, `--var k=v`, `--connector http:url=...`,
`--format console,json,junit,markdown`, `-o/--output-dir`, `--no-write`,
`--dry-run`, `--label`, `--env-file`, `-q/--quiet`, `-v/--verbose`.

## The crawler

The crawler explores a bot breadth-first inside a hard budget, then tells you
what it found and writes you a test suite.

```bash
conversat crawl --suite examples/suites/http.yaml \
  --seed "Hello" --max-depth 2 --max-turns 25 --branching 2 \
  --output reports/crawled.yaml
```

* **Dedupes** messages so it never asks the same thing twice per branch.
* **Mines** the bot's own replies for questions, then falls back to curated
  probes (`What are the available options?`, `Can you give me an example?`, ...).
  Swap in an LLM generator by subclassing `FollowUpGenerator`.
* **Flags** empty replies, error-looking answers, slow replies (>4s) and
  responses repeated 3+ times.
* **Generates cases** with assertions derived from what the bot actually said
  (`not_empty`, `contains_any` over the real words, a latency budget with 50%
  headroom), so the generated suite passes today and guards behaviour tomorrow.
* Each branch gets its **own** connector, so the tree stays correct even for
  stateful bots.

## Reports

```bash
conversat run suite.yaml --format console,json,junit,markdown -o reports/
```

| Format | Use |
| --- | --- |
| `console` | rich panels, per-turn replies, latency, failing assertions |
| `json` | full report object for tooling / the dashboard |
| `jsonl` | one line per turn for streaming into a data store |
| `junit` | JUnit XML for Jenkins / GitLab / Azure |
| `markdown` | PR comment or CI job summary, with transcripts |

Exit codes: `0` green · `1` failed assertions · `2` connector/runtime errors ·
`5` no cases matched the filters.

Every report carries the environment (Python, platform, cwd), p50/p95 latency,
per-turn assertions and the full transcript, with secrets redacted.

## Dashboard API

```bash
conversat serve --reports reports --port 8080
```

`GET /api/health` · `/api/runs` · `/api/runs/{id}` · `/api/runs/{id}/turns` ·
`/api/cases` · `/api/stats`, plus a minimal HTML page at `/` and OpenAPI docs
at `/docs`. Reads `*.json` from the reports directory on startup and keeps the
last 50 runs in memory.

## Architecture

```
YAML ──▶ loader ──▶ TestSuite (pydantic)      ──▶ crawler ──▶ CrawlReport
                          │                                    │
                          ▼                                    ▼
                    TestRunner                          reporting/formatters
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
   connectors        assertions          connectors
  (http/ws/web)    (registry +        (one instance
                    strategies)        per case)
```

Design decisions worth knowing:

* **Models are pure data.** Everything under `conversat/models/` validates and
  serialises; behaviour lives in `engine`, `assertions` and `connectors`. That
  is why a custom assertion never requires touching the models.
* **Assertions dispatch on `type`.** `models/assertion.py` holds the specs,
  `assertions/strategies.py` holds the handlers, `assertions/registry.py` maps
  them. Adding a strategy is one `@register("name")` function.
* **Connectors are lazily imported.** `playwright` and `websockets` are only
  imported when a suite actually uses them, so `conversat run` on an offline
  `echo` suite stays fast.
* **One connector per case.** No state bleeds between cases; `reset()`
  re-opens the conversation when a case needs it mid-flight.

## Extending conversat

Custom assertion:

```python
from conversat.assertions import AssertionResult, register

@register("has_emoji")
def has_emoji(spec, ctx):
    return AssertionResult(passed="🙂" in ctx.text, message="reply has an emoji")
```

Register the connector in `conversat.connectors`:

```python
from conversat.connectors import Connector, register
from conversat.models.response import BotResponse

class MyBot(Connector):
    type_name = "my-bot"

    async def connect(self) -> None: ...
    async def send(self, text: str, *, timeout: float | None = None) -> BotResponse:
        return BotResponse(text=await my_client.ask(text))
    async def close(self) -> None: ...

register("my-bot", lambda cfg: MyBot(cfg))
```

Then use `type: my-bot` in any suite. Same pattern for report formats
(`@register("html")` on a `Formatter` subclass).

## Development

```bash
make test        # pytest
make test-cov    # pytest + coverage (htmlcov/)
make lint        # ruff check + ruff format --check + mypy
make fmt         # auto-format and autofix
make all         # install + lint + test
```

The self-test suite in `tests/` covers the models, loader, every assertion
strategy, the runner (retries, timeouts, parallelism, filters), all four
connectors (httpx mock transport, a real local WS server, a fake browser page),
the crawler, all formatters and the CLI end to end. Browser tests are skipped
automatically when no Chromium build is present.

## Project layout

```
conversat/
├── pyproject.toml          # metadata, deps, ruff/mypy/pytest config
├── Makefile                # install test lint run crawl report
├── src/conversat/
│   ├── models/             # pydantic models (suite, assertion, report, crawler)
│   ├── engine/             # connector contract, YAML loader, test runner
│   ├── connectors/         # http, websocket, web (Playwright), echo, scripted
│   ├── crawler/            # conversation crawler + test-case generation
│   ├── assertions/         # strategy registry + built-in strategies
│   ├── reporting/          # console, json, jsonl, junit, markdown
│   ├── cli/                # typer commands
│   └── dashboard/          # FastAPI run store + API (phase 7)
├── tests/                  # conversat's own test suite
└── examples/               # sample bot + example suites
```

## Roadmap

1. ~~Core engine, connectors, assertions, reporting~~ — done
2. ~~Conversation crawler~~ — done
3. ~~CI-grade reports (JUnit/Markdown)~~ — done
4. ~~Dashboard API~~ — done (API; UI next)
5. **Next.js dashboard** consuming the API: run history, transcript diffing,
   assertion timelines
6. **LLM-assisted assertions**: judge-based grading for open-ended replies,
   pluggable via the same `register` hook as strategies
7. **Playwright codegen**: record a browser conversation and emit a suite
8. **Baseline diffing**: compare two runs and report behavioural regressions
   (reply drift, new empty replies, latency regressions)

## License

MIT
