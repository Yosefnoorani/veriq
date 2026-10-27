VENV ?= .venv
PY := $(VENV)/bin/python

.PHONY: install demo test clean

install:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -e '.[dev]'

demo:
	VERIQ=$(VENV)/bin/veriq ./scripts/demo.sh

test:
	$(PY) -m pytest -q

clean:
	rm -rf reports .pytest_cache build *.egg-info src/*.egg-info
