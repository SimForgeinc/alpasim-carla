# Counts in commit messages must be produced, not typed.
#
#   make test        the simulator-free suite
#   make count       just the one line, for pasting into a message
#   make carla       the acceptance suite; needs a live server
#   make protos      regenerate the vendored stubs

PYTHON ?= python

.PHONY: test count carla carla-mutating protos clean

test:
	$(PYTHON) -m pytest tests -m "not carla" -q

count:
	@$(PYTHON) -m pytest tests -m "not carla" -q 2>&1 | tail -1

carla:
	$(PYTHON) -m pytest tests -m carla -q

carla-mutating:
	$(PYTHON) -m pytest tests -m carla --run-mutating -q

protos:
	bash tools/gen_protos.sh

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
