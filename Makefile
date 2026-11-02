PY ?= python3

.PHONY: run test test-ui lint screenshots install uninstall

run:
	./run.sh

test:
	$(PY) -m unittest discover -s tests -t . -p 'test_[!u]*.py'

test-ui:
	GSK_RENDERER=cairo xvfb-run -a $(PY) -m unittest tests.test_ui_smoke -v

lint:
	ruff check .

screenshots:
	./scripts/screenshots.sh

install:
	./install.sh

uninstall:
	./uninstall.sh
