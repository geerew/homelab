#!/usr/bin/env python3
"""Ensure a Mealie long-lived API token exists for Homepage (owned by the service admin)."""

from __future__ import annotations

import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

try:
    import jwt
except ImportError:
    print("ERROR: PyJWT is required (pip install PyJWT)", file=sys.stderr)
    raise SystemExit(1)

ISS = "mealie"
ALGORITHM = "HS256"
DEFAULT_INTEGRATION_ID = "generic"


def read_secret(data_dir: Path) -> str:
    secret_path = data_dir / ".secret"
    if not secret_path.is_file():
        raise RuntimeError(f"Mealie secret not found at {secret_path} — start Mealie once")
    secret = secret_path.read_text(encoding="utf-8").strip()
    if not secret:
        raise RuntimeError("Mealie .secret file is empty")
    return secret


def find_admin_user(conn: sqlite3.Connection, service_username: str) -> tuple[str, str]:
    """Return (user_id, username) for the homelab service admin."""
    row = conn.execute(
        """
        SELECT id, username FROM users
        WHERE admin = 1 AND auth_method = 'MEALIE' AND lower(username) = lower(?)
        LIMIT 1
        """,
        (service_username,),
    ).fetchone()
    if row:
        return row[0], row[1]

    raise RuntimeError(
        f"Mealie service admin '{service_username}' not found — run deploy mealie first"
    )


def validate_token(base: str, token: str) -> bool:
    req = urllib.request.Request(
        f"{base.rstrip('/')}/api/users/self",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except urllib.error.HTTPError:
        return False
    except urllib.error.URLError:
        return False


def create_jwt(secret: str, user_id: str, name: str, integration_id: str) -> str:
    issued_at = datetime.now(UTC)
    expires = issued_at + timedelta(days=1825)
    payload = {
        "long_token": True,
        "id": user_id,
        "name": name,
        "integration_id": integration_id,
        "iss": ISS,
        "iat": issued_at,
        "exp": expires,
    }
    encoded = jwt.encode(payload, secret, algorithm=ALGORITHM)
    return encoded if isinstance(encoded, str) else encoded.decode()


def now_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def ensure_key(
    data_dir: Path,
    base_url: str,
    service_username: str,
    token_name: str,
    key_file: Path,
    integration_id: str = DEFAULT_INTEGRATION_ID,
) -> tuple[str, bool]:
    stored = key_file.read_text(encoding="utf-8").strip() if key_file.is_file() else ""
    if stored and validate_token(base_url, stored):
        return stored, False

    db_path = data_dir / "mealie.db"
    if not db_path.is_file():
        raise RuntimeError(f"Mealie database not found at {db_path}")

    secret = read_secret(data_dir)
    conn = sqlite3.connect(db_path)
    try:
        user_id, username = find_admin_user(conn, service_username)
        conn.execute(
            "DELETE FROM long_live_tokens WHERE name = ? AND user_id = ?",
            (token_name, user_id),
        )
        token = create_jwt(secret, user_id, token_name, integration_id)
        conn.execute(
            """
            INSERT INTO long_live_tokens (name, token, user_id, created_at, update_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token_name, token, user_id, now_str(), now_str()),
        )
        conn.commit()
    finally:
        conn.close()

    if not validate_token(base_url, token):
        raise RuntimeError(
            f"created Mealie API token for admin '{username}' but validation failed against {base_url}"
        )

    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(f"{token}\n", encoding="utf-8")
    return token, True


def main() -> int:
    base = os.environ.get("MEALIE_URL", "http://mealie:9000").rstrip("/")
    data_dir = Path(os.environ.get("MEALIE_DATA_DIR", "/data"))
    service_username = os.environ.get("MEALIE_ADMIN_USERNAME", "").strip()
    token_name = os.environ.get("API_TOKEN_NAME", "homepage").strip()
    key_file = Path(os.environ.get("API_KEY_FILE", "/data/homepage_api_key"))
    integration_id = os.environ.get("API_TOKEN_INTEGRATION_ID", DEFAULT_INTEGRATION_ID).strip()

    if not service_username:
        print("ERROR: MEALIE_ADMIN_USERNAME is required", file=sys.stderr)
        return 1
    if not token_name:
        print("ERROR: API_TOKEN_NAME is required", file=sys.stderr)
        return 1

    status_req = urllib.request.Request(f"{base}/api/app/about", method="GET")
    try:
        with urllib.request.urlopen(status_req, timeout=30) as resp:
            if resp.status != 200:
                print(f"ERROR: Mealie not reachable at {base} ({resp.status})", file=sys.stderr)
                return 1
    except urllib.error.URLError as exc:
        print(f"ERROR: Mealie not reachable at {base}: {exc}", file=sys.stderr)
        return 1

    try:
        token, created = ensure_key(
            data_dir, base, service_username, token_name, key_file, integration_id
        )
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if created:
        print(f"created Mealie API token '{token_name}' for service admin '{service_username}'", file=sys.stderr)
    else:
        print(f"using existing Mealie API token '{token_name}'", file=sys.stderr)

    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
