#!/usr/bin/env python3
"""Bootstrap Audiobookshelf root user, Authelia OIDC settings, and libraries."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


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


def trigger_library_scan(base: str, library_id: str, token: str) -> bool:
    status, _payload = api_request(
        "POST", f"{base}/api/libraries/{library_id}/scan", token=token
    )
    return status == 200


def folder_paths(library: dict) -> set[str]:
    paths: set[str] = set()
    for folder in library.get("folders", []):
        path = folder.get("fullPath") or folder.get("path")
        if path:
            paths.add(path)
    return paths


def library_settings(spec: dict) -> dict:
    """Library settings from homelab.yaml (coverAspectRatio 1 = square, disableWatcher false = watch)."""
    return dict(spec.get("settings") or {})


def library_settings_delta(current: dict, desired: dict) -> dict:
    return {key: value for key, value in desired.items() if current.get(key) != value}


def library_update_patch(lib: dict, spec: dict) -> dict:
    patch: dict = {}
    provider = spec.get("provider")
    if provider and lib.get("provider") != provider:
        patch["provider"] = provider
    settings_delta = library_settings_delta(lib.get("settings") or {}, library_settings(spec))
    if settings_delta:
        patch["settings"] = settings_delta
    return patch


def main() -> int:
    base = os.environ.get("ABS_URL", "http://audiobookshelf:80").rstrip("/")
    domain = os.environ.get("DOMAIN", "").strip()
    oidc_secret = os.environ.get("OIDC_CLIENT_SECRET", "")
    root_user = os.environ.get("AUDIOBOOKSHELF_ROOT_USERNAME", "admin").strip()
    root_pass = os.environ.get("AUDIOBOOKSHELF_ROOT_PASSWORD", "")
    libraries_raw = os.environ.get("AUDIOBOOKSHELF_LIBRARIES", "[]")
    auto_register = True
    button_text = "Login with Authelia"

    if not domain:
        print("ERROR: DOMAIN is required", file=sys.stderr)
        return 1
    if not oidc_secret:
        print("ERROR: OIDC_CLIENT_SECRET is required", file=sys.stderr)
        return 1
    if not root_user or not root_pass:
        print(
            "ERROR: AUDIOBOOKSHELF_ROOT_USERNAME and AUDIOBOOKSHELF_ROOT_PASSWORD are required",
            file=sys.stderr,
        )
        return 1

    try:
        libraries: list[dict] = json.loads(libraries_raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid AUDIOBOOKSHELF_LIBRARIES JSON: {exc}", file=sys.stderr)
        return 1

    status, payload = api_request("GET", f"{base}/status")
    if status != 200:
        print(f"ERROR: /status returned {status}: {payload}", file=sys.stderr)
        return 1

    if not payload.get("isInit"):
        status, init_payload = api_request(
            "POST",
            f"{base}/init",
            {"newRoot": {"username": root_user, "password": root_pass}},
        )
        if status != 200:
            print(f"ERROR: /init failed ({status}): {init_payload}", file=sys.stderr)
            return 1
        print(f"initialized server with root user '{root_user}'")
    else:
        print("server already initialized")

    status, login = api_request(
        "POST",
        f"{base}/login",
        {"username": root_user, "password": root_pass},
    )
    if status != 200:
        print(f"ERROR: login as '{root_user}' failed ({status}): {login}", file=sys.stderr)
        return 1

    token = login["user"]["token"]
    user_type = login.get("user", {}).get("type", "?")
    print(f"logged in as '{root_user}' (type={user_type})")

    auth_domain = f"https://auth.{domain}"
    desired_oidc = {
        "authActiveAuthMethods": ["local", "openid"],
        "authOpenIDIssuerURL": auth_domain,
        "authOpenIDAuthorizationURL": f"{auth_domain}/api/oidc/authorization",
        "authOpenIDTokenURL": f"{auth_domain}/api/oidc/token",
        "authOpenIDUserInfoURL": f"{auth_domain}/api/oidc/userinfo",
        "authOpenIDJwksURL": f"{auth_domain}/jwks.json",
        "authOpenIDClientID": "audiobookshelf",
        "authOpenIDClientSecret": oidc_secret,
        "authOpenIDTokenSigningAlgorithm": "RS256",
        "authOpenIDButtonText": button_text,
        "authOpenIDMatchExistingBy": "username",
        "authOpenIDAutoLaunch": False,
        "authOpenIDAutoRegister": auto_register,
        "authOpenIDMobileRedirectURIs": ["audiobookshelf://oauth"],
        "authOpenIDSubfolderForRedirectURLs": "",
        "authOpenIDLogoutURL": None,
        "authOpenIDGroupClaim": "groups",
    }

    status, current_auth = api_request("GET", f"{base}/api/auth-settings", token=token)
    if status != 200:
        print(f"ERROR: GET /api/auth-settings failed ({status}): {current_auth}", file=sys.stderr)
        return 1

    oidc_delta = {
        key: value for key, value in desired_oidc.items() if current_auth.get(key) != value
    }
    if oidc_delta:
        status, result = api_request(
            "PATCH", f"{base}/api/auth-settings", oidc_delta, token=token
        )
        if status != 200:
            print(f"ERROR: OIDC settings update failed ({status}): {result}", file=sys.stderr)
            return 1
        active_methods = (result.get("serverSettings") or {}).get("authActiveAuthMethods", [])
        if "openid" not in active_methods:
            print(
                f"ERROR: openid auth not active after update ({status}): {result}",
                file=sys.stderr,
            )
            return 1
        changed_keys = ", ".join(sorted(k for k in oidc_delta if k != "authOpenIDClientSecret"))
        if "authOpenIDClientSecret" in oidc_delta:
            changed_keys = f"{changed_keys}, authOpenIDClientSecret" if changed_keys else "authOpenIDClientSecret"
        print(f"updated OIDC settings ({changed_keys or 'secret only'})")
    else:
        print("OIDC settings already match")

    desired_server = {
        "storeCoverWithItem": True,
        "storeMetadataWithItem": True,
    }
    current_server = login.get("serverSettings") or {}
    server_delta = {
        key: value for key, value in desired_server.items() if current_server.get(key) != value
    }
    if server_delta:
        status, result = api_request("PATCH", f"{base}/api/settings", server_delta, token=token)
        if status != 200 or "serverSettings" not in result:
            print(f"ERROR: server settings update failed ({status}): {result}", file=sys.stderr)
            return 1
        print(f"updated server settings ({', '.join(sorted(server_delta))})")
    else:
        print("server settings already match")

    status, lib_resp = api_request("GET", f"{base}/api/libraries", token=token)
    if status != 200:
        print(f"ERROR: GET /api/libraries failed ({status}): {lib_resp}", file=sys.stderr)
        return 1

    existing_by_name = {lib["name"]: lib for lib in lib_resp.get("libraries", [])}

    for spec in libraries:
        name = spec.get("name", "").strip()
        folders = spec.get("folders") or []
        media_type = spec.get("mediaType", "book")
        icon = spec.get("icon", "audiobookshelf" if media_type == "book" else "podcast")
        provider = spec.get("provider")
        settings = library_settings(spec)

        if not name:
            print("WARNING: library entry missing name — skipping", file=sys.stderr)
            continue
        if not folders:
            print(f"WARNING: library '{name}' has no folders — skipping", file=sys.stderr)
            continue

        if name not in existing_by_name:
            body: dict = {
                "name": name,
                "folders": [{"fullPath": path} for path in folders],
                "mediaType": media_type,
                "icon": icon,
            }
            if provider:
                body["provider"] = provider
            if settings:
                body["settings"] = settings
            status, created = api_request("POST", f"{base}/api/libraries", body, token=token)
            if status != 200:
                print(f"ERROR: create library '{name}' failed ({status}): {created}", file=sys.stderr)
                return 1
            print(f"created library '{name}' with {len(folders)} folder(s)")
            library_id = created.get("id")
            if library_id and trigger_library_scan(base, library_id, token):
                print(f"triggered scan for library '{name}'")
            existing_by_name[name] = created
            continue

        lib = existing_by_name[name]
        patch = library_update_patch(lib, spec)
        if patch:
            status, updated = api_request(
                "PATCH",
                f"{base}/api/libraries/{lib['id']}",
                patch,
                token=token,
            )
            if status != 200:
                print(
                    f"ERROR: update library '{name}' failed ({status}): {updated}",
                    file=sys.stderr,
                )
                return 1
            parts = []
            if "provider" in patch:
                parts.append(f"provider={patch['provider']}")
            if "settings" in patch:
                parts.append(
                    "settings: "
                    + ", ".join(f"{k}={v!r}" for k, v in sorted(patch["settings"].items()))
                )
            print(f"updated library '{name}' ({'; '.join(parts)})")
            lib = updated if isinstance(updated, dict) and updated.get("id") else lib
            existing_by_name[name] = lib

        existing_paths = folder_paths(lib)
        new_paths = [path for path in folders if path not in existing_paths]
        if new_paths:
            status, updated = api_request(
                "PATCH",
                f"{base}/api/libraries/{lib['id']}",
                {"folders": [{"fullPath": path} for path in new_paths]},
                token=token,
            )
            if status != 200:
                print(
                    f"ERROR: update library '{name}' folders failed ({status}): {updated}",
                    file=sys.stderr,
                )
                return 1
            print(f"added {len(new_paths)} folder(s) to library '{name}'")
            if trigger_library_scan(base, lib["id"], token):
                print(f"triggered scan for library '{name}'")
        else:
            print(f"library '{name}' folders already present")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
