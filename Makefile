# One target: "get me set up". Everything else (recording, training, running the arm) is a
# script in scripts/, see README.md.

BIN := .venv/bin

.PHONY: setup

setup: ## System packages, .venv with LeRobot + YOLO, dev tools (tests, lint) and the pre-commit hook
	bash scripts/setup/install_dependencies.sh
	VIRTUAL_ENV=.venv uv pip install -r requirements-dev.txt
	$(BIN)/pre-commit install
