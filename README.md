# Mini AI Agent (from scratch)

A minimal, extensible AI agent you can run locally.

## Architecture (client + backend)
- `agent.py` is the local agent client.
- `backend.py` is your trusted server-side proxy.
- Backend auth: Codex OAuth (Open Claw-style), using `~/.codex/auth.json` from `codex login`.
- The client calls backend `/v1/complete` (no OpenAI key in client).

## Features
- ReAct-style loop (think -> act -> observe -> answer)
- Tool calling via strict JSON actions
- Local memory persisted to disk
- No external SDK required (Python stdlib HTTP)

## Project structure
- `agent.py`: CLI entrypoint
- `backend.py`: backend server entrypoint
- `src/mini_agent.py`: core agent loop
- `src/tools.py`: built-in tools
- `src/llm_openai.py`: client that calls backend
- `src/backend_server.py`: backend that calls OpenAI API

## Requirements
- Python 3.10+
- `codex login` completed on the backend machine

## Quickstart
1. Start backend in terminal A:
```bash
python3 backend.py
```

2. Run agent in terminal B:
```bash
python3 agent.py "Find the current files in this project"
```

Interactive mode:
```bash
python3 agent.py
```

## Environment variables
Backend:
- `OPENAI_MODEL` (optional, default: `gpt-4.1-mini`)
- `AGENT_BACKEND_TOKEN` (optional but recommended)
- `BACKEND_HOST` (optional, default: `127.0.0.1`)
- `BACKEND_PORT` (optional, default: `8787`)
- `CODEX_AUTH_FILE` (optional, default: `~/.codex/auth.json`)
- `OPENAI_OAUTH_CLIENT_ID` (optional single client-id override)
- `OPENAI_OAUTH_CLIENT_IDS` (optional comma-separated client-id list override)
- `OPENAI_OAUTH_REDIRECT_URI` (optional single redirect override)
- `OPENAI_OAUTH_REDIRECT_URIS` (optional comma-separated redirect list override)

Client:
- `AGENT_BACKEND_URL` (optional, default: `http://127.0.0.1:8787`)
- `AGENT_BACKEND_TOKEN` (must match backend if enabled)
- `OPENAI_MODEL` (optional, sent as request hint)
- `AGENT_MAX_STEPS` (optional, default: `6`)

## Example prompts
- `List files and summarize what this project does.`
- `Use tools to inspect README and tell me how to run this app.`
- `Create a TODO file with 3 improvements for this agent.`

## Safety notes
- File operations are restricted to the current workspace.
- Shell command tool is intentionally omitted to reduce risk in this starter.
- Keep backend on private network/localhost unless you add stronger auth/rate limits.

## Codex OAuth flow
Backend auth flow:
1. read OAuth access token from `~/.codex/auth.json`
2. if missing/expired, refresh tokens at `https://auth.openai.com/oauth/token`
3. reuse `tokens.access_token` directly; refresh using `refresh_token` when needed

This matches the same pattern used by Codex/Open Claw style `codex-cli` auth reuse.
