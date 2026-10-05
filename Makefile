# conversat -- conversational testing platform
#
# Targets: install test lint run crawl report (plus a few conveniences).
# Override variables on the command line, e.g.
#   make run SUITE=examples/suites/smoke.yaml
#   make crawl SUITE=examples/suites/smoke.yaml OUT=reports/crawl.yaml

PYTHON        ?= python
VENV          ?= .venv
BIN           := $(VENV)/Scripts
SUITE         ?= examples/suites/smoke.yaml
OUT           ?= reports
FORMAT        ?= console
CONCURRENCY   ?= 4
MAX_DEPTH     ?= 2
MAX_TURNS     ?= 20
REPORT        ?= $(OUT)/run.json
HOST          ?= 127.0.0.1
PORT          ?= 8080

.DEFAULT_GOAL := help
.PHONY: help install install-dev test test-cov lint fmt fix typecheck run crawl report validate serve clean all

help: ## Show this help
	@echo "conversat make targets:"
	@echo "  install      create .venv and install conversat (editable) with dev extras"
	@echo "  test         run the self-test suite (pytest)"
	@echo "  lint         ruff check + format check + mypy"
	@echo "  run          run a test suite against the sample bot (SUITE=...)"
	@echo "  crawl        crawl a bot and write a generated suite (SUITE=...)"
	@echo "  report       re-render a stored run report (REPORT=...)"
	@echo "  validate     parse suites and validate them without running"
	@echo "  serve        start the dashboard API"
	@echo "  all          install + lint + test"

$(VENV):
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python.exe -m pip install --upgrade pip

install: $(VENV) ## Create the venv and install conversat with dev extras
	$(BIN)/python.exe -m pip install -e ".[dev]"
	$(BIN)/python.exe -m playwright install chromium || echo "playwright browser install skipped"

install-dev: install ## Alias for install

test: ## Run the self-test suite
	$(BIN)/python.exe -m pytest

test-cov: ## Run the self-test suite with a coverage report
	$(BIN)/python.exe -m pytest --cov=conversat --cov-report=term-missing --cov-report=html

lint: ## Lint, format-check and type-check
	$(BIN)/python.exe -m ruff check src tests examples
	$(BIN)/python.exe -m ruff format --check src tests examples
	$(BIN)/python.exe -m mypy

fmt: ## Auto-format code
	$(BIN)/python.exe -m ruff format src tests examples
	$(BIN)/python.exe -m ruff check --fix src tests examples

fix: fmt ## Alias for fmt

typecheck: ## Type-check only
	$(BIN)/python.exe -m mypy

run: ## Run a suite: make run SUITE=examples/suites/smoke.yaml
	$(BIN)/python.exe -m conversat run $(SUITE) --format $(FORMAT) --output-dir $(OUT) --concurrency $(CONCURRENCY)

crawl: ## Crawl a bot: make crawl SUITE=examples/suites/smoke.yaml
	$(BIN)/python.exe -m conversat crawl --suite $(SUITE) --max-depth $(MAX_DEPTH) --max-turns $(MAX_TURNS) --output $(OUT)/crawled-suite.yaml

report: ## Re-render a stored report: make report REPORT=reports/run.json
	$(BIN)/python.exe -m conversat report $(REPORT) --format markdown,junit,json --output-dir $(OUT)

validate: ## Validate suites without executing them
	$(BIN)/python.exe -m conversat validate $(SUITE)

serve: ## Start the dashboard API
	$(BIN)/python.exe -m conversat serve --host $(HOST) --port $(PORT)

all: install lint test ## Install, lint and test

clean: ## Remove caches and generated reports
	rm -rf build dist .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage $(OUT)
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
