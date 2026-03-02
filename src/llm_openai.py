from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class OpenAIClient:
    """Client used by the local agent to call a trusted backend proxy."""

    def __init__(self, model: str | None = None):
        self.backend_url = os.getenv("AGENT_BACKEND_URL", "http://127.0.0.1:8787").rstrip("/")
        self.backend_token = os.getenv("AGENT_BACKEND_TOKEN")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "temperature": 0,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }

        headers = {"Content-Type": "application/json"}
        if self.backend_token:
            headers["Authorization"] = f"Bearer {self.backend_token}"

        req = urllib.request.Request(
            f"{self.backend_url}/v1/complete",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Backend HTTP {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Cannot reach backend at {self.backend_url}. "
                "Start backend.py and verify AGENT_BACKEND_URL."
            ) from e

        parsed = json.loads(raw)
        content = parsed.get("content")
        if not isinstance(content, str):
            raise RuntimeError(f"Invalid backend response: {raw[:300]}")
        return content.strip()
