#!/usr/bin/env python
"""Friend-scale admin CLI for the Ink backend.

Runs with direct repository access (no HTTP layer), locally or inside the Fly VM:

    python -m scripts.admin find <email|id>
    python -m scripts.admin show <account_id>
    python -m scripts.admin mint-token <account_id>
    python -m scripts.admin suspend <account_id>
    python -m scripts.admin unsuspend <account_id>
    python -m scripts.admin reset <account_id>     # unbind the account's frames + clear its key
    python -m scripts.admin delete <account_id>     # cascade: frames -> unpaired, account removed

On Fly:  flyctl ssh console --app ink-art-frame -C "python -m scripts.admin find foo@example.com"

Tokens are stored only as hashes, so we can never read an existing one — `mint-token`
issues a NEW recovery token (and prints it once) for the user to paste into the app.
"""
from __future__ import annotations

import argparse
import sys

from backend import auth, artwork_repo, repositories


def _fmt_account(a) -> str:
    n = len(repositories.list_account_devices(a.id))
    flag = " [SUSPENDED]" if a.suspended else ""
    return f"{a.id}  email={a.email or '-'}  frames={n}  created={a.created_at}{flag}"


def cmd_find(args) -> int:
    accounts = repositories.list_accounts(args.query)
    if not accounts:
        print("no matching accounts")
        return 1
    for a in accounts:
        print(_fmt_account(a))
    return 0


def cmd_show(args) -> int:
    a = repositories.get_account(args.account_id)
    if a is None:
        print("account not found")
        return 1
    print("ACCOUNT  " + _fmt_account(a))
    for d in repositories.list_account_devices(a.id):
        name = d.name or "(unnamed)"
        print(f"\nFRAME {d.id}  '{name}'  status={d.status}  order={d.display_order}")
        print(f"  orientation={d.orientation} tz={d.tz} interests={d.interests or '-'}")
        print(f"  last_seen={d.last_seen} battery={d.battery} rssi={d.wifi_rssi} fw={d.fw_version}")
        recent = artwork_repo.list_archive(d.id, limit=args.limit)
        if recent:
            print(f"  recent creations ({len(recent)}):")
            for aw in recent:
                visual = (aw.event_visual or "").strip() or "(abstract)"
                print(f"    {aw.date}: {aw.event_caption or aw.event_text_en or '-'}")
                print(f"        visual: {visual}")
                if aw.image_prompt:
                    print(f"        prompt: {aw.image_prompt[:160].replace(chr(10), ' ')}…")
    return 0


def cmd_mint_token(args) -> int:
    if repositories.get_account(args.account_id) is None:
        print("account not found")
        return 1
    token = auth.new_account_token()
    repositories.set_account_token_hash(args.account_id, auth.hash_token(token))
    print("New recovery token (give this to the user; the old one stops working):")
    print(token)
    return 0


def cmd_suspend(args) -> int:
    if repositories.get_account(args.account_id) is None:
        print("account not found")
        return 1
    repositories.set_account_suspended(args.account_id, args.value)
    print(f"account {args.account_id} suspended={args.value}")
    return 0


def cmd_reset(args) -> int:
    a = repositories.get_account(args.account_id)
    if a is None:
        print("account not found")
        return 1
    frames = repositories.list_account_devices(a.id)
    for d in frames:
        repositories.unbind_device(d.id)
    repositories.set_account_key(a.id, None)
    print(f"reset {a.id}: unbound {len(frames)} frame(s), cleared own key")
    return 0


def cmd_delete(args) -> int:
    a = repositories.get_account(args.account_id)
    if a is None:
        print("account not found")
        return 1
    if not args.yes:
        print(f"refusing to delete {a.id} without --yes")
        return 1
    repositories.delete_account(a.id)
    print(f"deleted account {a.id} (its frames are now unpaired + re-pairable)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="admin", description="Ink backend admin CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("find"); p.add_argument("query"); p.set_defaults(fn=cmd_find)
    p = sub.add_parser("show"); p.add_argument("account_id"); p.add_argument("--limit", type=int, default=5); p.set_defaults(fn=cmd_show)
    p = sub.add_parser("mint-token"); p.add_argument("account_id"); p.set_defaults(fn=cmd_mint_token)
    p = sub.add_parser("suspend"); p.add_argument("account_id"); p.set_defaults(fn=cmd_suspend, value=True)
    p = sub.add_parser("unsuspend"); p.add_argument("account_id"); p.set_defaults(fn=cmd_suspend, value=False)
    p = sub.add_parser("reset"); p.add_argument("account_id"); p.set_defaults(fn=cmd_reset)
    p = sub.add_parser("delete"); p.add_argument("account_id"); p.add_argument("--yes", action="store_true"); p.set_defaults(fn=cmd_delete)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
