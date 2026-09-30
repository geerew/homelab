#!/usr/bin/env python3
"""Install Jellyfin plugins from configured repositories."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

CLIENT_AUTH_HEADER = (
    'MediaBrowser Client="homelab-bootstrap", Device="homelab", '
    'DeviceId="homelab-bootstrap-plugins", Version="1.0.0"'
)


def log(msg: str) -> None:
    print(f"jellyfin plugins: {msg}", file=sys.stderr)


def load_json_env(name: str) -> Any:
    raw = os.environ.get(name, "")
    if not raw:
        raise RuntimeError(f"{name} is required")
    return json.loads(raw)


def api_request(
    method: str,
    url: str,
    body: dict | list | None = None,
    token: str | None = None,
    client_auth: bool = False,
    timeout: int = 120,
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


def plugin_dir_name(name: str, version: str) -> str:
    return f"{name}_{version}"


def plugin_installed_on_disk(plugins_dir: str, name: str, version: str) -> bool:
    from pathlib import Path

    return (Path(plugins_dir) / plugin_dir_name(name, version)).is_dir()


def ensure_repositories(base: str, token: str, repositories: list[dict[str, str]]) -> bool:
    status, cfg = api_request("GET", f"{base}/System/Configuration", token=token)
    if status != 200 or not isinstance(cfg, dict):
        raise RuntimeError(f"failed to read server configuration ({status}): {cfg}")

    desired = [
        {"Name": repo["name"], "Url": repo["url"], "Enabled": True}
        for repo in repositories
    ]
    current = cfg.get("PluginRepositories") or []
    if current == desired:
        log("plugin repositories unchanged")
        return False

    cfg["PluginRepositories"] = desired
    status, result = api_request("POST", f"{base}/System/Configuration", body=cfg, token=token)
    if status != 204:
        raise RuntimeError(f"failed to update plugin repositories ({status}): {result}")
    log("updated plugin repositories")
    return True


def install_plugin(base: str, token: str, plugins_dir: str, spec: dict[str, str]) -> bool:
    name = spec["name"]
    version = spec["version"]
    guid = spec["guid"]
    repository = spec["repository"]

    if plugin_installed_on_disk(plugins_dir, name, version):
        log(f"plugin unchanged: {name} {version}")
        return False

    params = urllib.parse.urlencode(
        {
            "assemblyGuid": guid,
            "version": version,
            "repositoryUrl": repository,
        }
    )
    path = urllib.parse.quote(name, safe="")
    status, result = api_request(
        "POST",
        f"{base}/Packages/Installed/{path}?{params}",
        token=token,
        timeout=300,
    )
    if status != 204:
        raise RuntimeError(f"failed to install plugin '{name}' ({status}): {result}")

    for attempt in range(1, 61):
        if plugin_installed_on_disk(plugins_dir, name, version):
            log(f"installed plugin: {name} {version}")
            return True
        time.sleep(2)

    raise RuntimeError(f"plugin '{name}' install did not extract within timeout")


def main() -> int:
    base = os.environ.get("JELLYFIN_URL", "http://127.0.0.1:8096").rstrip("/")
    username = os.environ.get("JELLYFIN_ADMIN_USERNAME", "").strip()
    password = os.environ.get("JELLYFIN_ADMIN_PASSWORD", "")
    repositories = load_json_env("JELLYFIN_PLUGIN_REPOSITORIES")
    plugins = load_json_env("JELLYFIN_PLUGINS")
    plugins_dir = os.environ.get("JELLYFIN_PLUGINS_DIR", "").strip()

    if not username or not password:
        raise RuntimeError("JELLYFIN_ADMIN_USERNAME and JELLYFIN_ADMIN_PASSWORD are required")
    if not plugins_dir:
        raise RuntimeError("JELLYFIN_PLUGINS_DIR is required")

    token = authenticate(base, username, password)

    changed = ensure_repositories(base, token, repositories)
    for spec in plugins:
        changed |= install_plugin(base, token, plugins_dir, spec)

    if not changed:
        log("nothing to change")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
