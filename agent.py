from __future__ import annotations

import sys
from pathlib import Path

from src.mini_agent import MiniAgent


def main() -> int:
    workspace = Path.cwd()
    agent = MiniAgent(workspace=workspace)

    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
        print(agent.run(task))
        return 0

    print("Mini Agent interactive mode. Type 'exit' to quit.\n")
    while True:
        try:
            task = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if task.lower() in {"exit", "quit"}:
            return 0
        if not task:
            continue

        print(agent.run(task))


if __name__ == "__main__":
    raise SystemExit(main())
