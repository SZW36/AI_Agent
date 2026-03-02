from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from src.llm_openai import OpenAIClient
from src.tools import ToolRegistry


@dataclass
class AgentConfig:
    max_steps: int = 6
    memory_file: str = ".agent_memory.json"


class MiniAgent:
    def __init__(self, workspace: Path, config: AgentConfig | None = None):
        self.workspace = workspace.resolve()
        self.config = config or AgentConfig(max_steps=int(os.getenv("AGENT_MAX_STEPS", "6")))
        self.tools = ToolRegistry(self.workspace)
        self.llm = OpenAIClient()
        self.memory_path = self.workspace / self.config.memory_file

    def _load_memory(self) -> list[dict[str, str]]:
        if not self.memory_path.exists():
            return []
        try:
            return json.loads(self.memory_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return []

    def _save_memory(self, memory: list[dict[str, str]]) -> None:
        self.memory_path.write_text(json.dumps(memory[-30:], indent=2), encoding="utf-8")

    def run(self, task: str) -> str:
        memory = self._load_memory()
        context = {
            "task": task,
            "observations": [],
        }

        system_prompt = (
            "You are a careful local coding agent. "
            "Always return valid JSON only, with no markdown. "
            "Use this schema: "
            f"{self.tools.schema()} "
            "Rules: "
            "1) If you need data, return {type:'action', tool:'...', args:{...}}. "
            "2) If done, return {type:'final', answer:'...'}"
        )

        for _step in range(self.config.max_steps):
            user_prompt = json.dumps(
                {
                    "memory": memory[-6:],
                    "task": context["task"],
                    "observations": context["observations"],
                    "tools": self.tools.names(),
                },
                indent=2,
            )

            raw = self.llm.complete(system_prompt=system_prompt, user_prompt=user_prompt)
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                # One lightweight retry hint by converting invalid output into observation.
                context["observations"].append(f"Invalid JSON from model: {raw[:400]}")
                continue

            if obj.get("type") == "final":
                answer = str(obj.get("answer", ""))
                memory.append({"task": task, "answer": answer})
                self._save_memory(memory)
                return answer

            if obj.get("type") == "action":
                tool = str(obj.get("tool", ""))
                args = obj.get("args", {})
                if not isinstance(args, dict):
                    args = {}
                result = self.tools.run(tool, args)
                context["observations"].append(
                    json.dumps({"tool": tool, "args": args, "result": result})
                )
                continue

            context["observations"].append(f"Unexpected object: {obj}")

        fallback = "I hit the max step limit before finishing. Try increasing AGENT_MAX_STEPS."
        memory.append({"task": task, "answer": fallback})
        self._save_memory(memory)
        return fallback
