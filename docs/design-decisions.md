# Design Decisions and Tradeoffs

Each section lists the choice made, the alternatives, and why.

## 1. Language: Python

| | Python | TypeScript |
|---|---|---|
| SDKs | Official SDKs from every major provider, most examples | Official, fewer tutorials |
| Setup | `python -m agent` | Node, `tsconfig`, build or `tsx` step |
| Types | Optional hints | Strong, helpful for tool schemas |
| Terminal UI | `rich`, `prompt_toolkit` | `ink` |

**Choice: Python.** The learning goal is the agent loop, so the language should add little friction. TypeScript would fit better if matching Claude Code's stack or building an editor extension.

## 2. Model access: bring your own key, any model

Alternatives: lock to one provider, use a unified library (LiteLLM), or write one adapter per provider.

| | Single provider | LiteLLM (unified) | Own adapters |
|---|---|---|---|
| Code size | Smallest | Small | Largest |
| Model coverage | One | 100+ models, local too | Only what you write |
| Tool-call normalization | None needed | Done for you | You maintain it |
| Dependency risk | Low | Medium (large dependency) | Low |

**Choice: our own thin `Provider` interface (`complete(messages, tools) -> response`) with LiteLLM as the first backend.** Any model works from day one, and the interface keeps the agent core independent of LiteLLM, so it can be replaced. The cost is one extra layer of abstraction. Keys come from environment variables or a local config file with restricted permissions, never from the repository.

## 3. Interface: CLI

| | CLI | Web UI | Editor extension |
|---|---|---|---|
| Effort | Lowest | High (frontend work) | Highest |
| Filesystem and shell access | Native | Needs a backend | Via the editor API |

**Choice: CLI.** It matches Claude Code and Kiro's agent flow. The core stays separate from the interface so a UI can be added later. The CLI uses plain `input()` prompts; no `rich` or `prompt_toolkit` dependency was added.

## 4. Agent loop: hand-written, native tool calling

- **Hand-written vs framework (LangChain etc.):** the loop is small, and frameworks hide what this project is meant to teach and add churn. Cost: some plumbing is ours.
- **Native tool calling vs text parsing:** structured calls validated against JSON schemas are reliable. Text parsing is brittle and only helps models without tool support.

**Choice: hand-written loop with native tool calling.** Models without tool support are out of scope initially.

## 5. Tools: small, general set

Read, write, edit, list directory, grep/search, run shell command. More tools make selection harder and cost prompt tokens.

**Edit method: exact search-and-replace over whole-file rewrite.** Rewrites waste tokens and can silently drop code. Cost: the edit fails if the match is not unique, so the tool returns a clear error the model can recover from.

## 6. Mandatory workspace directory

The user must select a directory before the agent runs. All file tools resolve paths against it and reject anything that escapes it (including through symlinks).

- Pro: clear environment, bounded blast radius, per-directory config and logs.
- Con: one extra step at startup. Shell commands can still reach outside the directory, so the shell tool is gated by permissions and starts with the workspace as its working directory. It is not a true sandbox.

## 7. Permissions: allow / ask / deny, global or per-directory

Each operation category (read, write, edit, shell, network if added) has one of three modes. Settings live in two places:

| Scope | Location | Use |
|---|---|---|
| Global | user config dir | Default behavior everywhere |
| Workspace | `<workspace>/.agent/config.json` | Overrides global for that directory |

Workspace settings override global. A config menu in the CLI edits both.

Alternatives considered: ask every time (safe, tedious), trust everything (fast, risky). Per-operation modes with scoped overrides let users be strict in unfamiliar projects and relaxed in their own. Cost: more config code and a precedence rule to understand.

## 8. Context management

Sending the full history on every call is simple but costs more and hits context limits on long tasks.

**Choice, layered:**
1. Truncate large tool outputs (head and tail plus a note) at the time they are returned.
2. Replace old, bulky tool results with short stubs once they are no longer needed.
3. When history nears the model's limit, summarize older turns into a compact task-state note.
4. Keep each task's state separate, so a new task starts with a clean context plus a short project summary.

Cost: summarization can lose detail, so the summary keeps file paths, decisions, and open items, and the full record stays in the change log on disk.

## 9. Change log: token-efficient, with reasoning

The log is written to disk by the agent runtime and is not part of the model context unless needed.

- One compact line-oriented entry per change: timestamp, action, path, and a one-sentence reason. Diffs are not stored in the log.
- A short end-of-task summary lists what changed and why.
- The model supplies the reason as a short field on write/edit calls, so no extra model call is needed for logging.

Alternative: ask the model to write a narrative afterward. That costs extra tokens and can drift from what actually happened. Cost of the chosen approach: reasons are brief, and the log does not replace git history.

## 10. Kiro-style agent flow

The agent works through a task as a visible sequence: understand the request, inspect the workspace, make a short plan, execute steps with tools, verify (run commands or tests), then report with the change summary. A task is the unit for context, logging, and summaries. Cost: a small planning overhead per task, offset by fewer wandering tool calls.

## 11. Build order

Thin vertical slices, each committed: loop with one tool, remaining tools, workspace selection and path safety, permissions and config menu, context management, change log, then extras. Streaming output and sub-agents were considered and are not built (see the README roadmap). Alternative of designing everything first risks unneeded abstraction and delays a working system.
