# Ansible migration checklist

Step through services one at a time until each has a `deploy-<service>.yml` playbook that stands up the service **and** applies as much configuration as possible. Goal: wipe `services/<app>/`, run Ansible, and avoid manual UI setup.

**Pattern for each service:**

1. Add `playbooks/deploy-<service>.yml`
2. Put secrets in `homelab.yaml` / `homelab.example.yaml` (never commit secrets to Ansible)
3. Put static config in `files/<service>/`
4. Put templated config in `templates/<service>/*.j2`
5. Import the playbook from `playbooks/deploy-services.yml` when ready
6. Document required `homelab.yaml` keys in this file and `README.md`

**Legend**

| Status | Meaning |
| --- | --- |
| ✅ Done | Playbook exists; config is largely reproducible from Ansible |
| 🟡 Partial | Playbook exists; significant config still manual or in Compose only |
| ⬜ Todo | No `deploy-*` playbook yet; only `site.yml` starts the container |
| 🔧 Infra | Shared playbook, not a single app |

**Run order (typical fresh stand-up)**

```bash
cd ansible
ansible-playbook playbooks/site.yml              # 1. dirs + docker compose up (prerequisite)
ansible-playbook playbooks/deploy-services.yml   # 2. all app config in dependency order
```

Or step through individually (same order as `deploy-services.yml` — see that file for the full list):

```bash
ansible-playbook playbooks/deploy-socket-proxy.yml
ansible-playbook playbooks/deploy-traefik.yml
ansible-playbook playbooks/deploy-authelia.yml
ansible-playbook playbooks/deploy-uptime-kuma.yml
ansible-playbook playbooks/deploy-autokuma.yml
ansible-playbook playbooks/deploy-memos.yml
ansible-playbook playbooks/deploy-audiobookshelf.yml
ansible-playbook playbooks/deploy-mealie.yml
ansible-playbook playbooks/deploy-paperless.yml
ansible-playbook playbooks/deploy-gluetun.yml
ansible-playbook playbooks/deploy-dispatcharr.yml
ansible-playbook playbooks/deploy-qbittorrent.yml
ansible-playbook playbooks/deploy-prowlarr.yml
ansible-playbook playbooks/deploy-sonarr.yml
ansible-playbook playbooks/deploy-radarr.yml
ansible-playbook playbooks/deploy-bazarr.yml
ansible-playbook playbooks/deploy-jellyfin.yml
ansible-playbook playbooks/deploy-jellyscope.yml
ansible-playbook playbooks/deploy-homepage.yml         # widgets last
```

**Why order matters**

| Playbook | Depends on |
| --- | --- |
| `site.yml` | — (run first: containers + `traefik_network` / `socket_proxy`) |
| `deploy-socket-proxy.yml` | `site.yml` — Traefik/Homepage/Dozzle/Autokuma need `tcp://socket-proxy:2375` |
| `deploy-watchtower.yml` | `site.yml` |
| `deploy-dozzle.yml` | Socket Proxy running |
| `deploy-traefik.yml` | Socket Proxy running |
| `deploy-cloudflare-ddns.yml` | `site.yml`, `CLOUDFLARE_API_TOKEN` |
| `deploy-authelia.yml` | `site.yml` (subnet auto-detect) |
| `deploy-gluetun.yml` | `site.yml` |
| `deploy-dispatcharr.yml` | `site.yml` (Dispatcharr container on `:9191`; also ensures Gluetun stack is up) |
| `deploy-qbittorrent.yml` | Gluetun running (shared network namespace) |
| `deploy-paperless.yml` | Authelia OIDC client + `paperless.*` in `homelab.yaml` |
| `deploy-prowlarr.yml` | Gluetun stack running |
| `deploy-sonarr.yml` / `deploy-radarr.yml` | Prowlarr indexers + qBittorrent creds in `homelab.yaml` |
| `deploy-bazarr.yml` | Sonarr + Radarr running |
| `deploy-jellyfin.yml` | Dispatcharr M3U populated at `http://dispatcharr:9191/output/m3u/` |
| `deploy-homepage.yml` | Nothing hard — deploy last so widget URLs match live services |

---

## Summary

| Service | Playbook | Fully configured? |
| --- | --- | --- |
| **Socket Proxy** | `deploy-socket-proxy.yml` | **Yes** — API filter flags in `homelab.yaml` |
| **Watchtower** | `deploy-watchtower.yml` | **Yes** — poll/cleanup in `homelab.yaml` |
| **Dozzle** | `deploy-dozzle.yml` | **Yes** — log viewer settings in `homelab.yaml` |
| **Traefik** | `deploy-traefik.yml` | **Yes** — static config + Authelia forward-auth; `acme.json` is runtime |
| **Cloudflare DDNS** | `deploy-cloudflare-ddns.yml` | **Yes** — DNS settings in `homelab.yaml` |
| **Authelia** | `deploy-authelia.yml` | **Yes** — users + OIDC clients templated; SQLite DB auto-created |
| **Uptime Kuma** | `deploy-uptime-kuma.yml` | **Yes** — container + status page sync |
| **Autokuma** | `deploy-autokuma.yml` | **Yes** — monitors from Compose labels + status page groups |
| **Memos** | `deploy-memos.yml` | **Yes** — Authelia OIDC via `/etc/secrets`, SSO-only |
| **Audiobookshelf** | `deploy-audiobookshelf.yml` | **Yes** — libraries, volumes, Authelia OIDC bootstrap |
| **Mealie** | `deploy-mealie.yml` | **Yes** — Authelia OIDC, service admin, optional OpenAI provider |
| **Paperless** | `deploy-paperless.yml` | **Yes** — Authelia OIDC, group sync, UK dates, `pg_dump` backup/restore |
| **Gluetun** | `deploy-gluetun.yml` | **Yes** — VPN in `homelab.yaml`, control API key auto-generated |
| **Dispatcharr** | `deploy-dispatcharr.yml` | **Yes** — M3U/XC, EPL channel groups, auto sync |
| **qBittorrent** | `deploy-qbittorrent.yml` | **Mostly** — WebUI port + LAN auth bypass; session prefs on existing installs left to UI |
| **Prowlarr** | `deploy-prowlarr.yml` | **Yes** — Cardigann indexers from `homelab.yaml` |
| **Sonarr** | `deploy-sonarr.yml` | **Yes** — root folders, Prowlarr indexers, qBittorrent, naming/quality profiles |
| **Radarr** | `deploy-radarr.yml` | **Yes** — root folders, Prowlarr indexers, qBittorrent, naming/quality profiles |
| **Bazarr** | `deploy-bazarr.yml` | **Yes** — Sonarr/Radarr links, language profiles, subtitle providers |
| **Jellyfin** | `deploy-jellyfin.yml` | **Yes** — libraries, plugins, SSO, VAAPI, Live TV; Trakt OAuth still manual |
| **Jellyscope** | `deploy-jellyscope.yml` | **Yes** — admin + Jellyfin API key from Ansible |
| **Homepage** | `deploy-homepage.yml` | **Yes** — service list + widgets; API keys auto where possible |

### Remaining (no deploy playbook)

| Service | Status | Notes |
| --- | --- | --- |
| **Seerr** | ⬜ Todo | Jellyfin + *arr integration, OIDC |
| **Sparky Fitness** | ⬜ Todo | DB passwords + auth secrets in `homelab.yaml` |
| **McClean** | ⬜ Todo | `mcclean.admin_*` in `homelab.yaml` |

---

## Infrastructure (already in Ansible)

| Playbook | Purpose | Status |
| --- | --- | --- |
| `site.yml` | `ensure-service-dirs` + `docker compose up` | 🔧 Done |
| `ensure-service-dirs.yml` | Create `services/*` volume tree | 🔧 Done |
| `deploy-services.yml` | Orchestrates all `deploy-*` app playbooks | 🔧 Done (grows as you add playbooks) |
| `tasks/load-homelab-config.yml` | Load `homelab.yaml` → `homelab_config` + flat `homelab_env` | ✅ Done |
| `tasks/resolve-data-dir.yml` | Resolve `DATA_DIR` | 🔧 Done |
| `tasks/start-gluetun-stack.yml` | Restart gluetun + VPN sidecars together | 🔧 Done |

---

## Services with deploy playbooks

### Socket Proxy — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-socket-proxy.yml` |
| **In `deploy-services.yml`** | Yes (first) |
| **Ansible sources** | None — configuration is entirely from `.env` via Compose |
| **`.env` keys** | `SOCKET_PROXY_*` (Docker API permission flags + `SOCKET_PROXY_LOG_LEVEL`) |
| **Configured by Ansible** | Validates `.env` and applies `docker compose up -d socket-proxy` |
| **Still in Compose only** | Kuma docker-host labels, image version |
| **Fresh stand-up** | Set Socket Proxy vars in `.env`, run before Traefik |

---

### Watchtower — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-watchtower.yml` |
| **In `deploy-services.yml`** | Yes (second) |
| **Ansible sources** | None — configuration is entirely from `.env` via Compose |
| **`.env` keys** | `WATCHTOWER_CLEANUP`, `WATCHTOWER_POLL_INTERVAL`, `WATCHTOWER_LABEL_ENABLE` |
| **Configured by Ansible** | Validates `.env` and applies `docker compose up -d watchtower` |
| **Still in Compose only** | Kuma labels, host `/var/run/docker.sock` mount |
| **Fresh stand-up** | Set Watchtower vars in `.env`, run `deploy-watchtower.yml` |

---

### Dozzle — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-dozzle.yml` |
| **In `deploy-services.yml`** | Yes (third, after Socket Proxy + Watchtower) |
| **Ansible sources** | None — configuration is entirely from `.env` via Compose |
| **`.env` keys** | `DOZZLE_LEVEL`, `DOZZLE_FILTER`, `DOZZLE_REMOTE_HOST`, `DOZZLE_AUTH_PROVIDER`, `DOZZLE_AUTH_HEADER_USER` |
| **Configured by Ansible** | Validates `.env` and applies `docker compose up -d dozzle` |
| **Still in Compose only** | Traefik/Kuma labels, image version |
| **Fresh stand-up** | Set Dozzle vars in `.env`, run after `deploy-socket-proxy.yml` |

---

### Traefik — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-traefik.yml` |
| **In `deploy-services.yml`** | Yes (after Socket Proxy + Watchtower) |
| **Ansible sources** | `templates/traefik/traefik.yml.j2`, `templates/traefik/dynamic/authelia.yml.j2` |
| **`.env` keys** | `DOMAIN`, `ACME_EMAIL`, `CLOUDFLARE_API_TOKEN` |
| **Configured by Ansible** | Entrypoints, HTTP→HTTPS redirect, Docker + file providers, Cloudflare ACME resolver, Authelia `forwardAuth` middleware, dashboard route |
| **Still in Compose only** | Per-service router labels, Kuma labels, image version, port 80/443 publish |
| **Auto-managed at runtime (not Ansible)** | `acme.json` — Let's Encrypt certificates; created/renewed by Traefik |
| **Fresh stand-up** | Set Traefik/DNS vars in `.env`, run `deploy-traefik.yml`, then `docker compose up -d traefik` |

---

### Cloudflare DDNS — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-cloudflare-ddns.yml` |
| **In `deploy-services.yml`** | Yes (after Traefik) |
| **Ansible sources** | None — configuration is entirely from `.env` via Compose |
| **`.env` keys** | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_DDNS_DOMAINS`, `CLOUDFLARE_DDNS_PROXIED`, `CLOUDFLARE_DDNS_DETECTION_MODE`, `CLOUDFLARE_DDNS_HTTP_TIMEOUT` |
| **Configured by Ansible** | Validates `.env` and applies `docker compose up -d cloudflare-ddns` |
| **Still in Compose only** | Kuma labels, image version, DNS servers (`1.1.1.1`, `8.8.8.8`) |
| **Fresh stand-up** | Set Cloudflare DDNS vars in `.env`, run `deploy-cloudflare-ddns.yml` |

---

### Authelia — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-authelia.yml` |
| **In `deploy-services.yml`** | Yes |
| **Ansible sources** | `authelia-users.yml`, `authelia-jwks.pem` (repo root, gitignored), `templates/authelia/*.j2`, `vars/authelia_oidc_clients.yml`, `tasks/resolve-docker-network-subnets.yml`, `tasks/authelia-resolve-oidc-client-secret.yml` |
| **`.env` keys** | `DOMAIN`, `AUTHELIA_SESSION_SECRET`, `AUTHELIA_JWT_SECRET`, `AUTHELIA_STORAGE_ENCRYPTION_KEY`, `AUTHELIA_OIDC_HMAC_SECRET`, `AUTHELIA_JWKS_FILE`, `OIDC_CLIENT_SECRET` |
| **Configured by Ansible** | `users.yml` (argon2 hashes), `configuration.yml` (session/storage/OIDC secrets, JWKS, 6 OIDC clients, CORS, vpn-status bypass subnets, access rules) |
| **Auto-managed at runtime (not Ansible)** | `db.sqlite3` — created on first start; stores OIDC consents, 2FA enrollments, session persistence (encrypted with `AUTHELIA_STORAGE_ENCRYPTION_KEY`). `notification.txt` — append-only log for the filesystem notifier (password-reset emails); empty until something triggers a notification. Neither needs templating or migration work. |
| **Fresh stand-up** | Copy `authelia-users.example.yml` → `authelia-users.yml`, set secrets + `AUTHELIA_JWKS_FILE` in `.env`, generate PEM at that path, run `deploy-authelia.yml`. Authelia creates an empty DB on first start — no manual setup. |
| **Existing install** | Keep `db.sqlite3` when migrating (preserves 2FA devices and OIDC consents). Back up before wiping `services/authelia/config/`. |

---

### Dispatcharr — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-dispatcharr.yml` |
| **In `deploy-services.yml`** | Yes |
| **Ansible sources** | `vars/dispatcharr_epl_channel_groups.yml`, `templates/dispatcharr/*.j2` |
| **`.env` keys** | `DISPATCHARR_ADMIN_*`, `DISPATCHARR_M3U_*` (incl. `DISPATCHARR_M3U_REFRESH_INTERVAL`), `DISPATCHARR_XC_PASSWORD` |
| **Configured by Ansible** | Superuser bootstrap, M3U/XC account create + refresh, max streams, XC password on admin, logical channel groups (EPL/TNT/Sky/US EPL), provider group regex mapping, auto channel sync, unmatched provider rules |
| **Still outside Ansible** | `DISPATCHARR_TRUSTED_PROXIES` (Compose env only), Traefik labels (Compose), SQLite DB / uploads beyond bootstrap |
| **Fresh stand-up** | Wipe `services/dispatcharr/data/*`, run `site.yml` then `deploy-dispatcharr.yml` |

---

### Gluetun — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-gluetun.yml` |
| **In `deploy-services.yml`** | Yes |
| **Ansible sources** | `templates/gluetun/config.toml.j2` → `services/gluetun/config.toml` |
| **`.env` keys** | VPN: `VPN_*`, `WIREGUARD_*`, `SERVER_CITIES`, `GLUETUN_DOT`, `GLUETUN_DNS_ADDRESS`, `FIREWALL_OUTBOUND_SUBNETS`. Ports: `GLUETUN_PORT_*`, `SONARR_PORT`, `RADARR_PORT`, `PROWLARR_PORT`, `BAZARR_PORT`, `QBITTORRENT_WEBUI_PORT` |
| **Configured by Ansible** | HTTP control-server API key auto-generated to `services/gluetun/control_api_key` + `compose.env`; auth roles in `config.toml` (Homepage widget) |
| **Configured via `.env` + Compose** | VPN provider, WireGuard creds, server cities, DNS, firewall outbound subnets |
| **Still in Compose only** | Traefik/Kuma labels, HTTP proxy/control-server toggles (port *values* come from `.env`) |
| **Fresh stand-up** | Fill Gluetun section in `.env`, run `deploy-gluetun.yml`, then `docker compose up -d gluetun` (or `site.yml`) |

---

### qBittorrent — 🟡

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-qbittorrent.yml` |
| **In `deploy-services.yml`** | Yes |
| **Ansible sources** | `templates/qbittorrent/qBittorrent.conf.j2`, `files/qbittorrent/qBittorrent.conf.backup`, `tasks/qbittorrent-webui-config.yml` |
| **`.env` keys** | `QBITTORRENT_WEBUI_USERNAME`, `QBITTORRENT_WEBUI_PASSWORD`, `QBITTORRENT_WEBUI_PORT`, `QBITTORRENT_LAN_AUTH_BYPASS` |
| **Configured by Ansible** | WebUI username/password (PBKDF2), port, LAN auth bypass (auto-detects `traefik_network` subnet), full baseline config on **fresh** install |
| **Still outside Ansible** | On existing installs: BitTorrent session settings (interface `tun0`, tags, paths) patched only in template for new installs — UI changes preserved on re-deploy; Sonarr/Radarr download-client link |
| **Next steps** | Optional: template VPN interface + save paths; API task to register qBittorrent as download client in Sonarr/Radarr/Prowlarr |

---

### Prowlarr — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-prowlarr.yml` |
| **In `deploy-services.yml`** | Yes (after qBittorrent) |
| **Ansible sources** | `tasks/bootstrap-prowlarr.yml` |
| **`homelab.yaml` keys** | `prowlarr.indexers` (Cardigann definitions, credentials for private indexers) |
| **Configured by Ansible** | Backs up `services/prowlarr/`; indexers from yaml; Sonarr/Radarr pull via Torznab (no Applications sync) |
| **Still outside Ansible** | Indexer health history, download client settings |
| **Fresh stand-up** | Set indexers in `homelab.yaml`, run after Gluetun stack is up |

---

### Sonarr — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-sonarr.yml` |
| **In `deploy-services.yml`** | Yes (after Prowlarr) |
| **Ansible sources** | Sonarr bootstrap from `homelab.yaml` (root folders, indexers, download clients, naming, quality profiles) |
| **`homelab.yaml` keys** | `sonarr.volumes`, `sonarr.root_folders`, `sonarr.indexers`, `sonarr.naming`, `sonarr.quality_*`, `qbittorrent.webui_*` |
| **Configured by Ansible** | Backs up `services/sonarr/`; Prowlarr Torznab indexers; qBittorrent download client; optional library import |
| **Still outside Ansible** | Series metadata, download queue state |
| **Fresh stand-up** | Deploy Prowlarr first; indexers in `sonarr.indexers` must match Prowlarr indexer names |

---

### Radarr — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-radarr.yml` |
| **In `deploy-services.yml`** | Yes (after Sonarr) |
| **Ansible sources** | Radarr bootstrap from `homelab.yaml` |
| **`homelab.yaml` keys** | `radarr.volumes`, `radarr.root_folders`, `radarr.indexers`, `radarr.naming`, `radarr.quality_*`, `qbittorrent.webui_*` |
| **Configured by Ansible** | Backs up `services/radarr/`; Prowlarr Torznab indexers; qBittorrent; naming/media/quality profiles; optional library import |
| **Still outside Ansible** | Movie metadata, download queue state |
| **Fresh stand-up** | Same pattern as Sonarr — Prowlarr indexers referenced by name |

---

### Bazarr — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-bazarr.yml` |
| **In `deploy-services.yml`** | Yes (after Radarr) |
| **Ansible sources** | Bazarr bootstrap from `homelab.yaml` |
| **`homelab.yaml` keys** | `bazarr.volumes`, `bazarr.sonarr`, `bazarr.radarr`, `bazarr.languages`, `bazarr.providers` |
| **Configured by Ansible** | Backs up `services/bazarr/`; links to Sonarr/Radarr; language profiles + subtitle providers |
| **Still outside Ansible** | Subtitle download history, manual subtitle edits |
| **Fresh stand-up** | Deploy Sonarr + Radarr first |

---

### Jellyfin — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-jellyfin.yml` |
| **In `deploy-services.yml`** | Yes |
| **Ansible sources** | `scripts/bootstrap_jellyfin.py`, `scripts/bootstrap_jellyfin_plugins.py`, `vars/jellyfin_plugins.yml`, `templates/jellyfin/` |
| **`homelab.yaml` keys** | `jellyfin.libraries`, `jellyfin.admin_*`, `jellyfin.server_name`, `authelia.oidc_client_secret`, `DOMAIN` |
| **Configured by Ansible** | Backs up `services/jellyfin/` before changes; libraries, server name, branding/CSS, plugins (Intro Skipper, SSO, TVDB, TMDb Box Sets, Trakt shell), VAAPI encoding, Live TV M3U → Dispatcharr, API key `ansible` |
| **Still outside Ansible** | Trakt OAuth link, extra Jellyfin users beyond admin (SSO creates on login), Les Mills `homevideos` folder browse quirk |

---

### Homepage — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-homepage.yml` |
| **In `deploy-services.yml`** | Yes (last) |
| **Ansible sources** | `templates/homepage/services.yaml.j2`, `files/homepage/{bookmarks,settings,widgets,docker,proxmox,kubernetes}.yaml` |
| **`.env` keys** | `DOMAIN`, `DISPATCHARR_ADMIN_*`, `HOMEPAGE_*_API_KEY` (except Jellyfin + Gluetun — auto) |
| **Configured by Ansible** | Service list with widget URLs/keys; Jellyfin widget key named `homepage` read/created in `jellyfin.db`; bookmarks, settings, widgets, docker/proxmox/kubernetes stubs |
| **Still in Compose only** | `HOMEPAGE_ALLOWED_HOSTS`, Kuma labels, image version |
| **Fresh stand-up** | Create per-app API keys in each service UI (except Jellyfin), set remaining `HOMEPAGE_*` in `.env`, run `deploy-homepage.yml` after Jellyfin has started once |

---

### Uptime Kuma — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-uptime-kuma.yml` |
| **In `deploy-services.yml`** | Yes (before Autokuma) |
| **Ansible sources** | `vars/uptime_kuma_status_page.yml`, `templates/uptime-kuma/status-page.json.j2`, `scripts/sync_uptime_kuma_status_page.py` |
| **`.env` keys** | None required |
| **Configured by Ansible** | Container via Compose; waits for health; first-install bootstrap (`disableAuth=true`) |
| **Configured via AutoKuma + Compose** | Individual monitors from `kuma.*` labels on each service |
| **Still outside Ansible** | Notification channels, incidents, maintenance windows, dashboard-only settings in SQLite |
| **Fresh stand-up** | Wipe `services/uptime-kuma/data/*`, run `deploy-uptime-kuma.yml` (SQLite via `UPTIME_KUMA_DB_TYPE`, bootstrap disables dashboard auth), then `deploy-autokuma.yml` |

---

### Autokuma — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-autokuma.yml` |
| **In `deploy-services.yml`** | Yes (after Uptime Kuma) |
| **Ansible sources** | `tasks/sync-uptime-kuma-status-page.yml`, `vars/uptime_kuma_status_page.yml` |
| **`.env` keys** | None required (auto-login when `disableAuth=true`) |
| **Configured by Ansible** | Autokuma container; status page layout (`Services` / `Arr` / `System` on slug `default` for Homepage widget) |
| **Configured via Compose labels** | Monitor definitions (`kuma.<id>.http|docker|port.*` on each service) |
| **Still outside Ansible** | `services/autokuma/data/` state DB (monitor ID mapping) |
| **Fresh stand-up** | Run after `deploy-uptime-kuma.yml` (bootstrap disables dashboard auth); ensure `kuma.*` labels in `compose.yaml` |

---

### Memos — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-memos.yml` |
| **In `deploy-services.yml`** | Yes (after Autokuma) |
| **Ansible sources** | `templates/memos/memos-idp-authelia.json.j2`, `memos-instance-setting-general.json.j2`, `memos-instance-setting-access.json.j2` |
| **`.env` keys** | `DOMAIN`, `OIDC_CLIENT_SECRET`, `MEMOS_ADMIN_USERNAME`, `MEMOS_ADMIN_PASSWORD` |
| **Configured by Ansible** | SSO-only login (`disallowPasswordAuth`), private access mode, Authelia OAuth2 IdP via `/etc/secrets`; instance admin bootstrapped from `.env` on first install; `MEMOS_INSTANCE_URL` in Compose |
| **Still in Compose only** | Traefik labels, Kuma labels, image version |
| **Still outside Ansible** | Memos, tags, attachments in SQLite (`memos_prod.db`); memo content and user accounts |
| **Existing install note** | A UI-configured IdP with the same `uid` (`authelia`) is shadowed by the file and ignored at runtime. Remove the stored provider in Memos admin if you remove the secrets file later, or the old DB row will reappear. |
| **Fresh stand-up** | Set `OIDC_CLIENT_SECRET`, `MEMOS_ADMIN_USERNAME`, and `MEMOS_ADMIN_PASSWORD`, run `deploy-authelia.yml` then `deploy-memos.yml`. Ansible creates the admin account on first install (skips setup wizard); main login shows Authelia SSO. Local admin: `https://notes.<domain>/auth/admin`. |

---

### Audiobookshelf — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-audiobookshelf.yml` |
| **In `deploy-services.yml`** | Yes (after Memos) |
| **Ansible sources** | `scripts/bootstrap_audiobookshelf.py`, volume/library config from `homelab.yaml` |
| **`homelab.yaml` keys** | `audiobookshelf.volumes`, `audiobookshelf.libraries`, `root_username`, `root_password`, `authelia.oidc_client_secret`, `DOMAIN` |
| **Configured by Ansible** | Backs up `services/audiobookshelf/`; libraries + OIDC auth settings via API bootstrap |
| **Still outside Ansible** | Audiobook metadata, playback progress, user accounts beyond bootstrap |
| **Fresh stand-up** | Set libraries/volumes + root creds in `homelab.yaml`, run after `deploy-authelia.yml` |

---

### Mealie — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-mealie.yml` |
| **In `deploy-services.yml`** | Yes (after Audiobookshelf) |
| **Ansible sources** | `tasks/bootstrap-mealie.yml` |
| **`homelab.yaml` keys** | `mealie.admin_*`, `mealie.openai_api_key` (optional), `authelia.oidc_client_secret`, `DOMAIN` |
| **Configured by Ansible** | Backs up `services/mealie/`; Authelia OIDC (password login hidden); service admin for Homepage; optional OpenAI group provider |
| **Still outside Ansible** | Recipes, images, households in SQLite |
| **Fresh stand-up** | Set `mealie.admin_*` + OIDC secret, run after Authelia. OIDC groups: `mealie-admins` / `mealie-users`. |

---

### Paperless — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-paperless.yml` |
| **In `deploy-services.yml`** | Yes (after Mealie) |
| **Ansible sources** | `templates/paperless/compose.env.j2`, `tasks/ensure-paperless-secret-key.yml`, `tasks/ensure-paperless-date-locale.yml`, OIDC client in `vars/authelia_oidc_clients.yml` |
| **`homelab.yaml` keys** | `paperless.admin_*`, `paperless.db_password`, `paperless.ocr_language`, `authelia.oidc_client_secret`, `DOMAIN` |
| **Configured by Ansible** | Valkey + PostgreSQL + app stack; auto-generated `secret_key`; Authelia OIDC always on; group sync (`paperless-admin` superuser); UK date locale (`en-gb`) + `PAPERLESS_DATE_ORDER=DMY`; break-glass admin with no email (OIDC-safe) |
| **Backup / restore** | `homelab backup paperless` — files + `postgres.dump`; `homelab restore paperless <id> --yes` |
| **Still outside Ansible** | Documents, tags, matching rules, correspondents (create in UI); Paperless groups must match Authelia group names |
| **Fresh stand-up** | Set `paperless.*` in `homelab.yaml`, run after Authelia. Enable SSO in Paperless Settings → Security on first login if needed. |

---

### Jellyscope — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-jellyscope.yml` |
| **In `deploy-services.yml`** | Yes (after Jellyfin) |
| **Ansible sources** | `scripts/ensure_jellyfin_api_key.py`, `scripts/bootstrap_jellyscope.py` |
| **`.env` keys** | `JELLYSCOPE_SECRET_KEY`, `JELLYSCOPE_ADMIN_USERNAME`, `JELLYSCOPE_ADMIN_PASSWORD` |
| **Configured by Ansible** | Backs up `services/jellyscope/data/` to `backups/jellyscope/<timestamp>/` before changes; reads or creates Jellyfin API key named `jellyscope` in `jellyfin.db`; bootstraps admin + Jellyfin URL/key in SQLite |
| **Still in Compose only** | Traefik labels, Kuma labels, media mounts, image build |
| **Still outside Ansible** | Scan cache (`imagecache/`), playback history in SQLite |
| **Sign-up policy** | No public registration — `/setup` runs only when zero accounts exist; after bootstrap only admins add users in Settings |
| **Fresh stand-up** | Set `.env` keys, run after `deploy-jellyfin.yml`. Wipe test: `rm -rf services/jellyscope/data/*` then re-run playbook |

---

## Services without deploy playbooks (remaining)

| Service | Config location | Suggested `deploy-*` scope |
| --- | --- | --- |
| **Seerr** | `services/seerr/config/` | `deploy-seerr.yml` — Jellyfin link, Sonarr/Radarr, OIDC |
| **Sparky Fitness** | DB + uploads + Compose env | `deploy-sparkyfitness.yml` — DB passwords, auth secrets from `homelab.yaml` |
| **McClean** | `services/mccleanengineering/data/` | `deploy-mcclean.yml` — `mcclean.admin_*` from `homelab.yaml`. **If login fails** with `readonly database`: stop container, delete `data.db-wal` + `data.db-shm`, restart |

---

## Suggested migration order

Most services are done. Remaining work:

1. ~~**Authelia + Traefik**~~ — done
2. ~~**Uptime Kuma + Autokuma**~~ — done
3. ~~**OIDC apps** (Memos, Audiobookshelf, Mealie, Paperless)~~ — done
4. ~~**Gluetun + *arr stack** (Prowlarr → Sonarr → Radarr → Bazarr + qBittorrent)~~ — done
5. ~~**Dispatcharr + Jellyfin + Jellyscope**~~ — done
6. ~~**Homepage**~~ — done (includes Paperless tile)
7. **Seerr** — depends on Jellyfin + *arr (next priority)
8. **Sparky Fitness / McClean** — as needed

---

## Checklist template (copy per service)

Use this when starting a new `deploy-<service>.yml`:

```markdown
### <Service> — ⬜ / 🟡 / ✅

- [ ] `playbooks/deploy-<service>.yml` created
- [ ] Added to `deploy-services.yml`
- [ ] `.env.example` updated with required keys
- [ ] Static files in `files/<service>/`
- [ ] Templates in `templates/<service>/`
- [ ] Secrets only in `.env` (playbook uses `no_log` where needed)
- [ ] Idempotent (safe to re-run)
- [ ] Restarts container when config changes
- [ ] Documented in `README.md` + this file
- [ ] Tested: wipe `services/<service>/`, run playbook, verify UI/API
```

---

## Notes

- **Compose vs Ansible**: Per-service Traefik router labels, Kuma labels, and image versions stay in `compose.yaml`. Ansible owns static Traefik config, Authelia middleware, and app config under `services/<app>/`.
- **Gluetun sidecars**: Any playbook that recreates Gluetun should use `tasks/start-gluetun-stack.yml` so qBittorrent/Sonarr/Radarr/Prowlarr/Bazarr stay attached to the same network namespace.
- **Dispatcharr ↔ Jellyfin**: Deploy Dispatcharr (M3U output) before Jellyfin Live TV.
- **Homepage widget keys**: Many `HOMEPAGE_*_API_KEY` values are created in each app's UI — consider Ansible tasks that read/create API keys via each app's API during deploy.
- **Trilium**: Mentioned in root `README.md` but not in current `compose.yaml` — add a deploy playbook if/when it returns to the stack.
