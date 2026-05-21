from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from download_emendas.auth import AccessTokenStore, generate_token
from download_emendas.settings import load_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera e lista tokens de acesso do baixador.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    create_command = subcommands.add_parser("create", help="Cria um novo token.")
    create_command.add_argument("--label", default="Token de acesso", help="Nome amigavel do token.")

    subcommands.add_parser("list", help="Lista os tokens cadastrados sem revelar o valor bruto.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings(ROOT_DIR)
    store = AccessTokenStore(settings.auth.tokens_path)

    if args.command == "create":
        raw_token = generate_token()
        stored = store.add(args.label, raw_token)
        print(f"Token criado: {args.label}")
        print(f"Hash salvo em: {settings.auth.tokens_path}")
        print(f"Token bruto: {raw_token}")
        print(f"Criado em: {stored.created_at_utc}")
        return 0

    for token in store.load():
        print(f"{token.label} | {token.created_at_utc} | {token.token_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
