PYTHON ?= python

install:
	$(PYTHON) -m pip install -r requirements.txt

run:
	$(PYTHON) main.py

report:
	$(PYTHON) main.py --report-only

test:
	$(PYTHON) -m pytest -q

errors:
	$(PYTHON) -m src.errors

smoke:
	$(PYTHON) main.py --config config.smoke.yaml

.PHONY: install run report test errors smoke
