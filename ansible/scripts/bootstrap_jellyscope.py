#!/usr/bin/env python3
"""Bootstrap Jellyscope admin account and Jellyfin connection settings."""

from __future__ import annotations

import asyncio
import os
import sys


def verify_jellyfin_connection(url: str, api_key: str) -> None:
    from jellyscope.jellyfin import QUICK_TIMEOUT, JellyfinClient, JellyfinError

    async def _check() -> str:
        async with JellyfinClient(url, api_key, QUICK_TIMEOUT) as client:
            info = await client.system_info()
        return f"{info.get('ServerName', '?')} (Jellyfin {info.get('Version', '?')})"

    try:
        server = asyncio.run(_check())
    except JellyfinError as exc:
        print(f"ERROR: Jellyfin connection test failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"jellyfin connection verified: {server}")


def main() -> int:
    username = os.environ.get("JELLYSCOPE_ADMIN_USERNAME", "").strip()
    password = os.environ.get("JELLYSCOPE_ADMIN_PASSWORD", "")
    jellyfin_url = os.environ.get("JELLYFIN_URL", "http://jellyfin:8096").strip().rstrip("/")
    jellyfin_api_key = os.environ.get("JELLYSCOPE_JELLYFIN_API_KEY", "").strip()
    ui_language = os.environ.get("JELLYSCOPE_UI_LANGUAGE", "en").strip().lower() or "en"
    log_language = os.environ.get("JELLYSCOPE_LOG_LANGUAGE", ui_language).strip().lower() or ui_language
    if ui_language not in {"cs", "en"}:
        ui_language = "en"
    if log_language not in {"cs", "en"}:
        log_language = ui_language

    if not username or not password:
        print("ERROR: JELLYSCOPE_ADMIN_USERNAME and JELLYSCOPE_ADMIN_PASSWORD are required", file=sys.stderr)
        return 1
    if not jellyfin_api_key:
        print("ERROR: JELLYSCOPE_JELLYFIN_API_KEY is required", file=sys.stderr)
        return 1

    from jellyscope import accounts, db
    from jellyscope.config import BASE_DIR

    secret_from_env = os.environ.get("SECRET_KEY", "").strip()
    secret_file = BASE_DIR / "data" / "secret_key"
    if secret_from_env and secret_file.is_file():
        secret_file.unlink()
        print("removed stale data/secret_key (SECRET_KEY comes from .env)")

    db.init_db()
    db.set_setting("jellyfin_url", jellyfin_url)
    db.set_setting("jellyfin_api_key", jellyfin_api_key)
    db.set_setting("ui_language", ui_language)
    db.set_setting("log_language", log_language)
    db.forget_settings()

    account = accounts.get_by_name(username)
    if account is None:
        accounts.create(username, password, is_admin=True)
        print(f"created admin account '{username}'")
    else:
        accounts.set_password(account["id"], password)
        accounts.set_admin(account["id"], True)
        print(f"updated admin account '{username}'")

    if accounts.count() == 1:
        print("single admin account configured; /setup is disabled")
    else:
        print(f"{accounts.count()} accounts present; only admins can add more in Settings")

    url, key = db.jellyfin_connection()
    if not url or not key:
        print("ERROR: Jellyfin connection settings were not saved", file=sys.stderr)
        return 1

    verify_jellyfin_connection(url, key)
    print("jellyfin connection configured")
    print(f"ui language set to '{ui_language}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
