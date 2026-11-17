# Security notes

This is a local, single-user tool. The limits below are known and accepted.

- **The shell tool is not a sandbox.** `run_shell` runs a command with your user's rights. The working directory is the workspace, but the command can read or write anywhere you can. Use `ask` (the default) or `deny` for the `shell` category in directories you do not trust.
- **Environment filtering is by name only.** The child process does not receive variables whose names look secret (`*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `AGENT_API_KEY`, and similar). A key stored under an unusual name still reaches the child. Names such as `SSH_KEY` are stripped too, which can break commands that need them.
- **The `.agent/` guard only prevents accidents.** `write_file` and `edit_file` refuse paths under `<workspace>/.agent/` (case-insensitive on macOS and Windows). A shell command can still change that directory.
- **Path checks are check-then-use.** File tools resolve symlinks and reject paths outside the workspace before any I/O. A symlink swapped between the check and the use is not defended against.
- **Scrubbing is exact-match.** Provider errors shown to you never include the provider's message text. The optional debug log (`AGENT_DEBUG=1`) removes known key values, but a provider that echoes only a masked fragment of a key (for example `sk-abc***`) is not matched.
- **Workspace config is untrusted.** A cloned repository can contain `.agent/config.json`. It cannot set `model`, `api_base` or `api_key` (these are global only, so your key cannot be redirected to another host). It can loosen permissions, so the CLI asks once per workspace per session before honoring a looser setting than your global one. The answer is not stored.
- **Credentials** are stored in `credentials.json` in the global config directory with mode 0600. The CLI warns if the mode is wider. `AGENT_API_KEY` or a provider variable such as `OPENAI_API_KEY` avoid the file.
- **Change log.** The log holds relative paths and short reasons for write and edit calls. Shell command text is never written to it.
