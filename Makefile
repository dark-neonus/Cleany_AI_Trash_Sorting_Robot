# Two targets, as in the course template: "get me set up" and "prove it works". Everything
# else (recording, training, running the arm) is a script in scripts/, see README.md.

BIN := .venv/bin

.PHONY: setup reproduce

setup: ## System packages, .venv with LeRobot + YOLO, dev tools (tests, lint) and the pre-commit hook
	bash scripts/setup/install_dependencies.sh
	VIRTUAL_ENV=.venv uv pip install -r requirements-dev.txt
	$(BIN)/pre-commit install

reproduce: ## Download the labelled frames and the models, print the YOLO numbers of README.md's results table
	$(BIN)/hf download cleany-ai/cleany_yolo_frames --repo-type dataset --local-dir yolo/hub_frames
	YOLO_AUTOINSTALL=false $(BIN)/python scripts/yolo/evaluate.py --frames yolo/hub_frames
