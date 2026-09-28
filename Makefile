.PHONY: install test lint fmt sim publish clean

SCENARIO ?= S01
SEED ?=
SPEED ?= 60
ADDRESS ?= tcp://*:5556

install:            ## create .venv and install package + dev tools
	uv sync --all-extras

test:               ## deterministic test suite (no API key needed)
	uv run pytest -m "not live"

lint:               ## static checks
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy

fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests

sim:                ## generate runs/$(SCENARIO)/{stream,labels}.jsonl
	uv run shiftassist-sim run scenarios/$(SCENARIO)*.yaml --out runs/$(SCENARIO) $(if $(SEED),--seed $(SEED))

publish: sim        ## replay the scenario on ZMQ (SPEED x real time)
	uv run shiftassist-sim publish runs/$(SCENARIO)/stream.jsonl --address $(ADDRESS) --speed $(SPEED)

clean:
	rm -rf runs .pytest_cache .mypy_cache .ruff_cache
