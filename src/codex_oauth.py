from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request


TOKEN_URL = "https://auth.openai.com/oauth/token"
DEFAULT_CLIENT_IDS = [
    # Legacy/public client id seen in older Codex/Open Claw examples.
    "a03e36f8-1a5d-4a47-976b-bc9d3cd50978",
    # Client id seen in newer bundled Codex binaries.
    "app_EMoamEEZ73f0CkXaXp7hrann",
]
DEFAULT_REDIRECT_URIS = [
    "https://chatgpt.com/auth/callback",
    # Try without redirect_uri as some refresh flows do not require it.
    "",
]


class CodexOAuthProvider:
    """Reuses Codex CLI auth.json and provides OAuth access tokens."""

    def __init__(self, auth_file: str | None = None):
        auth_path = auth_file or os.getenv("CODEX_AUTH_FILE") or "~/.codex/auth.json"
        self.auth_path = Path(auth_path).expanduser()

        client_ids_raw = os.getenv("OPENAI_OAUTH_CLIENT_IDS")
        if client_ids_raw:
            candidates = [s.strip() for s in client_ids_raw.split(",") if s.strip()]
        else:
            single = os.getenv("OPENAI_OAUTH_CLIENT_ID")
            candidates = [single] if single else DEFAULT_CLIENT_IDS
        self.client_ids = candidates

        redirect_raw = os.getenv("OPENAI_OAUTH_REDIRECT_URIS")
        if redirect_raw:
            redirects = [s.strip() for s in redirect_raw.split(",")]
        else:
            single_redirect = os.getenv("OPENAI_OAUTH_REDIRECT_URI")
            redirects = [single_redirect] if single_redirect is not None else DEFAULT_REDIRECT_URIS
        self.redirect_uris = redirects

    def get_access_token(self, force_refresh: bool = False) -> str:
        auth = self._load_auth()
        if not force_refresh:
            token = self._extract_access_token(auth)
            if token:
                return token
        return self._refresh_and_save(auth)

    def can_refresh(self) -> bool:
        try:
            auth = self._load_auth()
        except RuntimeError:
            return False
        tokens = auth.get("tokens")
        if not isinstance(tokens, dict):
            return False
        return bool(tokens.get("refresh_token"))

    def _load_auth(self) -> dict[str, Any]:
        if not self.auth_path.exists():
            raise RuntimeError(f"Codex auth file not found: {self.auth_path}")
        try:
            return json.loads(self.auth_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Failed to read Codex auth file: {exc}") from exc

    def _write_auth(self, auth: dict[str, Any]) -> None:
        self.auth_path.parent.mkdir(parents=True, exist_ok=True)
        self.auth_path.write_text(json.dumps(auth, indent=2), encoding="utf-8")
        try:
            os.chmod(self.auth_path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _extract_access_token(auth: dict[str, Any]) -> str | None:
        tokens = auth.get("tokens")
        if not isinstance(tokens, dict):
            return None
        token = tokens.get("access_token")
        return str(token) if token else None

    def _refresh_and_save(self, auth: dict[str, Any]) -> str:
        tokens = auth.get("tokens")
        if not isinstance(tokens, dict):
            raise RuntimeError("Codex auth file is missing 'tokens'")
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Codex auth file is missing refresh_token")

        refreshed = self._oauth_refresh(str(refresh_token))
        access_token = refreshed.get("access_token")
        if not access_token:
            raise RuntimeError("OAuth refresh response missing access_token")

        auth["tokens"] = refreshed
        auth["last_refresh"] = datetime.now(timezone.utc).isoformat()
        self._write_auth(auth)
        return str(access_token)

    def _oauth_refresh(self, refresh_token: str) -> dict[str, Any]:
        errors: list[str] = []
        for client_id in self.client_ids:
            for redirect_uri in self.redirect_uris:
                payload = {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                }
                if redirect_uri:
                    payload["redirect_uri"] = redirect_uri

                try:
                    body = self._post_json(TOKEN_URL, payload)
                except RuntimeError as exc:
                    errors.append(f"{client_id} ({redirect_uri or 'no-redirect'}): {exc}")
                    continue

                access_token = body.get("access_token")
                new_refresh_token = body.get("refresh_token")
                if not access_token or not new_refresh_token:
                    errors.append(
                        f"{client_id} ({redirect_uri or 'no-redirect'}): invalid refresh body {body}"
                    )
                    continue

                return {
                    "access_token": access_token,
                    "refresh_token": new_refresh_token,
                    "id_token": body.get("id_token"),
                    "account_id": body.get("account_id"),
                }

        joined = "; ".join(errors[-3:]) if errors else "no attempts made"
        raise RuntimeError(
            "OAuth refresh failed for all client IDs. "
            "Run `codex logout` then `codex login` and retry. "
            f"Recent errors: {joined}"
        )

    @staticmethod
    def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error calling {url}: {exc}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON from {url}: {raw[:400]}") from exc
