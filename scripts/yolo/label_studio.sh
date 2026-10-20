#!/usr/bin/env bash
set -e

# Run Label Studio locally for labeling the YOLO frames from extract_frames.py.
#
# Usage: scripts/yolo/label_studio.sh
#   then open http://localhost:8080 (login and password are printed below)
#
# Label Studio lives in its own venv (yolo/.label_studio/venv) so its dependencies can't break
# the lerobot .venv; its database is in yolo/.label_studio/data. Install once with:
#   uv venv yolo/.label_studio/venv --python 3.12 && VIRTUAL_ENV=yolo/.label_studio/venv uv pip install label-studio
# On every start, label_studio_setup.py creates the "Cleany frames" project and imports
# yolo/frames/label_studio_tasks.json with the pre-labels if the project doesn't exist yet.
# Images are served from disk, so the frames must stay in yolo/frames/images.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

LS_DIR="$PROJECT_ROOT/yolo/.label_studio"
LS_VENV="$LS_DIR/venv"
PORT="${PORT:-8080}"

if [ ! -x "$LS_VENV/bin/label-studio" ]; then
    echo "Error: Label Studio is not installed in $LS_VENV (see the install command at the top of this script)"
    exit 1
fi

# Local-only account, created on the first start. Kept next to the database, out of git.
CREDENTIALS="$LS_DIR/credentials.env"
if [ ! -f "$CREDENTIALS" ]; then
    mkdir -p "$LS_DIR"
    cat > "$CREDENTIALS" <<EOF
LS_USERNAME=cleany@localhost.local
LS_PASSWORD=$(head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 12)
LS_TOKEN=$(head -c 20 /dev/urandom | od -An -tx1 | tr -d ' \n')
EOF
    chmod 600 "$CREDENTIALS"
fi
source "$CREDENTIALS"

export LABEL_STUDIO_BASE_DATA_DIR="$LS_DIR/data"
export LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true
export LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT="$PROJECT_ROOT"
# The setup script talks to the API with the plain token from credentials.env
export LABEL_STUDIO_ENABLE_LEGACY_API_TOKEN=true

echo "Label Studio: http://localhost:$PORT"
echo "  login:    $LS_USERNAME"
echo "  password: $LS_PASSWORD"

"$LS_VENV/bin/python" "$SCRIPT_DIR/label_studio_setup.py" \
    --url "http://localhost:$PORT" --token "$LS_TOKEN" --project-root "$PROJECT_ROOT" &

exec "$LS_VENV/bin/label-studio" start --no-browser --port "$PORT" \
    --username "$LS_USERNAME" --password "$LS_PASSWORD" --user-token "$LS_TOKEN"
