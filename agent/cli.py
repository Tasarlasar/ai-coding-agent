"""Command line interface. The only module that talks to the user."""
from __future__ import annotations

import argparse
import os
import sys
from typing import Callable

from agent import config
from agent.loop import AgentLoop
from agent.providers.litellm_provider import LiteLLMProvider
from agent.tools import ToolContext, build_tools
from agent.workspace import Workspace, WorkspaceError

HELP = "Commands: /workspace, /help, /exit. Any other line is a task."


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent", description="Personal AI coding agent")
    parser.add_argument("--workspace", help="workspace directory the agent may work in")
    parser.add_argument("--model", help="model name, e.g. gpt-4o")
    parser.add_argument("--max-steps", type=int, default=25)
    parser.add_argument("--api-base", help="custom API base URL (local models)")
    args = parser.parse_args(argv)

    if not args.model:
        print("error: no model set; pass --model NAME")
        return 1
    api_key = (os.environ.get("AGENT_API_KEY") or "").strip() or None
    problem = LiteLLMProvider.preflight(args.model, api_key, args.api_base)
    if problem:
        print(problem)
        return 1

    workspace = _choose_workspace(args.workspace)
    if workspace is None:
        return 1
    print(f"Workspace: {workspace.root}")
    provider = LiteLLMProvider(args.model, api_key, args.api_base)
    ctx = ToolContext(workspace)
    loop = AgentLoop(provider, build_tools(), ctx, args.max_steps, _emit, _confirm)
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
            continue
        if line == "/workspace":
            new = _choose_workspace(None)
            if new is None:
                return 1
            workspace = new
            loop = AgentLoop(provider, build_tools(), ToolContext(workspace), args.max_steps,
                             _emit, _confirm)
            print(f"Workspace: {workspace.root}")
            continue
        try:
            loop.run_task(line)
        except KeyboardInterrupt:
            print("\ninterrupted")


if __name__ == "__main__":
    sys.exit(main())
