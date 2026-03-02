from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict


ToolFn = Callable[[dict[str, Any]], str]


class ToolRegistry:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self._tools: dict[str, ToolFn] = {
            "list_files": self.list_files,
            "read_file": self.read_file,
            "write_file": self.write_file,
        }

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def run(self, name: str, args: dict[str, Any]) -> str:
        fn = self._tools.get(name)
        if fn is None:
            return f"ERROR: unknown tool '{name}'. Available: {', '.join(self.names())}"
        try:
            return fn(args)
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: tool '{name}' failed: {exc}"

    def schema(self) -> str:
        return json.dumps(
            {
                "type": "object",
                "required": ["type"],
                "properties": {
                    "type": {"type": "string", "enum": ["action", "final"]},
                    "tool": {"type": "string", "enum": self.names()},
                    "args": {"type": "object"},
                    "answer": {"type": "string"},
                },
            },
            indent=2,
        )

    def _resolve(self, rel_path: str) -> Path:
        candidate = (self.workspace / rel_path).resolve()
        if not str(candidate).startswith(str(self.workspace)):
            raise ValueError("path escapes workspace")
        return candidate

    def list_files(self, args: dict[str, Any]) -> str:
        start = args.get("path", ".")
        max_items = int(args.get("max_items", 200))
        root = self._resolve(start)
        if not root.exists():
            return f"ERROR: path not found: {start}"

        items: list[str] = []
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(self.workspace)
            items.append(str(rel) + ("/" if p.is_dir() else ""))
            if len(items) >= max_items:
                break

        return "\n".join(items) if items else "(empty)"

    def read_file(self, args: dict[str, Any]) -> str:
        path = args.get("path")
        if not path:
            return "ERROR: missing 'path'"
        max_chars = int(args.get("max_chars", 4000))
        f = self._resolve(path)
        if not f.exists() or not f.is_file():
            return f"ERROR: file not found: {path}"

        text = f.read_text(encoding="utf-8")
        if len(text) > max_chars:
            return text[:max_chars] + "\n...<truncated>"
        return text

    def write_file(self, args: dict[str, Any]) -> str:
        path = args.get("path")
        content = args.get("content")
        if not path:
            return "ERROR: missing 'path'"
        if content is None:
            return "ERROR: missing 'content'"

        f = self._resolve(path)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(str(content), encoding="utf-8")
        return f"WROTE: {f.relative_to(self.workspace)}"
