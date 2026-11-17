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

Flags: `--model`, `--max-steps` (default 25), `--api-base` (local models).

## Test

```
.venv/bin/python -m pytest -q
```
