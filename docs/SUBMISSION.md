# Submission Guide

## Requirement map

| Requirement | Where it is satisfied |
|---|---|
| GitHub repository: organized, clean, readable, documented source | `agent/` (module and public API docstrings), `tests/`, `scripts/e2e_check.py`, `README.md` (features, install, usage, layout, limits), `pyproject.toml`, `LICENSE`, `.github/workflows/ci.yml` |
| Project explainer video: concept, architecture, key implementation, working demo | Script and recording checklist in `docs/VIDEO_GUIDE.md`; slides in `docs/SLIDES.md`; link goes on the `Video` line in `README.md` |
| Technical project report: approach, architecture, design decisions, implementation, challenges, learnings | `docs/REPORT.md` and `docs/REPORT.pdf` (sections 5 to 11) |
| Architecture diagrams and technical artifacts | `docs/diagrams/` (Mermaid sources `.mmd`, rendered `.svg` and `.png`: architecture, agent loop, permission flow, context pipeline, data layout); recorded session `Test run.md`; `docs/design-decisions.md`; `docs/security.md`; `docs/DEMO_NARRATIVE.md` |
| Simple agentic loop, enhanced step by step | `agent/loop.py`, report section 6.2 |
| Autonomous tool-using system | `agent/tools.py`, `agent/permissions.py`, report sections 6.3 and 6.5 |

## Create the GitHub repository and push

Check first that the working tree is clean and you are on `main`:

```
git status
git branch --show-current
```

Option 1, website and git:

1. On github.com choose New repository. Give it a name, leave it empty (no README, license or .gitignore), and create it.
2. Run, with your own account and repository name:

```
git remote add origin https://github.com/<your-user>/<repo-name>.git
git push -u origin main
```

Option 2, GitHub CLI (`gh auth login` once first):

```
gh repo create <repo-name> --public --source=. --remote=origin --push
```

Use `--private` instead of `--public` if the course allows it, and add the instructor as a collaborator.

## Pre-submit checklist

- [ ] `README.md` renders on GitHub: diagram shows, tables are intact, links work
- [ ] CI is green on the Actions tab (Python 3.10 to 3.13)
- [ ] Tests pass locally: `.venv/bin/python -m pytest -q` and `.venv/bin/python scripts/e2e_check.py`
- [ ] No secrets in the repository. Run:
  ```
  git grep -n -i -E "sk-[a-z0-9]{10,}|api[_-]?key *= *['\"][^'\"]+|bearer [a-z0-9]{10,}"
  git log -p --all -S"sk-" --oneline | head
  ```
  Both should print nothing that is a real key. `README.md` mentions `AGENT_API_KEY=...` as a placeholder only.
- [ ] `Test run.md` checked for personal paths or hostnames you do not want public; redact if needed
- [ ] Video recorded following `docs/VIDEO_GUIDE.md`, uploaded, and its link pasted into the `Video` line in `README.md`, then committed and pushed
- [ ] `docs/REPORT.pdf` attached to the submission form or LMS, and present in the repository
- [ ] Repository URL, video link and PDF submitted before the deadline (Friday 20.11.2026)
