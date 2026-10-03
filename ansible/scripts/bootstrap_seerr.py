#!/usr/bin/env python3
"""Configure Seerr: Jellyfin, Sonarr, Radarr, auth — idempotent bootstrap via Seerr API."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MEDIA_SERVER_JELLYFIN = 2
USER_TYPE_LOCAL = 3
PERMISSION_ADMIN = 2
PERMISSION_REQUEST = 32
PERMISSION_REQUEST_ADVANCED = 8192
DEFAULT_USER_PERMISSIONS = PERMISSION_REQUEST | PERMISSION_REQUEST_ADVANCED

SONARR_SERVER_SPECS: list[dict[str, Any]] = [
    {"name": "sonarr", "profile": "HD-720p", "isDefault": True},
]
RADARR_SERVER_SPECS: list[dict[str, Any]] = [
    {"name": "radarr", "profile": "HD-720p", "isDefault": True},
]
ALLOWED_QUALITY_PROFILES = ("HD-720p", "HD-1080p")


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def load_json_env(name: str, default: Any) -> Any:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    return json.loads(raw)


def read_api_key(settings_path: Path) -> str:
    for _ in range(60):
        if settings_path.is_file():
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            key = str(data.get("main", {}).get("apiKey", "")).strip()
            if key:
                return key
        time.sleep(2)
    raise SystemExit(f"Timed out waiting for Seerr API key in {settings_path}")


def api_request(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    data = None
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} {path} failed ({exc.code}): {detail}") from exc


AUTHELIA_LOGO = "https://www.authelia.com/images/branding/logo-cropped.png"


def configure_oidc_settings(
    settings_path: Path,
    *,
    issuer_url: str,
    client_id: str,
    client_secret: str,
    slug: str = "authelia",
    name: str = "Authelia",
    new_user_login: bool = True,
    local_login: bool = False,
    oidc_login: bool = True,
    media_server_login: bool = True,
) -> bool:
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    main = data.setdefault("main", {})
    desired_provider: dict[str, Any] = {
        "slug": slug,
        "name": name,
        "issuerUrl": issuer_url.rstrip("/"),
        "clientId": client_id,
        "clientSecret": client_secret,
        "logo": AUTHELIA_LOGO,
        "scopes": "openid profile email groups",
        "newUserLogin": new_user_login,
    }
    oidc = data.setdefault("oidc", {})
    providers: list[dict[str, Any]] = oidc.setdefault("providers", [])
    existing = next((provider for provider in providers if provider.get("slug") == slug), None)

    changed = False
    for key, value in (
        ("localLogin", local_login),
        ("oidcLogin", oidc_login),
        ("mediaServerLogin", media_server_login),
    ):
        if main.get(key) != value:
            main[key] = value
            changed = True

    if existing is None:
        providers[:] = [desired_provider]
        changed = True
    elif any(existing.get(k) != v for k, v in desired_provider.items()):
        existing.update(desired_provider)
        changed = True

    if changed:
        settings_path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        eprint("updated Seerr OIDC settings in settings.json")
    return changed


def ensure_local_admin(db_path: Path, email: str, password: str) -> bool:
    if not email or not password:
        return False
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute('SELECT COUNT(*) FROM "user"').fetchone()[0]
        if count:
            return False
        try:
            import bcrypt
        except ImportError as exc:
            raise SystemExit("bcrypt required to create first Seerr admin user") from exc
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")
        conn.execute(
            'INSERT INTO "user" (email, userType, permissions, avatar, password) VALUES (?, ?, ?, ?, ?)',
            (email.lower(), USER_TYPE_LOCAL, PERMISSION_ADMIN, "", hashed),
        )
        conn.commit()
        eprint(f"created local Seerr admin {email.lower()}")
        return True
    finally:
        conn.close()


def pick_named_profile(
    profiles: list[dict[str, Any]],
    preferred_names: tuple[str, ...],
    *,
    fallback_last: bool,
) -> str:
    for name in preferred_names:
        for profile in profiles:
            if profile.get("name") == name:
                return str(name)
    if fallback_last and profiles:
        return str(profiles[-1].get("name", ""))
    if profiles:
        return str(profiles[0].get("name", ""))
    return ""


def pick_profile(profiles: list[dict[str, Any]], preferred: str) -> dict[str, Any]:
    if preferred:
        for profile in profiles:
            if profile.get("name") == preferred:
                return profile
        raise SystemExit(f"Quality profile not found: {preferred!r}")
    if not profiles:
        raise SystemExit("No quality profiles returned from *arr")
    return profiles[0]


def pick_root_folder(folders: list[dict[str, Any]], preferred: str) -> dict[str, Any]:
    if preferred:
        for folder in folders:
            if folder.get("path") == preferred:
                return folder
        raise SystemExit(f"Root folder not found: {preferred!r}")
    if not folders:
        raise SystemExit("No root folders returned from *arr")
    return folders[-1]


def build_sonarr_payload(
    seerr_url: str,
    seerr_api_key: str,
    *,
    name: str,
    hostname: str,
    port: int,
    arr_api_key: str,
    profile_name: str,
    root_folder: str,
    is_default: bool,
) -> dict[str, Any]:
    test = api_request(
        seerr_url,
        seerr_api_key,
        "POST",
        "/api/v1/settings/sonarr/test",
        body={
            "name": name,
            "hostname": hostname,
            "port": port,
            "apiKey": arr_api_key,
            "useSsl": False,
            "baseUrl": "",
            "is4k": False,
        },
    )
    profile = pick_profile(test["profiles"], profile_name)
    folder = pick_root_folder(test["rootFolders"], root_folder)
    return {
        "name": name,
        "hostname": hostname,
        "port": port,
        "apiKey": arr_api_key,
        "useSsl": False,
        "baseUrl": test.get("urlBase") or "",
        "activeProfileId": profile["id"],
        "activeProfileName": profile["name"],
        "activeDirectory": folder["path"],
        "tags": [],
        "animeTags": [],
        "is4k": False,
        "isDefault": is_default,
        "enableSeasonFolders": False,
        "syncEnabled": True,
        "preventSearch": False,
        "tagRequests": False,
    }


def build_radarr_payload(
    seerr_url: str,
    seerr_api_key: str,
    *,
    name: str,
    hostname: str,
    port: int,
    arr_api_key: str,
    profile_name: str,
    root_folder: str,
    is_default: bool,
) -> dict[str, Any]:
    test = api_request(
        seerr_url,
        seerr_api_key,
        "POST",
        "/api/v1/settings/radarr/test",
        body={
            "name": name,
            "hostname": hostname,
            "port": port,
            "apiKey": arr_api_key,
            "useSsl": False,
            "baseUrl": "",
            "is4k": False,
            "minimumAvailability": "released",
        },
    )
    profile = pick_profile(test["profiles"], profile_name)
    folder = pick_root_folder(test["rootFolders"], root_folder)
    return {
        "name": name,
        "hostname": hostname,
        "port": port,
        "apiKey": arr_api_key,
        "useSsl": False,
        "baseUrl": test.get("urlBase") or "",
        "activeProfileId": profile["id"],
        "activeProfileName": profile["name"],
        "activeDirectory": folder["path"],
        "is4k": False,
        "minimumAvailability": "released",
        "tags": [],
        "isDefault": is_default,
        "syncEnabled": True,
        "preventSearch": False,
        "tagRequests": False,
    }


def sync_dvr_servers(
    seerr_url: str,
    api_key: str,
    *,
    arr_type: str,
    specs: list[dict[str, Any]],
    build_payload: Any,
    hostname: str,
    port: int,
    arr_api_key: str,
    root_folder: str,
) -> bool:
    path = f"/api/v1/settings/{arr_type}"
    existing = api_request(seerr_url, api_key, "GET", path)
    by_name = {server["name"]: server for server in existing}
    desired_names = {spec["name"] for spec in specs}
    changed = False

    for spec in specs:
        payload = build_payload(
            seerr_url,
            api_key,
            name=spec["name"],
            hostname=hostname,
            port=port,
            arr_api_key=arr_api_key,
            profile_name=spec["profile"],
            root_folder=root_folder,
            is_default=spec["isDefault"],
        )
        current = by_name.get(spec["name"])
        keys = (
            "hostname",
            "port",
            "apiKey",
            "activeProfileId",
            "activeProfileName",
            "activeDirectory",
            "isDefault",
            "syncEnabled",
            "name",
        )
        if current:
            if any(current.get(k) != payload.get(k) for k in keys):
                api_request(
                    seerr_url,
                    api_key,
                    "PUT",
                    f"{path}/{current['id']}",
                    body=payload,
                )
                changed = True
                eprint(f"updated Seerr {arr_type} server {spec['name']}")
        else:
            api_request(seerr_url, api_key, "POST", path, body=payload)
            changed = True
            eprint(f"added Seerr {arr_type} server {spec['name']}")

    for server in existing:
        if server["name"] not in desired_names:
            api_request(seerr_url, api_key, "DELETE", f"{path}/{server['id']}")
            changed = True
            eprint(f"removed stale Seerr {arr_type} server {server['name']}")

    return changed


def sync_default_permissions(seerr_url: str, api_key: str) -> bool:
    current_main = api_request(seerr_url, api_key, "GET", "/api/v1/settings/main")
    if current_main.get("defaultPermissions") == DEFAULT_USER_PERMISSIONS:
        return False
    api_request(
        seerr_url,
        api_key,
        "POST",
        "/api/v1/settings/main",
        body={"defaultPermissions": DEFAULT_USER_PERMISSIONS},
    )
    eprint("updated Seerr default permissions (request + advanced request)")
    return True


def grant_advanced_request_to_users(seerr_url: str, api_key: str) -> bool:
    users = api_request(seerr_url, api_key, "GET", "/api/v1/user", params={"take": "1000"})
    changed = False
    for user in users.get("results", []):
        perms = int(user.get("permissions", 0))
        if perms & PERMISSION_ADMIN:
            continue
        if perms & PERMISSION_REQUEST_ADVANCED:
            continue
        new_perms = perms | PERMISSION_REQUEST_ADVANCED
        api_request(
            seerr_url,
            api_key,
            "PUT",
            f"/api/v1/user/{user['id']}",
            body={"permissions": new_perms},
        )
        changed = True
        label = user.get("displayName") or user.get("email") or user["id"]
        eprint(f"granted advanced request permission to {label}")
    return changed


def arr_api_request(base_url: str, arr_api_key: str, method: str, path: str) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    req = urllib.request.Request(
        url,
        headers={"X-Api-Key": arr_api_key, "Accept": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} {path} failed ({exc.code}): {detail}") from exc


def prune_arr_quality_profiles(base_url: str, arr_api_key: str, arr_type: str) -> bool:
    profiles = arr_api_request(base_url, arr_api_key, "GET", "/api/v3/qualityprofile")
    if arr_type == "radarr":
        items = arr_api_request(base_url, arr_api_key, "GET", "/api/v3/movie")
        used = {item.get("qualityProfileId") for item in items}
    else:
        items = arr_api_request(base_url, arr_api_key, "GET", "/api/v3/series")
        used = {item.get("qualityProfileId") for item in items}

    changed = False
    for profile in profiles:
        name = profile.get("name", "")
        profile_id = profile.get("id")
        if name in ALLOWED_QUALITY_PROFILES or profile_id in used:
            continue
        arr_api_request(base_url, arr_api_key, "DELETE", f"/api/v3/qualityprofile/{profile_id}")
        changed = True
        eprint(f"removed unused {arr_type} quality profile {name!r}")
    return changed


def trigger_availability_scans(seerr_url: str, api_key: str) -> bool:
    changed = False
    for job_id in (
        "jellyfin-recently-added-scan",
        "jellyfin-full-scan",
        "radarr-scan",
        "sonarr-scan",
        "availability-sync",
    ):
        try:
            api_request(seerr_url, api_key, "POST", f"/api/v1/settings/jobs/{job_id}/run")
            changed = True
            eprint(f"triggered Seerr job {job_id}")
        except SystemExit as exc:
            eprint(f"warning: could not trigger {job_id}: {exc}")
    return changed


def library_type(name: str, lib_type: str) -> str | None:
    normalized = lib_type.lower()
    if normalized in {"movies", "movie"}:
        return "movie"
    if normalized in {"tvshows", "tv", "show"}:
        return "show"
    if name.lower() in {"movies", "movie"}:
        return "movie"
    if name.lower() in {"tv shows", "shows", "tv"}:
        return "show"
    return None


def main() -> int:
    seerr_url = os.environ.get("SEERR_URL", "http://127.0.0.1:5055")
    settings_path = Path(os.environ["SEERR_SETTINGS_FILE"])
    db_path = Path(os.environ["SEERR_DB_FILE"])
    domain = os.environ["DOMAIN"]
    jellyfin_public = os.environ.get("JELLYFIN_PUBLIC_HOST", f"tv.{domain}")
    jellyfin_api_key = os.environ["JELLYFIN_API_KEY"]
    sonarr_api_key = os.environ["SONARR_API_KEY"]
    radarr_api_key = os.environ["RADARR_API_KEY"]
    sonarr_host = os.environ.get("SONARR_HOST", "gluetun")
    sonarr_port = int(os.environ.get("SONARR_PORT", "8989"))
    radarr_host = os.environ.get("RADARR_HOST", "gluetun")
    radarr_port = int(os.environ.get("RADARR_PORT", "7878"))
    sonarr_profile = os.environ.get("SEERR_SONARR_QUALITY_PROFILE", "")
    sonarr_root = os.environ.get("SEERR_SONARR_ROOT_FOLDER", "")
    radarr_profile = os.environ.get("SEERR_RADARR_QUALITY_PROFILE", "")
    radarr_root = os.environ.get("SEERR_RADARR_ROOT_FOLDER", "")
    oidc_client_secret = os.environ.get("OIDC_CLIENT_SECRET", "")
    oidc_issuer_url = os.environ.get("OIDC_ISSUER_URL", f"https://auth.{domain}")
    oidc_client_id = os.environ.get("SEERR_OIDC_CLIENT_ID", "seerr")
    oidc_new_users = os.environ.get("SEERR_OIDC_NEW_USER_LOGIN", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    local_login = os.environ.get("SEERR_LOCAL_LOGIN", "false").lower() in {"1", "true", "yes"}
    admin_email = os.environ.get("SEERR_ADMIN_EMAIL", "")
    admin_password = os.environ.get("SEERR_ADMIN_PASSWORD", "")

    if not oidc_client_secret:
        raise SystemExit("OIDC_CLIENT_SECRET is required for Seerr Authelia login")

    if not sonarr_profile:
        profiles = load_json_env("SONARR_QUALITY_PROFILES", [])
        sonarr_profile = pick_named_profile(profiles, ("HD-720p",), fallback_last=False)
    if not sonarr_root:
        roots = load_json_env("SONARR_ROOT_FOLDERS", [])
        if roots:
            sonarr_root = str(roots[-1])
    if not radarr_profile:
        profiles = load_json_env("RADARR_QUALITY_PROFILES", [])
        radarr_profile = pick_named_profile(profiles, ("HD-1080p", "HD-720p"), fallback_last=True)
    if not radarr_root:
        roots = load_json_env("RADARR_ROOT_FOLDERS", [])
        if roots:
            radarr_root = str(roots[-1])

    api_key = read_api_key(settings_path)
    os.environ["SEERR_API_KEY"] = api_key

    created_admin = False
    if local_login:
        created_admin = ensure_local_admin(db_path, admin_email, admin_password)

    public = api_request(seerr_url, api_key, "GET", "/api/v1/settings/public")
    changed = created_admin

    desired_main = {
        "mediaServerLogin": True,
        "mediaServerType": MEDIA_SERVER_JELLYFIN,
        "applicationTitle": "Seerr",
    }
    current_main = api_request(seerr_url, api_key, "GET", "/api/v1/settings/main")
    if any(current_main.get(k) != v for k, v in desired_main.items()):
        api_request(seerr_url, api_key, "POST", "/api/v1/settings/main", body=desired_main)
        changed = True
        eprint("updated Seerr main settings")

    desired_jellyfin = {
        "ip": jellyfin_public,
        "port": 443,
        "useSsl": True,
        "urlBase": "",
        "apiKey": jellyfin_api_key,
    }
    current_jellyfin = api_request(seerr_url, api_key, "GET", "/api/v1/settings/jellyfin")
    jellyfin_needs_update = any(current_jellyfin.get(k) != v for k, v in desired_jellyfin.items())
    if jellyfin_needs_update:
        api_request(seerr_url, api_key, "POST", "/api/v1/settings/jellyfin", body=desired_jellyfin)
        changed = True
        eprint("updated Seerr Jellyfin connection")

    libraries = api_request(
        seerr_url,
        api_key,
        "POST",
        "/api/v1/settings/jellyfin/library/sync",
    )
    for lib in libraries:
        should_enable = (
            str(lib.get("type", "")).lower() in {"movie", "show"}
            or library_type(str(lib.get("name", "")), str(lib.get("type", ""))) in {"movie", "show"}
        )
        if lib.get("enabled") != should_enable:
            api_request(
                seerr_url,
                api_key,
                "PUT",
                f"/api/v1/settings/jellyfin/library/{lib['id']}",
                body={"enabled": should_enable},
            )
            changed = True
            state = "enabled" if should_enable else "disabled"
            eprint(f"{state} Jellyfin library {lib.get('name', lib['id'])}")

    sonarr_base = f"http://{sonarr_host}:{sonarr_port}"
    radarr_base = f"http://{radarr_host}:{radarr_port}"
    if prune_arr_quality_profiles(sonarr_base, sonarr_api_key, "sonarr"):
        changed = True
    if prune_arr_quality_profiles(radarr_base, radarr_api_key, "radarr"):
        changed = True

    if sync_dvr_servers(
        seerr_url,
        api_key,
        arr_type="sonarr",
        specs=SONARR_SERVER_SPECS,
        build_payload=build_sonarr_payload,
        hostname=sonarr_host,
        port=sonarr_port,
        arr_api_key=sonarr_api_key,
        root_folder=sonarr_root,
    ):
        changed = True

    if sync_dvr_servers(
        seerr_url,
        api_key,
        arr_type="radarr",
        specs=RADARR_SERVER_SPECS,
        build_payload=build_radarr_payload,
        hostname=radarr_host,
        port=radarr_port,
        arr_api_key=radarr_api_key,
        root_folder=radarr_root,
    ):
        changed = True

    if sync_default_permissions(seerr_url, api_key):
        changed = True

    if grant_advanced_request_to_users(seerr_url, api_key):
        changed = True

    if trigger_availability_scans(seerr_url, api_key):
        changed = True

    if not public.get("initialized"):
        api_request(seerr_url, api_key, "POST", "/api/v1/settings/initialize")
        changed = True
        eprint("marked Seerr as initialized")

    if configure_oidc_settings(
        settings_path,
        issuer_url=oidc_issuer_url,
        client_id=oidc_client_id,
        client_secret=oidc_client_secret,
        new_user_login=oidc_new_users,
        local_login=local_login,
        oidc_login=True,
        media_server_login=True,
    ):
        changed = True
        eprint("seerr restart required")

    if changed:
        eprint("Seerr bootstrap applied changes")
    else:
        eprint("nothing to change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
