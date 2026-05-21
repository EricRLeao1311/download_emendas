from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inicia um Cloudflare Quick Tunnel em segundo plano.")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--host", default="127.0.0.1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    binary_path = ROOT_DIR / "tools" / "cloudflared" / "cloudflared.exe"
    if not binary_path.exists():
      print(f"cloudflared nao encontrado em {binary_path}", file=sys.stderr)
      return 1

    tmp_dir = ROOT_DIR / "data" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    log_path = tmp_dir / "cloudflared.out"
    pid_path = tmp_dir / "cloudflared.pid"

    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            str(binary_path),
            "tunnel",
            "--url",
            f"http://{args.host}:{args.port}",
        ],
        cwd=ROOT_DIR,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    print(f"Tunel iniciado com PID {process.pid}. Log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
