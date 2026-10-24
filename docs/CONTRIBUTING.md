# Contributing

How we work on this repo, so that everyone's work is visible in the commit history.

## Branches

- `main` is always in a working state: anyone can clone it and run `make reproduce`.
- Larger work goes on a branch: `feat/<short-name>` for new functionality, `fix/<short-name>`
  for bug fixes, `exp/<short-name>` for experiments that might not pan out, merged through a
  pull request.
- Small changes (a doc fix, a parameter) may go straight to `main`, but always
  `git pull` first: two people work on this repo in parallel.

## Pull requests

A pull request gets a review from the other teammate before merging. Review is how the rest
of the team learns what was built, in enough detail to debug it later.

## Commits — Conventional Commits

Prefixes: `feat:`, `fix:`, `docs:`, `exp:`, `refactor:`, `test:`, `chore:`, `assets:`.

The commit body explains **why**, not what: the diff shows what changed. For `exp:` commits,
put the result in the body, so the git log doubles as an experiment record next to
[results/experiments.md](../results/experiments.md):

```
exp: add pre-grasp frames to YOLO training

test photo: 7/8 -> 8/8 right at conf 0.25, val mAP50-95 0.861 -> 0.870
```

| Before | After |
|---|---|
| `update` | `fix: keep the start pose when the arm returns within tolerance` |
| `changes` | `feat: add the sorting pipeline runner` |
| `final version` | `docs: add the metal ACT model to the model table` |

## Data and models

- Never commit datasets or weights: datasets go to Hub dataset repos
  (`scripts/dataset/sync.sh push`), models to Hub model repos (see [models/](../models/README.md)).
- One person records a given dataset at a time; pull before recording and push right after
  (see [docs/cloud-storage.md](cloud-storage.md#team-rules)).
- A new model becomes the default by changing `config/default.yaml`, in a commit that also
  updates `results/`.

## Authorship

- **Shared work**: credit both people with a `Co-authored-by:` trailer.
- **AI-assisted work**: the commit is made by a human under their own name, and that person
  must be able to explain every line. If AI tooling produced a substantial part of a change,
  it may be marked with an `Assisted-by: <tool>` trailer; the README's "AI usage" section
  lists what was AI-assisted.
- Even contribution is a pattern over the whole semester, not a last-week fix.

## Rhythm

- Commit at least once a week per person.
- Plan with GitHub Issues and milestones matching the course dates (proposal, midterm, poster,
  final defense); write experiment issues as hypothesis → setup → result → conclusion.

## Access

Add the instructor(s) and mentor as collaborators of the GitHub repo and members of the
`cleany-ai` Hugging Face organization (needed for the private YOLO frames dataset).
