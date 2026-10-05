# conversat examples

Everything here runs offline or against the bundled sample bot -- no API keys.

## 1. Offline examples (no server needed)

```bash
conversat run examples/suites/echo.yaml
conversat run examples/suites/scripted.yaml
conversat validate examples/suites/*.yaml
```

* `echo.yaml` — the in-process echo connector: templating, tags, assertion
  combinators, connector override per case.
* `scripted.yaml` — a scripted bot replaying fixed replies: useful as a CI
  smoke test of conversat itself.

## 2. Against the sample bot

`bot/app.py` is a ~200-line rule-based bot (greetings, arithmetic, memory,
refund/privacy policies, escalation) plus a tiny chat UI. It is deliberately
imperfect in places so that a suite can catch the difference.

```bash
python examples/bot/app.py --port 8099            # terminal 1
conversat run examples/suites/http.yaml           # terminal 2
conversat run examples/suites/websocket.yaml
conversat run examples/suites/http.yaml --tags policy -j 4
```

Add `--latency-ms 800` to the bot to make latency assertions interesting.

## 3. Browser (Playwright) example

```bash
playwright install chromium
python examples/bot/app.py --port 8099
conversat run examples/suites/web.yaml
```

The UI marks bot messages with `data-conversat-msg="bot"`, which is what
`message_selector` points at.

## 4. Crawling the sample bot

```bash
conversat crawl --suite examples/suites/http.yaml \
  --seed "Hello" --seed "What is your refund policy?" \
  --max-depth 2 --max-turns 20 --branching 2 \
  --output reports/crawled.yaml

conversat validate reports/crawled.yaml
conversat run reports/crawled.yaml
```

The generated suite contains the conversations the crawler actually observed,
with assertions derived from the real replies -- run it as a regression guard.

## 5. From scratch

```bash
conversat init --connector http --path my-suite.yaml
conversat run my-suite.yaml
```

## Files

| Path | What it is |
| --- | --- |
| `bot/app.py` | sample bot: HTTP `/chat`, WS `/ws/chat`, chat UI at `/` |
| `suites/http.yaml` | conversational smoke tests over HTTP |
| `suites/websocket.yaml` | the same over WebSocket |
| `suites/web.yaml` | end-to-end browser tests |
| `suites/echo.yaml` | offline echo connector examples |
| `suites/scripted.yaml` | offline scripted connector examples |
