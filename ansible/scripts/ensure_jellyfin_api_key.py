#!/usr/bin/env python3
"""Ensure a named Jellyfin API key exists and print its token."""

from __future__ import annotations

import argparse
import json
import secrets
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def read_key_from_db(db_path: str, app_name: str) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT AccessToken FROM ApiKeys WHERE Name = ? COLLATE NOCASE",
            (app_name,),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def validate_key(base_url: str, token: str) -> bool:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/System/Info/Public",
        headers={"Authorization": f'MediaBrowser Token="{token}"'},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def jellyfin_timestamp() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S") + f".{dt.microsecond:07d}"


def list_keys_via_api(base_url: str, admin_token: str) -> list[dict]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/Auth/Keys",
        headers={"Authorization": f'MediaBrowser Token="{admin_token}"'},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode())
    return payload.get("Items", [])


def find_key_in_api_list(items: list[dict], app_name: str) -> str | None:
    for item in items:
        if item.get("AppName", "").lower() == app_name.lower():
            token = item.get("AccessToken", "").strip()
            if token:
                return token
    return None


def create_key_via_api(base_url: str, admin_token: str, app_name: str) -> str:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/Auth/Keys?{urllib.parse.urlencode({'app': app_name})}",
        method="POST",
        headers={"Authorization": f'MediaBrowser Token="{admin_token}"'},
    )
    with urllib.request.urlopen(request, timeout=15):
        pass

    token = find_key_in_api_list(list_keys_via_api(base_url, admin_token), app_name)
    if not token:
        raise RuntimeError(f"Created Jellyfin API key '{app_name}' via API but could not read it back")
    return token


def delete_key_via_api(base_url: str, admin_token: str, token: str) -> None:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/Auth/Keys/{token}",
        method="DELETE",
        headers={"Authorization": f'MediaBrowser Token="{admin_token}"'},
    )
    try:
        with urllib.request.urlopen(request, timeout=15):
            pass
    except urllib.error.HTTPError as exc:
        if exc.code not in {204, 404}:
            raise


def find_bootstrap_token(db_path: str, base_url: str, app_name: str) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT Name, AccessToken FROM ApiKeys").fetchall()
    finally:
        conn.close()

    for name, token in rows:
        if name.lower() == app_name.lower():
            continue
        if token and validate_key(base_url, token):
            return token
    return None


def create_key_in_db(db_path: str, app_name: str, token: str | None = None) -> str:
    token = token or secrets.token_hex(16)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "DELETE FROM ApiKeys WHERE Name = ? COLLATE NOCASE",
            (app_name,),
        )
        conn.execute(
            "INSERT INTO ApiKeys (DateCreated, DateLastActivity, Name, AccessToken) "
            "VALUES (?, ?, ?, ?)",
            (jellyfin_timestamp(), "0001-01-01 00:00:00", app_name, token),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def ensure_key(db_path: str, base_url: str, app_name: str) -> tuple[str, bool, str]:
    """Return (token, created, method). method is reused|api|database."""
    existing = read_key_from_db(db_path, app_name)
    if existing and validate_key(base_url, existing):
        return existing, False, "reused"

    bootstrap = find_bootstrap_token(db_path, base_url, app_name)
    if bootstrap:
        if existing:
            delete_key_via_api(base_url, bootstrap, existing)
        try:
            token = create_key_via_api(base_url, bootstrap, app_name)
            if validate_key(base_url, token):
                create_key_in_db(db_path, app_name, token)
                return token, True, "api"
        except (urllib.error.URLError, TimeoutError, RuntimeError, urllib.error.HTTPError) as exc:
            print(
                f"WARN: Jellyfin API key creation failed ({exc}); falling back to database insert",
                file=sys.stderr,
            )

    token = create_key_in_db(db_path, app_name)
    if not validate_key(base_url, token):
        print(
            f"ERROR: created Jellyfin API key '{app_name}' in database but validation failed "
            f"(is Jellyfin running at {base_url}?).",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return token, True, "database"


def verify_key_listed(base_url: str, token: str, app_name: str) -> bool:
    if not validate_key(base_url, token):
        return False
    try:
        items = list_keys_via_api(base_url, token)
    except (urllib.error.URLError, TimeoutError, urllib.error.HTTPError):
        return False
    return find_key_in_api_list(items, app_name) is not None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8096")
    parser.add_argument("--app-name", default="jellyscope")
    parser.add_argument("--jellyfin-db", required=True)
    args = parser.parse_args()

    token, created, method = ensure_key(args.jellyfin_db, args.url, args.app_name)

    if created:
        print(f"created Jellyfin API key '{args.app_name}' via {method}", file=sys.stderr)
    else:
        print(f"using existing Jellyfin API key '{args.app_name}'", file=sys.stderr)

    if not verify_key_listed(args.url, token, args.app_name):
        print(
            f"ERROR: Jellyfin API key '{args.app_name}' works but is not listed under Dashboard → API Keys. "
            "Restart Jellyfin and re-run the playbook.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
