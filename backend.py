from __future__ import annotations

import os

from src.backend_server import run_server


def main() -> int:
    host = os.getenv("BACKEND_HOST", "127.0.0.1")
    port = int(os.getenv("BACKEND_PORT", "8787"))
    run_server(host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
