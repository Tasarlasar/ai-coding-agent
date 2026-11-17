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

## Usage

```
$ .venv/bin/python -m agent --model gpt-4o
Workspace directory (required): ~/projects/demo
> create a small Python package with an add function and a test
```

Each line you type is one task. The agent follows a fixed flow, printed as it happens: understand the request, inspect the workspace, write a short numbered plan, execute with tools, verify by running the tests, then report. Tool calls show as `-> edit_file src/app.py` followed by a one-line result. When a category is set to `ask`, you are prompted `[y/n/a]` (yes, no, always for this session). At the end a change summary of at most 15 lines is printed.

Commands: `/config` (permissions, model, API key), `/workspace` (switch directory), `/help`, `/exit`. Ctrl-C during a task interrupts it and returns to the prompt.

Tools: `read_file`, `write_file`, `edit_file` (exact, unique search and replace), `list_dir`, `search` (regex), `run_shell` (workspace as cwd, 60 s timeout, secret-looking environment variables removed). Output is not token-streamed.

## Manual smoke checklist

These need a terminal and, for the last item, a real API key.

1. Start with no workspace (`--workspace` omitted, no remembered path): a task is refused until a valid directory is entered, and a missing path or a file is rejected with a message and a new prompt.
2. Restart: the last directory is offered with `[Enter]`, and a new path can be typed instead.
3. `/config`: each category shows its mode and source (`default`, `global`, `workspace`). Change `shell` to `deny` at workspace scope and check `<workspace>/.agent/config.json`. Another workspace still shows the global value.
4. With a real model: ask for "create a small Python package with a function and a test". The agent should create a `src` or package directory and a `tests/` directory, run the tests, and print a change summary. `<workspace>/.agent/changelog.log` should list each write and edit with a reason and no shell command text.

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

An offline end-to-end check with a stub provider is in `.agents/tasks/coding-agent/e2e_check.py` (`.venv/bin/python .agents/tasks/coding-agent/e2e_check.py`).
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
