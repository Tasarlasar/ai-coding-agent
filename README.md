# Build Your Own AI Coding Agent
A personal AI coding agent built from scratch. It starts as a simple agentic loop (model call, tool call, observe, repeat) and grows toward the capabilities of tools like Claude Code, GitHub Copilot, and Cursor Agent.

## Install

Developed with Python 3.14 (`requires-python >= 3.10`).

```
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## Run

```
export AGENT_API_KEY=...            # or a provider variable such as OPENAI_API_KEY
.venv/bin/python -m agent --model gpt-4o
```

On start the CLI asks for a workspace directory (required; the last one is offered again). File tools cannot leave it.

Flags: `--workspace`, `--model`, `--max-steps` (default 25), `--api-base` (local models). Flags apply to the current run only.

## Configuration

Type `/config` in the CLI to view and edit each operation category (`read`, `write`, `edit`, `shell`) as `allow`, `ask` or `deny`, and to choose where the change is saved.

| Scope | File | Notes |
|---|---|---|
| Global | `~/.config/agent-cli/config.json` (or `$XDG_CONFIG_HOME`, `%APPDATA%`, `$AGENT_CONFIG_DIR`) | Default everywhere |
| Workspace | `<workspace>/.agent/config.json` | Overrides global for that directory only |

Workspace settings win over global, per key. The model and `api_base` are global only. The API key comes from `AGENT_API_KEY`, else `credentials.json` in the global directory (mode 0600), else a provider variable such as `OPENAI_API_KEY`. A corrupt config file is ignored with a warning and never overwritten. Defaults: read allow, write/edit/shell ask. Answering `always` at a prompt allows that category for the rest of the session only.

See `docs/security.md` for what the permissions do and do not protect.

## Test

```
.venv/bin/python -m pytest -q
```

## Change log

Each task appends to `<workspace>/.agent/changelog.log`. The runtime writes it, with no extra model call, and it is not sent to the model unless the model reads it.

```
# task 2025-01-15T10:32:00 | Add a CLI entry point
2025-01-15T10:32:05 | write | src/app.py | Create entry point with main()
2025-01-15T10:33:10 | edit | src/app.py | Fix off-by-one in loop
#> Task done: 2 change(s)
#>   src/app.py: Fix off-by-one in loop
#> verify: 1 shell run(s), last exit 0
# end 2025-01-15T10:32:00 done | 2 changes
```

Only successful writes and edits get a line (path, and the one-sentence reason the model gave, or `(none given)`). Reads and shell commands are never logged, and shell command text never reaches the file. The terminal shows a summary of at most 15 lines at the end of each task, including the shell commands that ran and their exit codes. The next task starts with fresh context plus a short project summary built from this log.
