#!/usr/bin/env python3
"""Prepare Mealie for homelab deploys: local service admin, OIDC-ready, optional OpenAI."""

from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    import bcrypt
except ImportError:
    print("ERROR: bcrypt is required (pip install bcrypt)", file=sys.stderr)
    raise SystemExit(1)

DEFAULT_EMAIL = "changeme@example.com"
DEPRECATED_EMAIL = "disabled-default@mealie.local"
SEED_EMAILS = {DEFAULT_EMAIL.lower(), DEPRECATED_EMAIL.lower()}
SERVICE_ADMIN_FULL_NAME = "Homelab Admin"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


def get_group_and_household(
    conn: sqlite3.Connection, group_name: str, household_name: str
) -> tuple[str, str | None]:
    group = conn.execute(
        "SELECT id FROM groups WHERE name = ? ORDER BY created_at LIMIT 1",
        (group_name,),
    ).fetchone()
    if not group:
        group = conn.execute("SELECT id FROM groups ORDER BY created_at LIMIT 1").fetchone()
    if not group:
        raise RuntimeError("No groups in Mealie database — start Mealie once before bootstrap")

    group_id = group[0]
    household = conn.execute(
        """
        SELECT id FROM households
        WHERE name = ? AND group_id = ?
        ORDER BY created_at LIMIT 1
        """,
        (household_name, group_id),
    ).fetchone()
    if not household:
        household = conn.execute(
            "SELECT id FROM households WHERE group_id = ? ORDER BY created_at LIMIT 1",
            (group_id,),
        ).fetchone()
    return group_id, household[0] if household else None


def ensure_service_admin(
    conn: sqlite3.Connection,
    username: str,
    password: str,
    email: str,
    group_name: str,
    household_name: str,
) -> tuple[str, bool]:
    row = conn.execute(
        """
        SELECT id, password, auth_method, admin, email
        FROM users WHERE lower(username) = lower(?)
        """,
        (username,),
    ).fetchone()

    if row:
        user_id, hashed, auth_method, admin, current_email = row
        if auth_method != "MEALIE" or not admin:
            raise RuntimeError(
                f"User '{username}' exists but is not a local admin — choose another mealie.admin_username"
            )

        changed = False
        if not verify_password(password, hashed or ""):
            conn.execute(
                """
                UPDATE users
                SET password = ?, update_at = ?, tokens_valid_after = ?
                WHERE id = ?
                """,
                (hash_password(password), now(), now(), user_id),
            )
            changed = True
        if current_email != email:
            conn.execute(
                "UPDATE users SET email = ?, update_at = ? WHERE id = ?",
                (email, now(), user_id),
            )
            changed = True
        return ("updated-service-admin", True) if changed else ("skipped-service-admin", False)

    group_id, household_id = get_group_and_household(conn, group_name, household_name)
    user_id = uuid.uuid4().hex
    ts = now()
    conn.execute(
        """
        INSERT INTO users (
            id, username, email, full_name, password, admin, advanced, auth_method,
            group_id, household_id, cache_key, can_manage, can_invite, can_organize,
            can_manage_household, show_announcements, login_attemps, created_at, update_at
        ) VALUES (?, ?, ?, ?, ?, 1, 0, 'MEALIE', ?, ?, '1234', 1, 1, 1, 1, 1, 0, ?, ?)
        """,
        (
            user_id,
            username,
            email,
            SERVICE_ADMIN_FULL_NAME,
            hash_password(password),
            group_id,
            household_id,
            ts,
            ts,
        ),
    )
    return "created-service-admin", True


def remove_seed_users(conn: sqlite3.Connection) -> tuple[str, bool]:
    """Remove Mealie's seeded placeholder users once a service admin exists."""
    for email in sorted(SEED_EMAILS):
        row = conn.execute(
            "SELECT id FROM users WHERE lower(email) = ?",
            (email,),
        ).fetchone()
        if not row:
            continue
        conn.execute("DELETE FROM users WHERE id = ?", (row[0],))
        return "deleted-seed-users", True
    return "skipped-seed-users", False


def ensure_openai_provider(conn: sqlite3.Connection, api_key: str, model: str) -> tuple[str, bool]:
    if not api_key:
        return "skipped-openai", False

    group = conn.execute("SELECT id FROM groups ORDER BY created_at LIMIT 1").fetchone()
    if not group:
        return "skipped-openai", False
    group_id = group[0]

    settings = conn.execute(
        "SELECT id, default_provider_id FROM ai_provider_settings WHERE group_id = ?",
        (group_id,),
    ).fetchone()
    if not settings:
        settings_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO ai_provider_settings (id, group_id, created_at, update_at) VALUES (?, ?, ?, ?)",
            (settings_id, group_id, now(), now()),
        )
    else:
        settings_id, default_provider_id = settings[0], settings[1]
        if default_provider_id:
            existing = conn.execute(
                "SELECT id FROM ai_providers WHERE id = ? AND api_key = ?",
                (default_provider_id, api_key),
            ).fetchone()
            if existing:
                return "skipped-openai", False

    provider_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO ai_providers (
            id, settings_id, name, base_url, api_key, model, timeout, created_at, update_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            provider_id,
            settings_id,
            "OpenAI",
            "https://api.openai.com/v1",
            api_key,
            model,
            600,
            now(),
            now(),
        ),
    )
    conn.execute(
        """
        UPDATE ai_provider_settings
        SET default_provider_id = ?, image_provider_id = ?, update_at = ?
        WHERE id = ?
        """,
        (provider_id, provider_id, now(), settings_id),
    )
    return "configured-openai", True


def bootstrap(
    db_path: Path,
    username: str,
    password: str,
    email: str,
    group_name: str,
    household_name: str,
    api_key: str,
    model: str,
) -> list[str]:
    if not db_path.is_file():
        return []

    conn = sqlite3.connect(db_path)
    try:
        actions: list[str] = []

        admin_action, admin_changed = ensure_service_admin(
            conn, username, password, email, group_name, household_name
        )
        if admin_changed:
            actions.append(admin_action)

        if admin_action != "skipped-service-admin" or admin_changed:
            service_ready = True
        else:
            service_ready = conn.execute(
                """
                SELECT id FROM users
                WHERE lower(username) = lower(?) AND admin = 1 AND auth_method = 'MEALIE'
                """,
                (username,),
            ).fetchone() is not None

        if service_ready:
            seed_action, seed_changed = remove_seed_users(conn)
            if seed_changed:
                actions.append(seed_action)

        openai_action, openai_changed = ensure_openai_provider(conn, api_key, model)
        if openai_changed:
            actions.append(openai_action)

        if actions:
            conn.commit()
        return actions
    finally:
        conn.close()


def main() -> int:
    db_path = Path(os.environ.get("MEALIE_DB", "/data/mealie.db"))
    username = os.environ.get("MEALIE_ADMIN_USERNAME", "").strip()
    password = os.environ.get("MEALIE_ADMIN_PASSWORD", "")
    email = os.environ.get("MEALIE_ADMIN_EMAIL", "").strip()
    group_name = os.environ.get("MEALIE_DEFAULT_GROUP", "Home").strip() or "Home"
    household_name = os.environ.get("MEALIE_DEFAULT_HOUSEHOLD", "Family").strip() or "Family"
    api_key = os.environ.get("MEALIE_OPENAI_API_KEY", "").strip()
    model = os.environ.get("MEALIE_OPENAI_MODEL", "gpt-4o").strip() or "gpt-4o"

    if not username or not password:
        print("ERROR: MEALIE_ADMIN_USERNAME and MEALIE_ADMIN_PASSWORD are required", file=sys.stderr)
        return 1
    if len(password) < 8:
        print("ERROR: MEALIE_ADMIN_PASSWORD must be at least 8 characters", file=sys.stderr)
        return 1
    if not email:
        email = f"{username}@mealie.local"

    try:
        actions = bootstrap(db_path, username, password, email, group_name, household_name, api_key, model)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not actions:
        print("Mealie bootstrap: nothing to change", file=sys.stderr)
        return 0

    for action in actions:
        if action == "created-service-admin":
            print(f"created local service admin '{username}'", file=sys.stderr)
        elif action == "updated-service-admin":
            print(f"updated local service admin '{username}'", file=sys.stderr)
        elif action == "deleted-seed-users":
            print("removed Mealie seeded placeholder user(s)", file=sys.stderr)
        elif action == "configured-openai":
            print(f"configured group OpenAI provider ({model})", file=sys.stderr)

    print(f"mealie bootstrap: {', '.join(actions)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
