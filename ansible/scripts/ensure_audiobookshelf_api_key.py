#!/usr/bin/env python3
"""Ensure a named Audiobookshelf API key exists and print its token."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _parse_json(raw: bytes) -> dict:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw.decode(errors="replace")}
    return payload if isinstance(payload, dict) else {"data": payload}


def api_request(
    method: str,
    url: str,
    body: dict | None = None,
    token: str | None = None,
) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, _parse_json(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _parse_json(exc.read())


def validate_key(base: str, token: str) -> bool:
    status, _payload = api_request("GET", f"{base}/api/libraries", token=token)
    return status == 200


def login(base: str, username: str, password: str) -> dict:
    status, payload = api_request(
        "POST",
        f"{base}/login",
        {"username": username, "password": password},
    )
    if status != 200:
        raise RuntimeError(f"login failed ({status}): {payload}")
    user = payload.get("user") or {}
    token = user.get("token")
    user_id = user.get("id")
    if not token or not user_id:
        raise RuntimeError(f"login response missing user token/id: {payload}")
    return {"token": token, "user_id": user_id}


def find_key_by_name(keys: list[dict], name: str) -> dict | None:
    for item in keys:
        if (item.get("name") or "").lower() == name.lower():
            return item
    return None


def ensure_key(
    base: str,
    username: str,
    password: str,
    app_name: str,
    key_file: Path,
) -> tuple[str, bool]:
    stored = key_file.read_text(encoding="utf-8").strip() if key_file.is_file() else ""
    if stored and validate_key(base, stored):
        return stored, False

    session = login(base, username, password)
    admin_token = session["token"]
    user_id = session["user_id"]

    status, listed = api_request("GET", f"{base}/api/api-keys", token=admin_token)
    if status != 200:
        raise RuntimeError(f"GET /api/api-keys failed ({status}): {listed}")

    existing = find_key_by_name(listed.get("apiKeys", []), app_name)
    if existing:
        key_id = existing.get("id")
        if key_id:
            status, _deleted = api_request(
                "DELETE",
                f"{base}/api/api-keys/{key_id}",
                token=admin_token,
            )
            if status != 200:
                raise RuntimeError(
                    f"DELETE /api/api-keys/{key_id} failed ({status}): {_deleted}"
                )

    status, created = api_request(
        "POST",
        f"{base}/api/api-keys",
        {"name": app_name, "userId": user_id, "isActive": True},
        token=admin_token,
    )
    if status != 200:
        raise RuntimeError(f"POST /api/api-keys failed ({status}): {created}")

    api_key = (created.get("apiKey") or {}).get("apiKey")
    if not api_key:
        raise RuntimeError(f"create response missing apiKey token: {created}")
    if not validate_key(base, api_key):
        raise RuntimeError(f"created API key '{app_name}' failed validation against {base}")

    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(f"{api_key}\n", encoding="utf-8")
    return api_key, True


def main() -> int:
    base = os.environ.get("ABS_URL", "http://audiobookshelf:13378").rstrip("/")
    username = os.environ.get("AUDIOBOOKSHELF_ROOT_USERNAME", "admin").strip()
    password = os.environ.get("AUDIOBOOKSHELF_ROOT_PASSWORD", "")
    app_name = os.environ.get("API_KEY_NAME", "homepage").strip()
    key_file = Path(os.environ.get("API_KEY_FILE", "/data/homepage_api_key"))

    if not username or not password:
        print(
            "ERROR: AUDIOBOOKSHELF_ROOT_USERNAME and AUDIOBOOKSHELF_ROOT_PASSWORD are required",
            file=sys.stderr,
        )
        return 1
    if not app_name:
        print("ERROR: API_KEY_NAME is required", file=sys.stderr)
        return 1

    status, payload = api_request("GET", f"{base}/status")
    if status != 200:
        print(f"ERROR: Audiobookshelf not reachable at {base} ({status}): {payload}", file=sys.stderr)
        return 1
    if not payload.get("isInit"):
        print(
            f"ERROR: Audiobookshelf at {base} is not initialized — run deploy audiobookshelf first",
            file=sys.stderr,
        )
        return 1

    try:
        token, created = ensure_key(base, username, password, app_name, key_file)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if created:
        print(f"created Audiobookshelf API key '{app_name}'", file=sys.stderr)
    else:
        print(f"using existing Audiobookshelf API key '{app_name}'", file=sys.stderr)

    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
