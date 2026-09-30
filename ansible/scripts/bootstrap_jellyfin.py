#!/usr/bin/env python3
"""Bootstrap Jellyfin: startup wizard, admin user, and libraries from homelab.yaml."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Jellyfin 12 rejects AuthenticateByName without a client Authorization header.
CLIENT_AUTH_HEADER = (
    'MediaBrowser Client="homelab-bootstrap", Device="homelab", '
    'DeviceId="homelab-bootstrap-1", Version="1.0.0"'
)


def log(msg: str) -> None:
    print(f"jellyfin bootstrap: {msg}", file=sys.stderr)


def load_json_env(name: str, default: Any) -> Any:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    return json.loads(raw)


def api_request(
    method: str,
    url: str,
    body: dict | list | None = None,
    token: str | None = None,
    client_auth: bool = False,
    timeout: int = 60,
) -> tuple[int, Any]:
    headers: dict[str, str] = {}
    data: bytes | None = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if token:
        headers["Authorization"] = f'MediaBrowser Token="{token}"'
    elif client_auth:
        headers["Authorization"] = CLIENT_AUTH_HEADER

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            if not raw:
                return resp.status, None
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload: Any = json.loads(raw) if raw else raw
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload


def wait_for_api(base: str, retries: int = 60, delay: float = 5.0) -> None:
    for attempt in range(1, retries + 1):
        status, _ = api_request("GET", f"{base}/System/Info/Public")
        if status == 200:
            return
        log(f"waiting for Jellyfin API ({attempt}/{retries})")
        time.sleep(delay)
    raise RuntimeError(f"Jellyfin API not ready at {base}/System/Info/Public")


def startup_complete(base: str) -> bool:
    status, info = api_request("GET", f"{base}/System/Info/Public")
    if status != 200 or not isinstance(info, dict):
        raise RuntimeError(f"failed to read public system info ({status}): {info}")
    return bool(info.get("StartupWizardCompleted"))


def complete_startup_wizard(base: str, username: str, password: str) -> bool:
    if startup_complete(base):
        log("startup wizard already completed")
        return False

    changed = False

    # Jellyfin 12 creates the placeholder first user during InitializeAsync.
    status, result = api_request("GET", f"{base}/Startup/FirstUser", client_auth=True)
    if status != 200:
        raise RuntimeError(f"failed to initialize first user ({status}): {result}")

    server_name = os.environ.get("JELLYFIN_SERVER_NAME", "").strip()

    startup_configuration: dict[str, str] = {
        "UICulture": "en-GB",
        "MetadataCountryCode": "GB",
        "PreferredMetadataLanguage": "en",
    }
    if server_name:
        startup_configuration["ServerName"] = server_name

    for path, body in (
        ("/Startup/Configuration", startup_configuration),
        ("/Startup/User", {"Name": username, "Password": password}),
        (
            "/Startup/RemoteAccess",
            {"EnableRemoteAccess": True, "EnableAutomaticPortMapping": False},
        ),
    ):
        status, result = api_request("POST", f"{base}{path}", body=body, client_auth=True)
        if status not in (200, 204):
            raise RuntimeError(f"failed POST {path} ({status}): {result}")
        changed = True
        log(f"applied {path}")

    status, result = api_request("POST", f"{base}/Startup/Complete", client_auth=True)
    if status != 204:
        raise RuntimeError(f"failed to complete startup wizard ({status}): {result}")
    log("completed startup wizard")
    return changed


def authenticate(base: str, username: str, password: str) -> str:
    status, result = api_request(
        "POST",
        f"{base}/Users/AuthenticateByName",
        body={"Username": username, "Pw": password},
        client_auth=True,
    )
    if status != 200 or not isinstance(result, dict):
        raise RuntimeError(f"authentication failed ({status}): {result}")
    token = result.get("AccessToken", "").strip()
    if not token:
        raise RuntimeError("authentication succeeded but no AccessToken returned")
    return token


def library_paths(entry: dict[str, Any]) -> list[str]:
    paths = entry.get("paths") or []
    return [str(path) for path in paths if path]


def existing_libraries(base: str, token: str) -> dict[str, dict[str, Any]]:
    status, result = api_request("GET", f"{base}/Library/VirtualFolders", token=token)
    if status != 200 or not isinstance(result, list):
        raise RuntimeError(f"failed to list libraries ({status}): {result}")

    by_name: dict[str, dict[str, Any]] = {}
    for item in result:
        name = item.get("Name") or item.get("name")
        if name:
            by_name[name] = item
    return by_name


def library_paths_match(existing: dict[str, Any], desired_paths: list[str]) -> bool:
    current: set[str] = set()
    for location in existing.get("Locations") or []:
        current.add(str(location))
    return current == set(desired_paths)


def ensure_library(base: str, token: str, spec: dict[str, Any]) -> bool:
    name = spec["name"]
    collection_type = spec.get("type") or spec.get("collection_type") or "mixed"
    paths = library_paths(spec)
    if not paths:
        raise RuntimeError(f"library '{name}' has no paths")

    libraries = existing_libraries(base, token)
    existing = libraries.get(name)
    if existing and library_paths_match(existing, paths):
        log(f"library unchanged: {name}")
        return False

    if existing:
        raise RuntimeError(
            f"library '{name}' exists with different paths — adjust manually or remove it first"
        )

    params: list[tuple[str, str]] = [
        ("name", name),
        ("collectionType", collection_type),
        ("refreshLibrary", "true"),
    ]
    params.extend(("paths", path) for path in paths)
    query = urllib.parse.urlencode(params)
    status, result = api_request(
        "POST",
        f"{base}/Library/VirtualFolders?{query}",
        body={},
        token=token,
    )
    if status not in (200, 204):
        raise RuntimeError(f"failed to create library '{name}' ({status}): {result}")
    log(f"created library: {name} ({collection_type}) -> {', '.join(paths)}")
    return True


def ensure_server_configuration(base: str, token: str, server_name: str) -> bool:
    status, cfg = api_request("GET", f"{base}/System/Configuration", token=token)
    if status != 200 or not isinstance(cfg, dict):
        raise RuntimeError(f"failed to read server configuration ({status}): {cfg}")

    status, info = api_request("GET", f"{base}/System/Info", token=token)
    if status != 200 or not isinstance(info, dict):
        raise RuntimeError(f"failed to read system info ({status}): {info}")

    desired = dict(cfg)
    path_fields = {
        "CachePath": info.get("CachePath") or "/cache",
        "MetadataPath": info.get("InternalMetadataPath") or "/config/metadata",
    }
    log_path = info.get("LogPath")
    if log_path:
        path_fields["LogPath"] = log_path

    for key, value in path_fields.items():
        if value:
            desired[key] = value

    if server_name:
        desired["ServerName"] = server_name
    if not desired.get("UICulture"):
        desired["UICulture"] = "en-GB"
    desired["DisplaySpecialsWithinSeasons"] = False

    unchanged = (
        cfg.get("ServerName") == desired.get("ServerName")
        and cfg.get("CachePath") == desired.get("CachePath")
        and cfg.get("MetadataPath") == desired.get("MetadataPath")
        and cfg.get("DisplaySpecialsWithinSeasons") is False
    )
    if unchanged:
        log("server configuration unchanged")
        return False

    status, result = api_request(
        "POST",
        f"{base}/System/Configuration",
        body=desired,
        token=token,
    )
    if status != 204:
        raise RuntimeError(f"failed to update server configuration ({status}): {result}")
    log(f"updated server configuration (ServerName={desired.get('ServerName', '')!r})")
    return True


def ensure_metadata_configuration(base: str, token: str) -> bool:
    status, cfg = api_request("GET", f"{base}/System/Configuration/Metadata", token=token)
    if status == 200 and isinstance(cfg, dict) and "UseFileCreationTimeForDateAdded" in cfg:
        log("metadata configuration unchanged")
        return False

    body = {"UseFileCreationTimeForDateAdded": True}
    status, result = api_request(
        "POST",
        f"{base}/System/Configuration/metadata",
        body=body,
        token=token,
    )
    if status != 204:
        raise RuntimeError(f"failed to update metadata configuration ({status}): {result}")
    log("initialized metadata configuration")
    return True


def main() -> int:
    base = os.environ.get("JELLYFIN_URL", "http://127.0.0.1:8096").rstrip("/")
    username = os.environ.get("JELLYFIN_ADMIN_USERNAME", "").strip()
    password = os.environ.get("JELLYFIN_ADMIN_PASSWORD", "")
    server_name = os.environ.get("JELLYFIN_SERVER_NAME", "").strip()
    libraries = load_json_env("JELLYFIN_LIBRARIES", [])

    if not username or not password:
        raise RuntimeError("JELLYFIN_ADMIN_USERNAME and JELLYFIN_ADMIN_PASSWORD are required")
    if not libraries:
        raise RuntimeError("JELLYFIN_LIBRARIES must contain at least one library")

    wait_for_api(base)

    changed = complete_startup_wizard(base, username, password)
    token = authenticate(base, username, password)

    changed |= ensure_server_configuration(base, token, server_name)
    changed |= ensure_metadata_configuration(base, token)

    for spec in libraries:
        changed |= ensure_library(base, token, spec)

    if not changed:
        log("nothing to change")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
