.PHONY: install test test-e2e analyze generate bulk clean help

VENV = .venv
PYTHON = $(VENV)/bin/python
RSV = $(VENV)/bin/rsv
OP_ENV = op run --env-file=.env --

install: $(VENV)
	$(VENV)/bin/pip install -e ".[dev]"

$(VENV):
	python3 -m venv $(VENV)

test:
	$(VENV)/bin/python -m pytest tests/test_analyzer.py -v

test-e2e:
	$(OP_ENV) $(VENV)/bin/python -m pytest tests/test_e2e.py -v -s

analyze:
	$(PYTHON) -m src.cli analyze $(FILE)

generate:
	$(OP_ENV) $(RSV) generate $(FILE) -s $(or $(STYLE),abstract) -q $(or $(QUALITY),high)

bulk:
	$(OP_ENV) $(RSV) bulk $(DIR) -s $(or $(STYLE),abstract)

styles:
	$(RSV) styles

test-tracks:
	$(PYTHON) scripts/generate_test_tracks.py

clean:
	rm -rf output/ .cache/ __pycache__ .pytest_cache
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

help:
	@echo "Usage:"
	@echo "  make install              Install dependencies"
	@echo "  make test                 Run unit tests"
	@echo "  make test-e2e             Run e2e test (needs API key)"
	@echo "  make analyze FILE=x.flac  Analyze a track"
	@echo "  make generate FILE=x.flac Generate visuals"
	@echo "  make bulk DIR=./music     Bulk process directory"
	@echo "  make styles               List visual styles"
	@echo "  make test-tracks          Generate synthetic test audio"
	@echo "  make clean                Clean output/cache"
