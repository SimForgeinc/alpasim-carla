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

hooks:
	@install -m 0755 tools/hooks/pre-commit "$$(git rev-parse --git-common-dir)/hooks/pre-commit"
	@install -m 0755 tools/hooks/prepare-commit-msg "$$(git rev-parse --git-common-dir)/hooks/prepare-commit-msg"
	@echo "installed pre-commit       - runs 'make test', refuses on failure"
	@echo "installed prepare-commit-msg - appends the verified count to the message"
