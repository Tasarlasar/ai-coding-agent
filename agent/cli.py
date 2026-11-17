"""Command line interface. The only module that talks to the user."""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from typing import Callable

from agent import config
from agent.config import CATEGORIES, MODES, UNSET, ConfigError, LoadedSettings
from agent.loop import AgentLoop
from agent.permissions import PermissionGate
from agent.providers.litellm_provider import LiteLLMProvider
from agent.tools import build_tools
from agent.workspace import Workspace, WorkspaceError

HELP = "Commands: /config, /workspace, /help, /exit. Any other line is a task."


def _emit(kind: str, text: str) -> None:
    print(text if kind in ("assistant", "info") else f"[{kind}] {text}")


def _confirm(prompt: str) -> str:
    try:
        answer = input(f"{prompt} [y/n/a]: ").strip().lower()
    except EOFError:
        return "no"
    return {"y": "yes", "yes": "yes", "a": "always", "always": "always"}.get(answer, "no")


def select_workspace(flag: str | None, input_fn: Callable[[str], str], state: dict,
                     out: Callable[[str], None] = print) -> Workspace | None:
    """Return a validated Workspace, or None when input ends (EOF)."""
    if flag:
        try:
            return Workspace.validate(flag)
        except WorkspaceError as exc:
            out(f"--workspace: {exc}")
    remembered = state.get("last_workspace")
    if remembered:
        try:
            Workspace.validate(remembered)
        except WorkspaceError:
            remembered = None
    while True:
        prompt = (f"Workspace directory [Enter] to use {remembered} or type a new path: "
                  if remembered else "Workspace directory (required): ")
        try:
            answer = input_fn(prompt).strip()
        except EOFError:
            return None
        if not answer and remembered:
            answer = remembered
        try:
            return Workspace.validate(answer)
        except WorkspaceError as exc:
            out(str(exc))


def _choose_workspace(flag: str | None) -> Workspace | None:
    ws = select_workspace(flag, input, config.load_state())
    if ws is not None:
        try:
            config.save_last_workspace(str(ws.root))
        except OSError as exc:
            print(f"could not remember workspace: {exc}")
    return ws


def _ask(prompt: str) -> str | None:
    try:
        return input(prompt).strip()
    except EOFError:
        return None


class Session:
    """State that lives for one CLI run."""

    def __init__(self, args: argparse.Namespace, workspace: Workspace):
        self.args = args
        self.workspace = workspace
        self.session_allow: set[str] = set()
        self.honor_loosening: dict[str, bool] = {}

    def overrides(self) -> dict:
        return {k: v for k, v in (("model", self.args.model), ("api_base", self.args.api_base),
                                  ("max_steps", self.args.max_steps)) if v is not None}

    def load(self) -> LoadedSettings:
        loaded = config.load_settings(self.workspace.root, self.overrides())
        key = str(self.workspace.root)
        loose = config.loosened_categories(loaded)
        if loose and key not in self.honor_loosening:
            names = ", ".join(f"{c}={loaded.settings.permissions[c]}" for c in loose)
            answer = _ask(f"Workspace config loosens permissions ({names}). Honor it for this session? [y/N] ")
            self.honor_loosening[key] = (answer or "").lower() in ("y", "yes")
        if loose and not self.honor_loosening.get(key, False):
            merged = {**self.overrides(), **config.overrides_without_loosening(loaded)}
            loaded = config.load_settings(self.workspace.root, merged)
        return loaded

    def print_warnings(self, loaded: LoadedSettings) -> None:
        for w in loaded.warnings:
            print(f"warning: {w}")
        cw = config.credentials_warning()
        if cw:
            print(f"warning: {cw}")

    def change_workspace(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.session_allow = set()


def _provider_problem(settings, api_key: str | None) -> str | None:
    if not settings.model:
        return "no model set; use --model NAME or /config"
    return LiteLLMProvider.preflight(settings.model, api_key, settings.api_base)


def _run_task(session: Session, request: str) -> None:
    settings = session.load().settings
    api_key = config.resolve_api_key(os.environ)
    problem = _provider_problem(settings, api_key)
    if problem:
        print(problem)
        return
    provider = LiteLLMProvider(settings.model, api_key, settings.api_base)
    gate = PermissionGate(settings, _confirm, session.session_allow, session.workspace)
    loop = AgentLoop(provider, build_tools(), session.workspace, settings, gate, _emit)
    try:
        loop.run_task(request)
    except KeyboardInterrupt:
        print("\ninterrupted")


def _menu_rows(loaded: LoadedSettings) -> list[str]:
    rows = []
    for i, cat in enumerate(CATEGORIES, 1):
        mode = loaded.settings.permissions[cat]
        rows.append(f" {i}. {cat:<6} {mode:<6} [{loaded.sources[f'permissions.{cat}']}]")
    n = len(CATEGORIES)
    rows.append(f" {n + 1}. model  {loaded.settings.model or '(not set)'}  [{loaded.sources['model']}]")
    rows.append(f" {n + 2}. set API key")
    rows.append(" q. back")
    return rows


def config_menu(session: Session) -> None:
    ws = session.workspace.root
    while True:
        loaded = config.load_settings(ws, session.overrides())
        print(f"Config (workspace: {ws})")
        print("\n".join(_menu_rows(loaded)))
        choice = _ask("select: ")
        if choice is None or choice.lower() in ("q", ""):
            return
        try:
            n = int(choice)
        except ValueError:
            print("enter a number or q")
            continue
        try:
            if 1 <= n <= len(CATEGORIES):
                _edit_permission(loaded, CATEGORIES[n - 1], ws)
            elif n == len(CATEGORIES) + 1:
                value = _ask("model name (global setting, blank to cancel): ")
                if value:
                    config.save_setting("global", "model", value, ws)
            elif n == len(CATEGORIES) + 2:
                key = getpass.getpass("API key (input hidden, blank to cancel): ").strip()
                if key:
                    config.save_api_key(key)
                    print("API key saved")
                    cw = config.credentials_warning()
                    if cw:
                        print(f"warning: {cw}")
            else:
                print("no such row")
        except (OSError, ConfigError) as exc:
            print(f"could not save: {exc}")
        except EOFError:
            return


def _edit_permission(loaded: LoadedSettings, cat: str, ws) -> None:
    current = loaded.settings.permissions[cat]
    mode = _ask(f"{cat} mode (allow/ask/deny/unset) [{current}]: ")
    if not mode:
        return
    if mode != "unset" and mode not in MODES:
        print("invalid mode")
        return
    default_scope = "w" if loaded.sources[f"permissions.{cat}"] == "workspace" else "g"
    scope = (_ask(f"scope: [g]lobal or [w]orkspace [{default_scope}]: ") or default_scope).lower()
    if scope not in ("g", "w"):
        print("invalid scope")
        return
    scope_name = "global" if scope == "g" else "workspace"
    config.save_setting(scope_name, f"permissions.{cat}", UNSET if mode == "unset" else mode, ws)
    print(f"saved {cat}={mode} ({scope_name})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent", description="Personal AI coding agent")
    parser.add_argument("--workspace", help="workspace directory the agent may work in")
    parser.add_argument("--model", help="model name, e.g. gpt-4o")
    parser.add_argument("--max-steps", type=int, help="maximum model calls per task (default 25)")
    parser.add_argument("--api-base", help="custom API base URL (local models)")
    args = parser.parse_args(argv)

    workspace = _choose_workspace(args.workspace)
    if workspace is None:
        return 1
    session = Session(args, workspace)
    print(f"Workspace: {workspace.root}")
    loaded = session.load()
    session.print_warnings(loaded)
    problem = _provider_problem(loaded.settings, config.resolve_api_key(os.environ))
    if problem:
        print(f"{problem} (tasks are disabled until fixed; /config is available)")
    print(HELP)
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line == "/exit":
            return 0
        if line == "/help":
            print(HELP)
        elif line == "/config":
            try:
                config_menu(session)
            except KeyboardInterrupt:
                print()
        elif line == "/workspace":
            new = _choose_workspace(None)
            if new is None:
                return 1
            session.change_workspace(new)
            print(f"Workspace: {new.root}")
            session.print_warnings(session.load())
        else:
            _run_task(session, line)


if __name__ == "__main__":
    sys.exit(main())
