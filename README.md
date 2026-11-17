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
