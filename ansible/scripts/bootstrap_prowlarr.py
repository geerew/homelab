#!/usr/bin/env python3
"""Configure Prowlarr auth and indexers from homelab.yaml (idempotent)."""

from __future__ import annotations

import copy
import json
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# Prowlarr is always behind Authelia at Traefik (Remote-User header).
AUTH_METHOD = "external"


def log(msg: str) -> None:
    print(f"prowlarr bootstrap: {msg}", file=sys.stderr)


def parse_json(raw: bytes) -> Any:
    if not raw:
        return None
    return json.loads(raw)


def api_request(
    method: str,
    url: str,
    api_key: str,
    body: dict | None = None,
) -> tuple[int, Any]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Api-Key": api_key,
    }
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, parse_json(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, parse_json(exc.read())


def read_api_key(config_xml: Path) -> str:
    if not config_xml.is_file():
        raise RuntimeError(f"Prowlarr config.xml not found: {config_xml}")
    root = ET.parse(config_xml).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"No ApiKey in {config_xml}")
    return api_key.strip()


def wait_for_api(base: str, api_key: str, retries: int = 24, delay: float = 5.0) -> None:
    for attempt in range(1, retries + 1):
        status, _payload = api_request("GET", f"{base}/ping", api_key)
        if status == 200:
            return
        log(f"waiting for Prowlarr API ({attempt}/{retries})")
        time.sleep(delay)
    raise RuntimeError(f"Prowlarr API not ready at {base}/ping")


def load_indexers() -> list[dict[str, Any]]:
    raw = os.environ.get("PROWLARR_INDEXERS", "[]")
    indexers = json.loads(raw)
    if not isinstance(indexers, list):
        raise RuntimeError("PROWLARR_INDEXERS must be a JSON array")
    return indexers


def apply_credentials(fields: list[dict[str, Any]], creds: dict[str, str]) -> None:
    mapping = {
        "username": creds.get("username", ""),
        "password": creds.get("password", ""),
        "alt2fatoken": creds.get("alt2fa_token", ""),
    }
    for field in fields:
        name = field.get("name")
        if name in mapping and mapping[name]:
            field["value"] = mapping[name]


def field_value(fields: list[dict[str, Any]], name: str) -> str:
    for field in fields:
        if field.get("name") == name:
            return str(field.get("value") or "")
    return ""


def indexer_needs_update(existing: dict[str, Any], desired: dict[str, Any]) -> bool:
    if existing.get("enable") != desired.get("enable", True):
        return True
    if existing.get("definitionName") != desired["definition"]:
        return True
    if not desired.get("private"):
        return False
    if field_value(existing.get("fields", []), "username") != desired.get("username", ""):
        return True
    desired_password = desired.get("password", "")
    if desired_password:
        existing_password = field_value(existing.get("fields", []), "password")
        if existing_password not in ("", "********") and existing_password != desired_password:
            return True
    alt2fa = desired.get("alt2fa_token")
    if alt2fa and field_value(existing.get("fields", []), "alt2fatoken") != alt2fa:
        return True
    return False


def default_app_profile_id(base: str, api_key: str) -> int:
    status, profiles = api_request("GET", f"{base}/api/v1/appprofile", api_key)
    if status != 200 or not isinstance(profiles, list) or not profiles:
        raise RuntimeError(f"failed to load app profiles ({status}): {profiles}")
    for profile in profiles:
        if profile.get("name") == "Standard" and profile.get("id"):
            return int(profile["id"])
    profile_id = profiles[0].get("id")
    if not profile_id:
        raise RuntimeError(f"no app profile id in Prowlarr profiles: {profiles}")
    return int(profile_id)


def build_indexer_payload(
    schema: dict[str, Any],
    desired: dict[str, Any],
    app_profile_id: int,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = copy.deepcopy(existing if existing else schema)
    payload["name"] = desired["name"]
    payload["enable"] = desired.get("enable", True)
    payload["definitionName"] = desired["definition"]
    if not payload.get("appProfileId"):
        payload["appProfileId"] = app_profile_id
    if desired.get("private"):
        apply_credentials(payload.get("fields", []), desired)
    elif existing:
        # Keep existing credential fields when not managing a private indexer.
        pass
    return payload


def ensure_auth(base: str, api_key: str) -> bool:
    status, host = api_request("GET", f"{base}/api/v1/config/host", api_key)
    if status != 200 or not isinstance(host, dict):
        raise RuntimeError(f"failed to read host config ({status}): {host}")

    if host.get("authenticationMethod") == AUTH_METHOD:
        return False

    desired = copy.deepcopy(host)
    desired["authenticationMethod"] = AUTH_METHOD
    status, result = api_request("PUT", f"{base}/api/v1/config/host", api_key, desired)
    if status >= 400:
        raise RuntimeError(f"failed to update host config ({status}): {result}")
    log(f"updated auth method to {AUTH_METHOD}")
    return True


def ensure_indexers(base: str, api_key: str, desired_indexers: list[dict[str, Any]]) -> bool:
    status, existing_list = api_request("GET", f"{base}/api/v1/indexer", api_key)
    if status != 200 or not isinstance(existing_list, list):
        raise RuntimeError(f"failed to list indexers ({status}): {existing_list}")

    status, schema_list = api_request("GET", f"{base}/api/v1/indexer/schema", api_key)
    if status != 200 or not isinstance(schema_list, list):
        raise RuntimeError(f"failed to load indexer schema ({status}): {schema_list}")

    schema_by_def = {item["definitionName"]: item for item in schema_list}
    existing_by_name = {item["name"]: item for item in existing_list}
    app_profile_id = default_app_profile_id(base, api_key)
    changed = False

    for desired in desired_indexers:
        name = desired["name"]
        definition = desired["definition"]
        if definition not in schema_by_def:
            raise RuntimeError(f"unknown indexer definition '{definition}' for '{name}'")

        if desired.get("private"):
            if not desired.get("username") or not desired.get("password"):
                raise RuntimeError(f"private indexer '{name}' requires username and password")

        existing = existing_by_name.get(name)
        if existing and not indexer_needs_update(existing, desired):
            log(f"indexer unchanged: {name}")
            continue

        payload = build_indexer_payload(
            schema_by_def[definition], desired, app_profile_id, existing
        )
        if existing:
            payload["id"] = existing["id"]
            status, result = api_request("PUT", f"{base}/api/v1/indexer/{existing['id']}", api_key, payload)
            action = "updated"
        else:
            payload.pop("id", None)
            status, result = api_request("POST", f"{base}/api/v1/indexer", api_key, payload)
            action = "created"

        if status >= 400:
            raise RuntimeError(f"failed to {action[:-1]} indexer '{name}' ({status}): {result}")
        log(f"{action} indexer: {name} ({definition})")
        changed = True

    return changed


def main() -> int:
    base = os.environ.get("PROWLARR_URL", "http://127.0.0.1:9696").rstrip("/")
    config_xml = Path(os.environ.get("PROWLARR_CONFIG_XML", "services/prowlarr/config/config.xml"))
    api_key = os.environ.get("PROWLARR_API_KEY", "").strip() or read_api_key(config_xml)
    indexers = load_indexers()

    if not indexers:
        log("no indexers configured — nothing to do")
        return 0

    wait_for_api(base, api_key)

    auth_changed = ensure_auth(base, api_key)
    indexers_changed = ensure_indexers(base, api_key, indexers)

    if not auth_changed and not indexers_changed:
        log("nothing to change")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
