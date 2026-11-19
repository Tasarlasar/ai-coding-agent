# Project Explainer Video Guide

Target length: 9 minutes (budget 8 to 10). The video covers the project concept, system architecture, key implementation details and a working demonstration. Slides are in `docs/SLIDES.md` (Marp deck); the diagrams are in `docs/diagrams/`.

| # | Time | Section | Show |
|---|---|---|---|
| 1 | 0:00-1:00 | Concept | Slide 1-2 |
| 2 | 1:00-3:00 | Architecture | Slides 3-4, `docs/diagrams/architecture.png`, `agent-loop.png` |
| 3 | 3:00-5:00 | Key implementation | Slides 5-8, `agent/loop.py`, `agent/permissions.py`, `agent/context.py` |
| 4 | 5:00-8:00 | Live demo | Terminal |
| 5 | 8:00-9:00 | Results and wrap-up | Slides 10-12 |

## Before you record

- Screen recorder: QuickTime (File > New Screen Recording) or OBS. Record at 1920x1080, 30 fps, with microphone audio. Do one 10-second test clip and check the sound.
- Terminal: font size 18 to 20 pt, dark text on a plain background, window about 110 columns wide, notifications off.
- Hide secrets: never type or `echo` your key on screen. Export it before recording in a terminal you will not show, or in a shell started with `clear` afterwards. Do not open `credentials.json` or shell history. Check `git grep -n -i -E "sk-|api[_-]?key *= *['\"]"` shows nothing.
- Test the endpoint first (skip if you use the stub fallback). Run the exact demo command below once and give it a one-line task. If the model replies and a file appears, you are ready.
- Use a throwaway workspace, never your home directory or this repo:
  ```
  rm -rf /tmp/agent-demo && mkdir -p /tmp/agent-demo
  ```
- Use a clean config so earlier settings do not change the demo:
  ```
  export AGENT_CONFIG_DIR=$(mktemp -d)
  ```
- Open these files in tabs ahead of time: `agent/loop.py`, `agent/permissions.py`, `agent/context.py`, `docs/diagrams/architecture.png`.

## Script

### 1. Concept (0:00-1:00)

Show: slide 1, then slide 2.

> Hi, this is my coding agent for Project 1, Build Your Own AI Coding Agent. It is a Python command line tool that takes a task in plain English and builds software in a directory you choose. It reads files, writes and edits them, runs commands, and keeps a short log of every change with the reason. It is bring your own key. You give it any model that LiteLLM supports, or any OpenAI-compatible endpoint, and it works the same way. The flow is inspired by Claude Code, Copilot and Kiro: understand the request, inspect the project, plan, execute, verify, report.

### 2. Architecture (1:00-3:00)

Show: `docs/diagrams/architecture.png` (slide 3), then `docs/diagrams/agent-loop.png` (slide 4).

> The CLI is the only module that talks to the user. It reads the config, asks for the workspace, and starts the agent loop. The loop sends the history and tool definitions to a provider, and the provider is a small interface. LiteLLM is the only module that imports the model library, so swapping backends touches one file.
>
> Every tool call goes through the permission gate before it runs, and file paths go through the workspace module, which resolves real paths so symlinks cannot escape the directory. The loop is the classic cycle: call the model, run the tool calls it asks for, add the results to the history, repeat. It stops when the model answers without tool calls, or at the step limit. At the end, the change log summary is printed.

### 3. Key implementation details (3:00-5:00)

Show each file briefly, scrolling to the named part. Keep each under 30 seconds.

- `agent/loop.py` (slide 5): the model call, tool dispatch and step limit.
- `agent/permissions.py` (slide 6): `allow`, `ask`, `deny` per category; global and workspace scopes; workspace overrides global.
- `agent/context.py` (slide 7): truncation, stubbing of old results, summarization near the budget.
- Change log (slide 8): show the sample log format from the README.

> The loop is short on purpose. For each tool call it validates the arguments, asks the gate, runs the tool and appends the result. Permissions are per category: read, write, edit and shell. Each is allow, ask or deny, and you set it globally or for one directory from the in-CLI config menu. A workspace config can only loosen permissions after you confirm it, so a cloned repository cannot quietly grant itself shell access.
>
> Context is managed per task. Each task starts fresh with a short project summary. Large tool outputs are truncated, old bulky results become one-line stubs, and the history is summarized when it nears the token budget. The change log is written by the runtime, not the model. It is one line per write or edit with a one-sentence reason, so it costs no extra model call and stays small.

### 4. Live demo (5:00-8:00)

Show: terminal, large font. Choose the real endpoint (4a) or the stub (4b, also the fallback).

#### 4a. Real endpoint

Run from the repository root. The key goes in the environment, never on the command line:

```
export AGENT_API_KEY=<key the endpoint expects>    # do this off camera
.venv/bin/python -m agent --workspace /tmp/agent-demo \
  --api-base <your endpoint>/v1 --model openai/<model-id>
```

`--api-base` takes any OpenAI-compatible endpoint, and the `openai/` prefix selects the OpenAI protocol. For a standard provider, drop `--api-base` and use `--model gpt-4o` or similar.

Steps and what to say:

1. Startup (0:20). Expect `Workspace: /tmp/agent-demo`, then the command help line. Say: "I must choose a directory before the agent works. I passed it with `--workspace`; without the flag it asks and refuses to continue until the path is valid."
2. Config menu (0:40). Type `/config`. Expect rows for read, write, edit and shell with their mode and source (`default`, `global`, `workspace`). Pick the shell row, enter `ask`, then scope `w`. Expect `saved shell=ask (workspace)`. Type `q`. Say: "This one is saved for this directory only."
3. Task (1:20). Type:
   ```
   create a small Python package with an add function and a pytest test, then run the test
   ```
   Expect lines like `-> write_file src/...`, a one-line result under each, and a permission prompt `[y/n/a]` for writes and the shell command. Answer `y` to each, or `a` for writes. Say: "Each prompt shows what it wants to do and why."
4. Boundary (0:20). Type `list the files in /Users`. Expect `ERROR: path escapes workspace`. Say: "The code enforces the boundary, not the model."
5. Summary and log (0:30). After the first task, expect a block starting `Task done: N change(s)`, one line per changed file, and a `verify:` line with the shell exit code. Then `/exit`, and in the terminal run:
   ```
   cat /tmp/agent-demo/.agent/changelog.log
   ```
   Expect `# task ...` header, one `| write |` or `| edit |` line per change with a reason, `#>` summary lines and `# end ... done`.

If the model call fails, you will see a provider error line and the prompt returns. Fix the endpoint, key or model ID and re-record that part.

#### 4b. Offline stub (fallback, no endpoint needed)

Use this if no endpoint is available or the live run misbehaves. It uses a scripted provider, so output is the same every time. It does not call a model; say so in the narration.

```
.venv/bin/python scripts/e2e_check.py
```

Expect a series of `PASS:` lines, including `create files`, `edit file`, `ask mode prompts for write+shell`, `deny mode blocks without prompt`, `../ rejected`, `symlink file read/write rejected`, `workspace overrides global`, `changelog end-of-task summary` and `CLI exits without directory (EOF)`, followed by the printed change log, and the last line `20/20 passed`. Exit code 0.

Say: "This script drives the real loop, tools, permissions and change log with a scripted model, so every safety property is checked without network access."

Then run the unit tests:

```
.venv/bin/python -m pytest -q
```

Expect all tests passing (147 at the time of writing) with exit code 0.

To show the CLI directory requirement without a model:

```
.venv/bin/python -m agent --model x
```

Expect `Workspace directory (required):`. Type `/nonexistent` and expect a "does not exist" message and the prompt again. Press Ctrl-D to exit.

### 5. Results and wrap-up (8:00-9:00)

Show: slides 10, 11, 12.

> To sum up: the agent runs the full loop, works only inside a chosen directory, lets you decide per operation what is allowed, manages context per task, and logs each change with a reason in a few lines. It is tested offline with a scripted provider, and CI runs the tests on Python 3.10 to 3.13. The limits are honest. The shell is not a sandbox, output is not streamed, and quality depends on the model's tool calling. Next steps are streaming, sub-agents and a sandboxed shell. The code, the technical report and these slides are in the repository linked below. Thanks for watching.

## Recording checklist

- [ ] Endpoint tested with a one-line task, or stub fallback chosen
- [ ] `/tmp/agent-demo` empty, `AGENT_CONFIG_DIR` set to a temp dir
- [ ] Key exported off camera, not visible in history or prompt
- [ ] 1920x1080, font 18-20 pt, notifications off
- [ ] Audio level checked with a test clip
- [ ] Slides, diagrams and the three source files open in order
- [ ] Total length between 8 and 10 minutes
- [ ] Video uploaded, link added to the `Video` line in `README.md`
