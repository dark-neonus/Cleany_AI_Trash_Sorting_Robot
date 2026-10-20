"""Create the Label Studio project for the YOLO frames and import them (once).

Started in the background by label_studio.sh: waits for the server, then, if the project
doesn't exist yet, creates it with the label config from extract_frames.py, connects the
frames folder as local storage (Label Studio only serves local files under a storage) and
imports label_studio_tasks.json with the pre-labels as predictions.

Usage:
    python label_studio_setup.py --url http://localhost:8080 --token <token> --project-root <repo>
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

PROJECT_TITLE = "Cleany frames"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--frames", default="yolo/frames")
    args = parser.parse_args()

    frames = Path(args.project_root) / args.frames
    api = requests.Session()
    api.headers["Authorization"] = f"Token {args.token}"

    # Wait up to 3 min: the first start runs database migrations
    for _ in range(180):
        try:
            if api.get(f"{args.url}/api/projects", timeout=5).status_code == 200:
                break
        except requests.ConnectionError:
            pass
        time.sleep(1)
    else:
        sys.exit("label_studio_setup: server did not answer, project not created")

    projects = api.get(f"{args.url}/api/projects", params={"title": PROJECT_TITLE}).json()["results"]
    if any(p["title"] == PROJECT_TITLE for p in projects):
        return

    tasks_file = frames / "label_studio_tasks.json"
    if not tasks_file.exists():
        sys.exit(f"label_studio_setup: {tasks_file} not found, run extract_frames.py first")

    project = api.post(f"{args.url}/api/projects", json={
        "title": PROJECT_TITLE,
        "label_config": (frames / "label_studio_config.xml").read_text(),
        "show_collab_predictions": True,  # show the pre-labels as an editable starting point
    })
    project.raise_for_status()
    project_id = project.json()["id"]

    api.post(f"{args.url}/api/storages/localfiles", json={
        "project": project_id,
        "title": "frames",
        "path": str(frames / "images"),
        "use_blob_urls": False,  # only grants access; the tasks come from the JSON import
    }).raise_for_status()

    tasks = json.loads(tasks_file.read_text())
    api.post(f"{args.url}/api/projects/{project_id}/import", json=tasks).raise_for_status()
    # Pre-label new annotations from the imported predictions. Label Studio only accepts a
    # model_version that already has predictions, so this goes after the import.
    model_version = next((t["predictions"][0]["model_version"] for t in tasks if t.get("predictions")), None)
    if model_version:
        api.patch(f"{args.url}/api/projects/{project_id}", json={"model_version": model_version}).raise_for_status()
    print(f"label_studio_setup: project '{PROJECT_TITLE}' created with {len(tasks)} frames")


if __name__ == "__main__":
    main()
