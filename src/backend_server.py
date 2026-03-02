from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request

from src.codex_oauth import CodexOAuthProvider


OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class BackendHandler(BaseHTTPRequestHandler):
    server_version = "MiniAgentBackend/0.1"
    oauth = CodexOAuthProvider()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            _json_response(self, 200, {"ok": True})
            return
        _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/complete":
            _json_response(self, 404, {"error": "not found"})
            return

        required_token = os.getenv("AGENT_BACKEND_TOKEN")
        if required_token:
            auth = self.headers.get("Authorization", "")
            expected = f"Bearer {required_token}"
            if auth != expected:
                _json_response(self, 401, {"error": "unauthorized"})
                return

        try:
            access_token = self.oauth.get_access_token()
        except RuntimeError as exc:
            _json_response(
                self,
                500,
                {
                    "error": "Codex OAuth credentials unavailable",
                    "details": str(exc),
                    "hint": "Run `codex login` on this machine.",
                },
            )
            return

        length_str = self.headers.get("Content-Length", "0")
        try:
            length = int(length_str)
        except ValueError:
            _json_response(self, 400, {"error": "invalid content length"})
            return

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            _json_response(self, 400, {"error": "invalid json"})
            return

        system_prompt = str(payload.get("system_prompt", ""))
        user_prompt = str(payload.get("user_prompt", ""))
        model = str(payload.get("model") or os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
        temperature = payload.get("temperature", 0)

        provider = os.getenv("BACKEND_PROVIDER", "codex").strip().lower()
        if provider == "codex":
            content, err = self._request_codex_cli(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            if err:
                code, details = err
                _json_response(self, 502, {"error": f"Codex provider HTTP {code}", "details": details})
                return
            _json_response(self, 200, {"content": content})
            return

        chat_payload = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        responses_payload = {
            "model": model,
            "temperature": temperature,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        content, err = self._request_openai_with_fallback(
            access_token=access_token,
            chat_payload=chat_payload,
            responses_payload=responses_payload,
        )
        if err:
            code, details = err
            _json_response(self, 502, {"error": f"OpenAI HTTP {code}", "details": details})
            return

        _json_response(self, 200, {"content": content})

    def log_message(self, fmt: str, *args: object) -> None:
        # Keep backend logs minimal but visible for local debugging.
        print(f"[backend] {self.address_string()} - {fmt % args}")

    @staticmethod
    def _call_openai(
        req: urllib.request.Request,
    ) -> tuple[str | None, tuple[int, str] | None]:
        retries = 3
        backoff_seconds = [0.4, 1.0, 2.0]
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    return resp.read().decode("utf-8"), None
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                if e.code >= 500 and attempt < retries - 1:
                    time.sleep(backoff_seconds[attempt])
                    continue
                return None, (e.code, body)
            except urllib.error.URLError as e:
                if attempt < retries - 1:
                    time.sleep(backoff_seconds[attempt])
                    continue
                return None, (503, str(e))
        return None, (503, "upstream retries exhausted")

    def _request_codex_cli(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str | None, tuple[int, str] | None]:
        codex_bin = os.getenv("CODEX_BIN", "/Applications/Codex.app/Contents/Resources/codex")
        prompt = (
            f"{system_prompt}\n\n"
            f"User prompt:\n{user_prompt}\n\n"
            "Return only the answer."
        )
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, encoding="utf-8") as tmp:
            output_path = tmp.name

        cmd = [
            codex_bin,
            "exec",
            "--skip-git-repo-check",
            "-C",
            str(Path.cwd()),
            "-o",
            output_path,
            prompt,
        ]
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except Exception as exc:  # noqa: BLE001
            return None, (500, f"failed to run codex exec: {exc}")

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            details = stderr if stderr else stdout
            if not details:
                details = f"codex exited with status {proc.returncode}"
            return None, (500, details)

        try:
            content = Path(output_path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            return None, (500, f"failed to read codex output: {exc}")
        finally:
            try:
                Path(output_path).unlink(missing_ok=True)
            except OSError:
                pass

        if not content:
            return None, (500, "codex returned empty output")
        return content, None

    def _request_openai_with_fallback(
        self,
        access_token: str,
        chat_payload: dict[str, Any],
        responses_payload: dict[str, Any],
    ) -> tuple[str | None, tuple[int, str] | None]:
        # Try chat completions first for compatibility with current agent payload shape.
        raw, err = self._request_openai_json(OPENAI_CHAT_URL, access_token, chat_payload)
        if err is None and raw is not None:
            parsed_content = self._parse_chat_completion(raw)
            if parsed_content is not None:
                return parsed_content, None

        # Fall back to Responses API, which can be more reliable for OAuth bearer tokens.
        raw2, err2 = self._request_openai_json(OPENAI_RESPONSES_URL, access_token, responses_payload)
        if err2 is None and raw2 is not None:
            parsed_content = self._parse_responses_output(raw2)
            if parsed_content is not None:
                return parsed_content, None

        # If both fail, return the most relevant error (responses first, then chat).
        if err2 is not None:
            return None, err2
        if err is not None:
            return None, err
        return None, (502, "Could not parse OpenAI response from either endpoint")

    def _request_openai_json(
        self,
        url: str,
        access_token: str,
        payload: dict[str, Any],
    ) -> tuple[str | None, tuple[int, str] | None]:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
            method="POST",
        )
        raw, err = self._call_openai(req)
        if err and err[0] == 401 and self.oauth.can_refresh():
            try:
                refreshed = self.oauth.get_access_token(force_refresh=True)
            except RuntimeError as exc:
                return None, (401, f"OpenAI unauthorized and refresh failed: {exc}")
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {refreshed}",
                },
                method="POST",
            )
            return self._call_openai(req)
        return raw, err

    @staticmethod
    def _parse_chat_completion(raw: str) -> str | None:
        try:
            parsed = json.loads(raw)
            content = parsed["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            return None
        return str(content)

    @staticmethod
    def _parse_responses_output(raw: str) -> str | None:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None

        output_text = parsed.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        output = parsed.get("output")
        if isinstance(output, list):
            pieces: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    text = part.get("text")
                    if isinstance(text, str):
                        pieces.append(text)
            if pieces:
                return "".join(pieces)
        return None


def run_server(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), BackendHandler)
    print(f"Mini agent backend listening on http://{host}:{port}")
    server.serve_forever()
