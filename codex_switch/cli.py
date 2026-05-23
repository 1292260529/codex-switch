from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .desktop import restart_codex_desktop
from .store import CodexSwitchError, AccountPool


def add_restart_args(parser: argparse.ArgumentParser, *, default_restart: bool) -> None:
    parser.set_defaults(restart_desktop=default_restart)
    parser.add_argument(
        "--restart-desktop",
        action="store_true",
        dest="restart_desktop",
        help="Restart Codex Desktop after the operation so the running app reloads auth",
    )
    parser.add_argument(
        "--no-restart-desktop",
        action="store_false",
        dest="restart_desktop",
        help="Do not restart Codex Desktop after the operation",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-switch")
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=None,
        help="Codex home directory, defaults to ~/.codex",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="save current Codex auth as an account")
    add.add_argument("alias", nargs="?", help="defaults to the login email from auth.json")
    add.add_argument(
        "--next-refresh",
        default=None,
        help="YYYY-MM-DD; defaults to the reset date from Codex usage",
    )
    add.add_argument("--note", default="")

    use = sub.add_parser("use", help="switch to a named account")
    use.add_argument("alias")
    add_restart_args(use, default_restart=True)

    auto = sub.add_parser("auto", help="switch to the first available account")
    add_restart_args(auto, default_restart=True)
    sub.add_parser("restart-desktop", help="restart Codex Desktop")
    prepare_add = sub.add_parser(
        "prepare-add",
        help="clear local auth without logging out, so a new account can be added safely",
    )
    add_restart_args(prepare_add, default_restart=True)
    sub.add_parser("sync-emails", help="rename saved accounts to their login emails")
    sub.add_parser("list", help="list accounts")
    sub.add_parser("current", help="show current matched account")

    mark = sub.add_parser("mark", help="set account quota status")
    mark.add_argument("alias")
    mark.add_argument("status", choices=["available", "unavailable", "unknown"])

    refresh = sub.add_parser("refresh", help="set next refresh date")
    refresh.add_argument("alias")
    refresh.add_argument("--next-refresh", required=True, help="YYYY-MM-DD")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pool = AccountPool(codex_home=args.codex_home)
    try:
        if args.command == "add":
            print(pool.add_account(args.alias, args.next_refresh, args.note))
        elif args.command == "use":
            print(pool.use_account(args.alias))
            if args.restart_desktop:
                print(restart_codex_desktop())
        elif args.command == "auto":
            ok, message = pool.auto_switch()
            print(message)
            if ok and args.restart_desktop:
                print(restart_codex_desktop())
            return 0 if ok else 2
        elif args.command == "restart-desktop":
            print(restart_codex_desktop())
        elif args.command == "prepare-add":
            print(pool.prepare_add())
            if args.restart_desktop:
                print(restart_codex_desktop())
        elif args.command == "sync-emails":
            print(pool.sync_emails())
        elif args.command == "list":
            print(pool.list_accounts())
        elif args.command == "current":
            print(pool.current())
        elif args.command == "mark":
            print(pool.mark(args.alias, args.status))
        elif args.command == "refresh":
            print(pool.refresh(args.alias, args.next_refresh))
        else:
            raise CodexSwitchError(f"unknown command: {args.command}")
        return 0
    except CodexSwitchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
