"""Command line interface. The only module that talks to the user."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from agent.loop import AgentLoop
from agent.providers.litellm_provider import LiteLLMProvider
from agent.tools import ToolContext, build_tools

HELP = "Commands: /help, /exit. Any other line is a task."


def _emit(kind: str, text: str) -> None:
    print(text if kind in ("assistant", "info") else f"[{kind}] {text}")


def _confirm(prompt: str) -> str:
    try:
        answer = input(f"{prompt} [y/n/a]: ").strip().lower()
    except EOFError:
        return "no"
    return {"y": "yes", "yes": "yes", "a": "always", "always": "always"}.get(answer, "no")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent", description="Personal AI coding agent")
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

    provider = LiteLLMProvider(args.model, api_key, args.api_base)
    ctx = ToolContext(workspace_root=Path.cwd())
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
        loop.run_task(line)


if __name__ == "__main__":
    sys.exit(main())
