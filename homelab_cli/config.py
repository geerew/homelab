"""Load, validate, and flatten homelab.yaml."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from homelab_cli.paths import config_file, repo_root


class ConfigError(Exception):
    pass


def parse_dotenv(text: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key.strip()] = value
    return env


def normalize_pem(pem: str) -> str:
    """Collapse folded YAML whitespace and blank lines in a PEM block."""
    if not pem:
        return pem
    lines = [line.strip() for line in pem.splitlines() if line.strip()]
    return "\n".join(lines) + "\n"


class _LiteralStr(str):
    """Marker for YAML literal block (|) serialization."""


def _literal_str_representer(dumper: yaml.Dumper, data: _LiteralStr) -> yaml.nodes.ScalarNode:
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style=style)


yaml.add_representer(_LiteralStr, _literal_str_representer)


def dump_config(cfg: dict[str, Any]) -> str:
    """Serialize homelab config; PEM fields use YAML literal blocks."""
    import copy

    cfg_copy = copy.deepcopy(cfg)
    au = cfg_copy.get("authelia")
    if isinstance(au, dict) and au.get("jwks_private_key"):
        au["jwks_private_key"] = _LiteralStr(normalize_pem(au["jwks_private_key"]))
    return yaml.safe_dump(cfg_copy, sort_keys=False, default_flow_style=False, allow_unicode=True)


def _parse_volumes(raw: str) -> list[dict[str, str]]:
    volumes: list[dict[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        host, _, container = part.partition(":")
        volumes.append({"host": host.strip(), "container": container.strip()})
    return volumes


def env_to_config(env: dict[str, str], users: dict[str, Any] | None = None, jwks_pem: str = "") -> dict[str, Any]:
    """Convert flat .env dict to nested homelab.yaml structure."""
    users = users or {}
    cfg: dict[str, Any] = {
        "core": {
            "data_dir": env.get("DATA_DIR", "."),
            "puid": int(env.get("PUID", "1000")),
            "pgid": int(env.get("PGID", "1000")),
            "tz": env.get("TZ", "UTC"),
            "domain": env.get("DOMAIN", "example.com"),
            "acme_email": env.get("ACME_EMAIL", ""),
        },
        "socket_proxy": {
            "log_level": env.get("SOCKET_PROXY_LOG_LEVEL", "warning"),
            "allow_start": env.get("SOCKET_PROXY_ALLOW_START", "1"),
            "allow_stop": env.get("SOCKET_PROXY_ALLOW_STOP", "1"),
            "allow_restarts": env.get("SOCKET_PROXY_ALLOW_RESTARTS", "1"),
            "events": env.get("SOCKET_PROXY_EVENTS", "1"),
            "ping": env.get("SOCKET_PROXY_PING", "1"),
            "version": env.get("SOCKET_PROXY_VERSION", "1"),
            "auth": env.get("SOCKET_PROXY_AUTH", "0"),
            "secrets": env.get("SOCKET_PROXY_SECRETS", "0"),
            "post": env.get("SOCKET_PROXY_POST", "1"),
            "build": env.get("SOCKET_PROXY_BUILD", "0"),
            "commit": env.get("SOCKET_PROXY_COMMIT", "0"),
            "configs": env.get("SOCKET_PROXY_CONFIGS", "0"),
            "containers": env.get("SOCKET_PROXY_CONTAINERS", "1"),
            "distribution": env.get("SOCKET_PROXY_DISTRIBUTION", "0"),
            "exec": env.get("SOCKET_PROXY_EXEC", "0"),
            "images": env.get("SOCKET_PROXY_IMAGES", "1"),
            "info": env.get("SOCKET_PROXY_INFO", "1"),
            "networks": env.get("SOCKET_PROXY_NETWORKS", "1"),
            "nodes": env.get("SOCKET_PROXY_NODES", "0"),
            "plugins": env.get("SOCKET_PROXY_PLUGINS", "0"),
            "services": env.get("SOCKET_PROXY_SERVICES", "1"),
            "session": env.get("SOCKET_PROXY_SESSION", "0"),
            "swarm": env.get("SOCKET_PROXY_SWARM", "0"),
            "system": env.get("SOCKET_PROXY_SYSTEM", "0"),
            "tasks": env.get("SOCKET_PROXY_TASKS", "1"),
            "volumes": env.get("SOCKET_PROXY_VOLUMES", "1"),
            "disable_ipv6": env.get("SOCKET_PROXY_DISABLE_IPV6", "0"),
        },
        "watchtower": {
            "cleanup": env.get("WATCHTOWER_CLEANUP", "true"),
            "poll_interval": env.get("WATCHTOWER_POLL_INTERVAL", "86400"),
            "label_enable": env.get("WATCHTOWER_LABEL_ENABLE", "true"),
        },
        "dozzle": {
            "level": env.get("DOZZLE_LEVEL", "info"),
            "filter": env.get("DOZZLE_FILTER", "status=running"),
            "remote_host": env.get("DOZZLE_REMOTE_HOST", "tcp://socket-proxy:2375"),
            "auth_provider": env.get("DOZZLE_AUTH_PROVIDER", "forward-proxy"),
            "auth_header_user": env.get("DOZZLE_AUTH_HEADER_USER", "Remote-User"),
        },
        "cloudflare": {
            "api_token": env.get("CLOUDFLARE_API_TOKEN", ""),
            "ddns_domains": env.get("CLOUDFLARE_DDNS_DOMAINS", ""),
            "ddns_proxied": env.get("CLOUDFLARE_DDNS_PROXIED", "true"),
            "ddns_detection_mode": env.get("CLOUDFLARE_DDNS_DETECTION_MODE", "cloudflare.trace"),
            "ddns_http_timeout": env.get("CLOUDFLARE_DDNS_HTTP_TIMEOUT", "10s"),
        },
        "authelia": {
            "session_secret": env.get("AUTHELIA_SESSION_SECRET", ""),
            "jwt_secret": env.get("AUTHELIA_JWT_SECRET", ""),
            "storage_encryption_key": env.get("AUTHELIA_STORAGE_ENCRYPTION_KEY", ""),
            "oidc_hmac_secret": env.get("AUTHELIA_OIDC_HMAC_SECRET", ""),
            "oidc_client_secret": env.get("OIDC_CLIENT_SECRET", ""),
            "jwks_private_key": normalize_pem(jwks_pem),
            "users": users.get("users", users),
        },
        "memos": {
            "admin_username": env.get("MEMOS_ADMIN_USERNAME", "admin"),
            "admin_password": env.get("MEMOS_ADMIN_PASSWORD", ""),
            "admin_email": env.get("MEMOS_ADMIN_EMAIL", ""),
        },
        "sparkyfitness": {
            "db_password": env.get("SPARKY_FITNESS_DB_PASSWORD", ""),
            "app_db_password": env.get("SPARKY_FITNESS_APP_DB_PASSWORD", ""),
            "encryption_key": env.get("SPARKY_FITNESS_ENCRYPTION_KEY", ""),
            "better_auth": env.get("SPARKY_FITNESS_BETTER_AUTH", ""),
            "jwt_secret": env.get("SPARKY_FITNESS_JWT_SECRET", ""),
        },
        "mealie": {
            "admin_username": env.get("MEALIE_ADMIN_USERNAME", "admin"),
            "admin_password": env.get("MEALIE_ADMIN_PASSWORD", ""),
            "admin_email": env.get("MEALIE_ADMIN_EMAIL", ""),
            "openai_api_key": env.get("MEALIE_OPENAI_API_KEY", ""),
        },
        "gluetun": {
            "api_key": env.get("GLUETUN_API_KEY", ""),
            "vpn_service_provider": env.get("VPN_SERVICE_PROVIDER", "mullvad"),
            "vpn_type": env.get("VPN_TYPE", "wireguard"),
            "wireguard_private_key": env.get("WIREGUARD_PRIVATE_KEY", ""),
            "wireguard_addresses": env.get("WIREGUARD_ADDRESSES", ""),
            "server_cities": env.get("SERVER_CITIES", ""),
            "dot": env.get("GLUETUN_DOT", "off"),
            "dns_address": env.get("GLUETUN_DNS_ADDRESS", "10.64.0.1"),
            "firewall_outbound_subnets": env.get("FIREWALL_OUTBOUND_SUBNETS", "192.168.90.0/24"),
            "ports": {
                "httpproxy": int(env.get("GLUETUN_PORT_HTTPPROXY", "8888")),
                "control_server": int(env.get("GLUETUN_PORT_CONTROL_SERVER", "8080")),
                "sonarr": int(env.get("SONARR_PORT", "8989")),
                "radarr": int(env.get("RADARR_PORT", "7878")),
                "prowlarr": int(env.get("PROWLARR_PORT", "9696")),
                "bazarr": int(env.get("BAZARR_PORT", "6767")),
                "qbittorrent_webui": int(env.get("QBITTORRENT_WEBUI_PORT", "9865")),
            },
        },
        "qbittorrent": {
            "webui_username": env.get("QBITTORRENT_WEBUI_USERNAME", "admin"),
            "webui_password": env.get("QBITTORRENT_WEBUI_PASSWORD", ""),
            "lan_auth_bypass": env.get("QBITTORRENT_LAN_AUTH_BYPASS", "true"),
        },
        "media": {
            "media1_dir": env.get("MEDIA1_DIR", "/mnt/media1"),
            "media2_dir": env.get("MEDIA2_DIR", "/mnt/media2"),
            "audiobooks_dir": env.get("AUDIOBOOKS_DIR", "/mnt/audiobooks"),
            "downloads_dir": env.get("DOWNLOADS_DIR", "/downloads"),
        },
        "audiobookshelf": {
            "volumes": _parse_volumes(
                env.get("AUDIOBOOKSHELF_VOLUMES", env.get("AUDIOBOOKS_DIR", "/mnt/audiobooks") + ":/audiobooks")
            ),
            "root_username": env.get("AUDIOBOOKSHELF_ROOT_USERNAME", "admin"),
            "root_password": env.get("AUDIOBOOKSHELF_ROOT_PASSWORD", ""),
            "libraries": json.loads(env.get("AUDIOBOOKSHELF_LIBRARIES", "[]")),
        },
        "uptime_kuma": {
            "bazarr_url": env.get("KUMA_BAZARR_URL", ""),
            "sonarr_url": env.get("KUMA_SONARR_URL", ""),
            "radarr_url": env.get("KUMA_RADARR_URL", ""),
            "prowlarr_url": env.get("KUMA_PROWLARR_URL", ""),
            "dispatcharr_url": env.get("KUMA_DISPATCHARR_URL", ""),
        },
        "jellyscope": {
            "admin_username": env.get("JELLYSCOPE_ADMIN_USERNAME", "admin"),
            "admin_password": env.get("JELLYSCOPE_ADMIN_PASSWORD", ""),
            "secret_key": env.get("JELLYSCOPE_SECRET_KEY", ""),
        },
        "homepage": {
            "sonarr_api_key": env.get("HOMEPAGE_SONARR_API_KEY", ""),
            "seerr_api_key": env.get("HOMEPAGE_SEERR_API_KEY", ""),
            "bazarr_api_key": env.get("HOMEPAGE_BAZARR_API_KEY", ""),
        },
        "mcclean": {
            "admin_username": env.get("MCCLEAN_ADMIN_USERNAME", "admin"),
            "admin_password": env.get("MCCLEAN_ADMIN_PASSWORD", ""),
        },
        "dispatcharr": {
            "admin_username": env.get("DISPATCHARR_ADMIN_USERNAME", "admin"),
            "admin_password": env.get("DISPATCHARR_ADMIN_PASSWORD", ""),
            "admin_email": env.get("DISPATCHARR_ADMIN_EMAIL", ""),
            "trusted_proxies": env.get("DISPATCHARR_TRUSTED_PROXIES", "none"),
            "setup_allowed_ip": env.get("DISPATCHARR_SETUP_ALLOWED_IP", "127.0.0.1"),
            "m3u_name": env.get("DISPATCHARR_M3U_NAME", ""),
            "m3u_url": env.get("DISPATCHARR_M3U_URL", ""),
            "m3u_username": env.get("DISPATCHARR_M3U_USERNAME", ""),
            "m3u_password": env.get("DISPATCHARR_M3U_PASSWORD", ""),
            "m3u_account_type": env.get("DISPATCHARR_M3U_ACCOUNT_TYPE", "XC"),
            "m3u_max_streams": int(env.get("DISPATCHARR_M3U_MAX_STREAMS", "1")),
            "m3u_refresh_interval": int(env.get("DISPATCHARR_M3U_REFRESH_INTERVAL", "24")),
            "xc_password": env.get("DISPATCHARR_XC_PASSWORD", ""),
        },
    }
    return cfg


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or config_file()
    if not cfg_path.is_file():
        raise ConfigError(f"Missing config: {cfg_path} — copy homelab.example.yaml to homelab.yaml")
    with cfg_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"{cfg_path} must be a YAML mapping")
    au = data.get("authelia")
    if isinstance(au, dict) and au.get("jwks_private_key"):
        au["jwks_private_key"] = normalize_pem(au["jwks_private_key"])
    return data


def flatten_config(cfg: dict[str, Any]) -> dict[str, str]:
    """Map nested homelab.yaml to legacy flat keys used by Ansible templates."""
    core = cfg.get("core", {})
    sp = cfg.get("socket_proxy", {})
    wt = cfg.get("watchtower", {})
    dz = cfg.get("dozzle", {})
    cf = cfg.get("cloudflare", {})
    au = cfg.get("authelia", {})
    memos = cfg.get("memos", {})
    sf = cfg.get("sparkyfitness", {})
    mealie = cfg.get("mealie", {})
    gl = cfg.get("gluetun", {})
    gl_ports = gl.get("ports", {})
    qb = cfg.get("qbittorrent", {})
    prowlarr = cfg.get("prowlarr", {})
    radarr = cfg.get("radarr", {})
    media = cfg.get("media", {})
    abs_cfg = cfg.get("audiobookshelf", {})
    kuma = cfg.get("uptime_kuma", {})
    js = cfg.get("jellyscope", {})
    hp = cfg.get("homepage", {})
    mc = cfg.get("mcclean", {})
    dp = cfg.get("dispatcharr", {})

    abs_volumes = abs_cfg.get("volumes", [])
    abs_vol_str = ",".join(f"{v['host']}:{v['container']}" for v in abs_volumes if v.get("host") and v.get("container"))

    libraries = abs_cfg.get("libraries", [])
    prowlarr_indexers = prowlarr.get("indexers", [])
    prowlarr_indexers_json = json.dumps(
        [
            {
                "name": idx.get("name"),
                "definition": idx.get("definition"),
                "enable": idx.get("enable", True),
                "private": idx.get("private", False),
                **({"username": idx["username"]} if idx.get("username") is not None else {}),
                **({"password": idx["password"]} if idx.get("password") is not None else {}),
                **({"alt2fa_token": idx["alt2fa_token"]} if idx.get("alt2fa_token") else {}),
            }
            for idx in prowlarr_indexers
        ]
    )

    radarr_indexers_json = json.dumps(radarr.get("indexers", []))
    radarr_download_clients_json = json.dumps(radarr.get("download_clients", []))
    radarr_root_folders_json = json.dumps(radarr.get("root_folders", []))
    radarr_naming_json = json.dumps(radarr.get("naming", {}))
    radarr_media_management_json = json.dumps(radarr.get("media_management", {}))
    radarr_qualities_json = json.dumps(radarr.get("qualities", {}))
    radarr_quality_profiles_json = json.dumps(radarr.get("quality_profiles", []))
    radarr_quality_definitions_json = json.dumps(radarr.get("quality_definitions", {}))
    library_import = radarr.get("library_import", {})
    radarr_library_import_json = json.dumps(
        {
            "enabled": library_import.get("enabled", True),
            "quality_profile": library_import.get("quality_profile", ""),
            "minimum_availability": library_import.get("minimum_availability", "released"),
            "monitor": library_import.get("monitor", "none"),
        }
    )

    # bootstrap script expects mediaType in JSON
    lib_json = json.dumps(
        [
            {
                "name": lib.get("name"),
                "mediaType": lib.get("media_type", lib.get("mediaType", "book")),
                "folders": lib.get("folders", []),
                **({"icon": lib["icon"]} if lib.get("icon") else {}),
                **({"provider": lib["provider"]} if lib.get("provider") else {}),
                **({"settings": lib["settings"]} if lib.get("settings") else {}),
            }
            for lib in libraries
        ]
    )

    flat: dict[str, str] = {
        "DATA_DIR": str(core.get("data_dir", ".")),
        "PUID": str(core.get("puid", 1000)),
        "PGID": str(core.get("pgid", 1000)),
        "TZ": str(core.get("tz", "UTC")),
        "DOMAIN": str(core.get("domain", "")),
        "ACME_EMAIL": str(core.get("acme_email", "")),
        "SOCKET_PROXY_LOG_LEVEL": str(sp.get("log_level", "warning")),
        "SOCKET_PROXY_ALLOW_START": str(sp.get("allow_start", "1")),
        "SOCKET_PROXY_ALLOW_STOP": str(sp.get("allow_stop", "1")),
        "SOCKET_PROXY_ALLOW_RESTARTS": str(sp.get("allow_restarts", "1")),
        "SOCKET_PROXY_EVENTS": str(sp.get("events", "1")),
        "SOCKET_PROXY_PING": str(sp.get("ping", "1")),
        "SOCKET_PROXY_VERSION": str(sp.get("version", "1")),
        "SOCKET_PROXY_AUTH": str(sp.get("auth", "0")),
        "SOCKET_PROXY_SECRETS": str(sp.get("secrets", "0")),
        "SOCKET_PROXY_POST": str(sp.get("post", "1")),
        "SOCKET_PROXY_BUILD": str(sp.get("build", "0")),
        "SOCKET_PROXY_COMMIT": str(sp.get("commit", "0")),
        "SOCKET_PROXY_CONFIGS": str(sp.get("configs", "0")),
        "SOCKET_PROXY_CONTAINERS": str(sp.get("containers", "1")),
        "SOCKET_PROXY_DISTRIBUTION": str(sp.get("distribution", "0")),
        "SOCKET_PROXY_EXEC": str(sp.get("exec", "0")),
        "SOCKET_PROXY_IMAGES": str(sp.get("images", "1")),
        "SOCKET_PROXY_INFO": str(sp.get("info", "1")),
        "SOCKET_PROXY_NETWORKS": str(sp.get("networks", "1")),
        "SOCKET_PROXY_NODES": str(sp.get("nodes", "0")),
        "SOCKET_PROXY_PLUGINS": str(sp.get("plugins", "0")),
        "SOCKET_PROXY_SERVICES": str(sp.get("services", "1")),
        "SOCKET_PROXY_SESSION": str(sp.get("session", "0")),
        "SOCKET_PROXY_SWARM": str(sp.get("swarm", "0")),
        "SOCKET_PROXY_SYSTEM": str(sp.get("system", "0")),
        "SOCKET_PROXY_TASKS": str(sp.get("tasks", "1")),
        "SOCKET_PROXY_VOLUMES": str(sp.get("volumes", "1")),
        "SOCKET_PROXY_DISABLE_IPV6": str(sp.get("disable_ipv6", "0")),
        "WATCHTOWER_CLEANUP": str(wt.get("cleanup", "true")),
        "WATCHTOWER_POLL_INTERVAL": str(wt.get("poll_interval", "86400")),
        "WATCHTOWER_LABEL_ENABLE": str(wt.get("label_enable", "true")),
        "DOZZLE_LEVEL": str(dz.get("level", "info")),
        "DOZZLE_FILTER": str(dz.get("filter", "status=running")),
        "DOZZLE_REMOTE_HOST": str(dz.get("remote_host", "tcp://socket-proxy:2375")),
        "DOZZLE_AUTH_PROVIDER": str(dz.get("auth_provider", "forward-proxy")),
        "DOZZLE_AUTH_HEADER_USER": str(dz.get("auth_header_user", "Remote-User")),
        "CLOUDFLARE_API_TOKEN": str(cf.get("api_token", "")),
        "CLOUDFLARE_DDNS_DOMAINS": str(cf.get("ddns_domains", "")),
        "CLOUDFLARE_DDNS_PROXIED": str(cf.get("ddns_proxied", "true")),
        "CLOUDFLARE_DDNS_DETECTION_MODE": str(cf.get("ddns_detection_mode", "cloudflare.trace")),
        "CLOUDFLARE_DDNS_HTTP_TIMEOUT": str(cf.get("ddns_http_timeout", "10s")),
        "AUTHELIA_SESSION_SECRET": str(au.get("session_secret", "")),
        "AUTHELIA_JWT_SECRET": str(au.get("jwt_secret", "")),
        "AUTHELIA_STORAGE_ENCRYPTION_KEY": str(au.get("storage_encryption_key", "")),
        "AUTHELIA_OIDC_HMAC_SECRET": str(au.get("oidc_hmac_secret", "")),
        "OIDC_CLIENT_SECRET": str(au.get("oidc_client_secret", "")),
        "MEMOS_ADMIN_USERNAME": str(memos.get("admin_username", "admin")),
        "MEMOS_ADMIN_PASSWORD": str(memos.get("admin_password", "")),
        "MEMOS_ADMIN_EMAIL": str(memos.get("admin_email", "")),
        "SPARKY_FITNESS_DB_PASSWORD": str(sf.get("db_password", "")),
        "SPARKY_FITNESS_APP_DB_PASSWORD": str(sf.get("app_db_password", "")),
        "SPARKY_FITNESS_ENCRYPTION_KEY": str(sf.get("encryption_key", "")),
        "SPARKY_FITNESS_BETTER_AUTH": str(sf.get("better_auth", "")),
        "SPARKY_FITNESS_JWT_SECRET": str(sf.get("jwt_secret", "")),
        "MEALIE_ADMIN_USERNAME": str(mealie.get("admin_username", "admin")),
        "MEALIE_ADMIN_PASSWORD": str(mealie.get("admin_password", "")),
        "MEALIE_ADMIN_EMAIL": str(mealie.get("admin_email", "")),
        "MEALIE_OPENAI_API_KEY": str(mealie.get("openai_api_key", "")),
        "GLUETUN_API_KEY": str(gl.get("api_key", "")),
        "VPN_SERVICE_PROVIDER": str(gl.get("vpn_service_provider", "")),
        "VPN_TYPE": str(gl.get("vpn_type", "")),
        "WIREGUARD_PRIVATE_KEY": str(gl.get("wireguard_private_key", "")),
        "WIREGUARD_ADDRESSES": str(gl.get("wireguard_addresses", "")),
        "SERVER_CITIES": str(gl.get("server_cities", "")),
        "GLUETUN_DOT": str(gl.get("dot", "off")),
        "GLUETUN_DNS_ADDRESS": str(gl.get("dns_address", "")),
        "FIREWALL_OUTBOUND_SUBNETS": str(gl.get("firewall_outbound_subnets", "")),
        "GLUETUN_PORT_HTTPPROXY": str(gl_ports.get("httpproxy", 8888)),
        "GLUETUN_PORT_CONTROL_SERVER": str(gl_ports.get("control_server", 8080)),
        "SONARR_PORT": str(gl_ports.get("sonarr", 8989)),
        "RADARR_PORT": str(gl_ports.get("radarr", 7878)),
        "PROWLARR_PORT": str(gl_ports.get("prowlarr", 9696)),
        "BAZARR_PORT": str(gl_ports.get("bazarr", 6767)),
        "QBITTORRENT_WEBUI_PORT": str(gl_ports.get("qbittorrent_webui", 9865)),
        "QBITTORRENT_WEBUI_USERNAME": str(qb.get("webui_username", "admin")),
        "QBITTORRENT_WEBUI_PASSWORD": str(qb.get("webui_password", "")),
        "QBITTORRENT_LAN_AUTH_BYPASS": str(qb.get("lan_auth_bypass", "true")),
        "PROWLARR_INDEXERS": prowlarr_indexers_json,
        "RADARR_ROOT_FOLDERS": radarr_root_folders_json,
        "RADARR_INDEXERS": radarr_indexers_json,
        "RADARR_DOWNLOAD_CLIENTS": radarr_download_clients_json,
        "RADARR_NAMING": radarr_naming_json,
        "RADARR_MEDIA_MANAGEMENT": radarr_media_management_json,
        "RADARR_QUALITIES": radarr_qualities_json,
        "RADARR_QUALITY_PROFILES": radarr_quality_profiles_json,
        "RADARR_QUALITY_DEFINITIONS": radarr_quality_definitions_json,
        "RADARR_LIBRARY_IMPORT": radarr_library_import_json,
        "MEDIA1_DIR": str(media.get("media1_dir", "")),
        "MEDIA2_DIR": str(media.get("media2_dir", "")),
        "AUDIOBOOKS_DIR": str(media.get("audiobooks_dir", "")),
        "DOWNLOADS_DIR": str(media.get("downloads_dir", "")),
        "AUDIOBOOKSHELF_VOLUMES": abs_vol_str,
        "AUDIOBOOKSHELF_PORT": str(abs_cfg.get("port", 13378)),
        "AUDIOBOOKSHELF_ROOT_USERNAME": str(abs_cfg.get("root_username", "admin")),
        "AUDIOBOOKSHELF_ROOT_PASSWORD": str(abs_cfg.get("root_password", "")),
        "AUDIOBOOKSHELF_LIBRARIES": lib_json,
        "KUMA_BAZARR_URL": str(kuma.get("bazarr_url", "")),
        "KUMA_SONARR_URL": str(kuma.get("sonarr_url", "")),
        "KUMA_RADARR_URL": str(kuma.get("radarr_url", "")),
        "KUMA_PROWLARR_URL": str(kuma.get("prowlarr_url", "")),
        "KUMA_DISPATCHARR_URL": str(kuma.get("dispatcharr_url", "")),
        "JELLYSCOPE_ADMIN_USERNAME": str(js.get("admin_username", "admin")),
        "JELLYSCOPE_ADMIN_PASSWORD": str(js.get("admin_password", "")),
        "JELLYSCOPE_SECRET_KEY": str(js.get("secret_key", "")),
        "HOMEPAGE_SONARR_API_KEY": str(hp.get("sonarr_api_key", "")),
        "HOMEPAGE_SEERR_API_KEY": str(hp.get("seerr_api_key", "")),
        "HOMEPAGE_BAZARR_API_KEY": str(hp.get("bazarr_api_key", "")),
        "MCCLEAN_ADMIN_USERNAME": str(mc.get("admin_username", "admin")),
        "MCCLEAN_ADMIN_PASSWORD": str(mc.get("admin_password", "")),
        "DISPATCHARR_ADMIN_USERNAME": str(dp.get("admin_username", "admin")),
        "DISPATCHARR_ADMIN_PASSWORD": str(dp.get("admin_password", "")),
        "DISPATCHARR_ADMIN_EMAIL": str(dp.get("admin_email", "")),
        "DISPATCHARR_TRUSTED_PROXIES": str(dp.get("trusted_proxies", "none")),
        "DISPATCHARR_SETUP_ALLOWED_IP": str(dp.get("setup_allowed_ip", "127.0.0.1")),
        "DISPATCHARR_M3U_NAME": str(dp.get("m3u_name", "")),
        "DISPATCHARR_M3U_URL": str(dp.get("m3u_url", "")),
        "DISPATCHARR_M3U_USERNAME": str(dp.get("m3u_username", "")),
        "DISPATCHARR_M3U_PASSWORD": str(dp.get("m3u_password", "")),
        "DISPATCHARR_M3U_ACCOUNT_TYPE": str(dp.get("m3u_account_type", "XC")),
        "DISPATCHARR_M3U_MAX_STREAMS": str(dp.get("m3u_max_streams", 1)),
        "DISPATCHARR_M3U_REFRESH_INTERVAL": str(dp.get("m3u_refresh_interval", 24)),
        "DISPATCHARR_XC_PASSWORD": str(dp.get("xc_password", "")),
    }
    return flat


def resolve_data_dir(cfg: dict[str, Any]) -> Path:
    raw = str(cfg.get("core", {}).get("data_dir", "."))
    root = repo_root()
    if raw in (".", "./"):
        return root
    return Path(raw).expanduser().resolve()


def validate_config(cfg: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    core = cfg.get("core", {})
    if not core.get("domain"):
        errors.append("core.domain is required")
    if not core.get("data_dir"):
        errors.append("core.data_dir is required")
    au = cfg.get("authelia", {})
    for key in ("session_secret", "jwt_secret", "storage_encryption_key", "oidc_hmac_secret", "oidc_client_secret"):
        if not au.get(key):
            errors.append(f"authelia.{key} is required")
    if not au.get("jwks_private_key", "").strip():
        errors.append("authelia.jwks_private_key is required")
    users = au.get("users", {})
    if not users:
        errors.append("authelia.users must not be empty")
    return errors


def lookup(cfg: dict[str, Any], dotted: str) -> Any:
    cur: Any = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def render_scalar(cfg: dict[str, Any], flat: dict[str, str], token: str) -> str:
    """Resolve compose template token like core.domain or legacy ENV_NAME."""
    if re.match(r"^[A-Z][A-Z0-9_]*$", token):
        return flat.get(token, "")
    value = lookup(cfg, token)
    if value is None:
        return ""
    return str(value)
