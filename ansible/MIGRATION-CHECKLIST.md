# Ansible migration checklist

Step through services one at a time until each has a `deploy-<service>.yml` playbook that stands up the service **and** applies as much configuration as possible. Goal: wipe `services/<app>/`, run Ansible, and avoid manual UI setup.

**Pattern for each service:**

1. Add `playbooks/deploy-<service>.yml`
2. Put secrets in `.env` / `.env.example` (never commit secrets to Ansible)
3. Put static config in `files/<service>/`
4. Put templated config in `templates/<service>/*.j2`
5. Import the playbook from `playbooks/deploy-services.yml` when ready
6. Document required `.env` keys in this file and `README.md`

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

Or step through individually (same order as `deploy-services.yml`):

```bash
ansible-playbook playbooks/deploy-socket-proxy.yml     # Docker API proxy; before Traefik
ansible-playbook playbooks/deploy-watchtower.yml       # auto-updates
ansible-playbook playbooks/deploy-dozzle.yml          # container logs UI
ansible-playbook playbooks/deploy-traefik.yml          # edge config
ansible-playbook playbooks/deploy-cloudflare-ddns.yml  # DNS records from .env
ansible-playbook playbooks/deploy-authelia.yml         # auth; needs Docker networks from site.yml
ansible-playbook playbooks/deploy-gluetun.yml          # VPN before *arr / qBittorrent
ansible-playbook playbooks/deploy-dispatcharr.yml      # IPTV; before Jellyfin Live TV
ansible-playbook playbooks/deploy-qbittorrent.yml      # WebUI on gluetun network
ansible-playbook playbooks/deploy-jellyfin.yml         # M3U tuner → Dispatcharr
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
| `deploy-jellyfin.yml` | Dispatcharr M3U populated at `http://dispatcharr:9191/output/m3u/` |
| `deploy-homepage.yml` | Nothing hard — deploy last so widget URLs match live services |

---

## Summary — your question

| Service | Playbook | Fully configured? |
| --- | --- | --- |
| **Socket Proxy** | `deploy-socket-proxy.yml` | **Yes** — API filter flags in `.env`; no on-disk config |
| **Watchtower** | `deploy-watchtower.yml` | **Yes** — poll/cleanup settings in `.env`; no on-disk config |
| **Dozzle** | `deploy-dozzle.yml` | **Yes** — log viewer settings in `.env`; no on-disk config |
| **Traefik** | `deploy-traefik.yml` | **Yes** — static config + Authelia forward-auth middleware; `acme.json` is runtime |
| **Cloudflare DDNS** | `deploy-cloudflare-ddns.yml` | **Yes** — settings in `.env`; no on-disk config |
| **Authelia** | `deploy-authelia.yml` | **Yes** — `users.yml` + `configuration.yml` templated; SQLite DB + notification log are auto-created at runtime (not Ansible todos) |
| **Dispatcharr** | `deploy-dispatcharr.yml` | **Yes** — admin, M3U/XC provider, XC password, EPL/sports channel groups, auto channel sync |
| **Gluetun** | `deploy-gluetun.yml` | **Yes** — VPN settings in `.env`, HTTP control-server auth in `config.toml`; ports/Traefik labels stay in Compose |
| **Jellyfin** | `deploy-jellyfin.yml` | **No** — Live TV + branding/CSS only; libraries, users, OIDC, transcoding, plugins still manual |
| **qBittorrent** | `deploy-qbittorrent.yml` | **Mostly for WebUI** — port + LAN auth bypass; BitTorrent session prefs intentionally left to UI on existing installs |
| **Homepage** | `deploy-homepage.yml` | **Yes** — service list + widgets from `.env`; static YAML including `bookmarks.yaml` |

---

## Infrastructure (already in Ansible)

| Playbook | Purpose | Status |
| --- | --- | --- |
| `site.yml` | `ensure-service-dirs` + `docker compose up` | 🔧 Done |
| `ensure-service-dirs.yml` | Create `services/*` volume tree | 🔧 Done |
| `deploy-services.yml` | Orchestrates all `deploy-*` app playbooks | 🔧 Done (grows as you add playbooks) |
| `tasks/load-env.yml` | Parse repo `.env` → `homelab_env` | 🔧 Done |
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
| **`.env` keys** | VPN: `GLUETUN_API_KEY`, `VPN_*`, `WIREGUARD_*`, `SERVER_CITIES`, `GLUETUN_DOT`, `GLUETUN_DNS_ADDRESS`, `FIREWALL_OUTBOUND_SUBNETS`. Ports: `GLUETUN_PORT_*`, `SONARR_PORT`, `RADARR_PORT`, `PROWLARR_PORT`, `BAZARR_PORT`, `QBITTORRENT_WEBUI_PORT` |
| **Configured by Ansible** | HTTP control-server API key roles (Homepage widget, local app routes) |
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

### Jellyfin — 🟡

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-jellyfin.yml` |
| **In `deploy-services.yml`** | Yes |
| **Ansible sources** | `templates/jellyfin/branding.xml.j2`, `templates/jellyfin/livetv.xml.j2`, `files/jellyfin/custom.css`, `files/jellyfin/livetv-channels-list.css` |
| **`.env` keys** | `DOMAIN` |
| **Configured by Ansible** | Custom CSS (Intro Skipper styling, Authelia SSO button), Live TV M3U tuner → Dispatcharr, remove legacy HDHomeRun tuner, channel re-import on livetv.xml change; API key named `ansible` read from `jellyfin.db` or created automatically |
| **Still outside Ansible** | Media libraries + folder paths, users, OIDC (`OIDC_CLIENT_SECRET`), transcoding/HW accel, plugins, server name, remote access, collections, most `system.xml` / `encoding.xml` |
| **Next steps** | Template `system.xml` / network settings; API or templated library paths from `MEDIA1_DIR` / `MEDIA2_DIR`; OIDC provider block; Intro Skipper plugin config if file-based |

---

### Homepage — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-homepage.yml` |
| **In `deploy-services.yml`** | Yes (last) |
| **Ansible sources** | `templates/homepage/services.yaml.j2`, `files/homepage/{bookmarks,settings,widgets,docker,proxmox,kubernetes}.yaml` |
| **`.env` keys** | `DOMAIN`, `DISPATCHARR_ADMIN_*`, `GLUETUN_API_KEY`, `HOMEPAGE_*_API_KEY` (except Jellyfin — auto from `jellyfin.db`) |
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

### Jellyscope — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-jellyscope.yml` |
| **In `deploy-services.yml`** | Yes (after Jellyfin) |
| **Ansible sources** | `scripts/ensure_jellyfin_api_key.py`, `scripts/bootstrap_jellyscope.py` |
| **`.env` keys** | `JELLYSCOPE_SECRET_KEY`, `JELLYSCOPE_ADMIN_USERNAME`, `JELLYSCOPE_ADMIN_PASSWORD` |
| **Configured by Ansible** | Backs up `services/jellyscope/data/` before changes; reads or creates Jellyfin API key named `jellyscope` in `jellyfin.db`; bootstraps admin + Jellyfin URL/key in SQLite |
| **Still in Compose only** | Traefik labels, Kuma labels, media mounts, image build |
| **Still outside Ansible** | Scan cache (`imagecache/`), playback history in SQLite |
| **Sign-up policy** | No public registration — `/setup` runs only when zero accounts exist; after bootstrap only admins add users in Settings |
| **Fresh stand-up** | Set `.env` keys, run after `deploy-jellyfin.yml`. Wipe test: `rm -rf services/jellyscope/data/*` then re-run playbook |

---

## Services without deploy playbooks (todo)

Priority suggestion: **Authelia + Traefik** (auth edge) → ***arr stack** (Sonarr/Radarr/Prowlarr/Bazarr) → **Seerr** → OIDC apps → rest.

### Core / edge

| Service | Compose only today | Config location | Suggested `deploy-*` scope |
| --- | --- | --- | --- |
| **Traefik** | ✅ | `services/traefik/traefik.yml`, `dynamic/authelia.yml`, `acme/acme.json` | `deploy-traefik.yml` — static + Authelia middleware; per-service routes stay on Compose labels |
| **Authelia** | ✅ | `services/authelia/config/configuration.yml`, `users.yml` | `deploy-authelia.yml` — config done; `db.sqlite3` / `notification.txt` auto-created at runtime |
| **Cloudflare DDNS** | ✅ | `.env` only | `deploy-cloudflare-ddns.yml` — DNS record settings in `.env` |
| **Socket proxy** | ✅ | `.env` only | `deploy-socket-proxy.yml` — Docker API filter flags |
| **Watchtower** | ✅ | `.env` only | `deploy-watchtower.yml` — poll interval, cleanup, label enable |

### Monitoring / ops

| Service | Compose only today | Config location | Suggested `deploy-*` scope |
| --- | --- | --- | --- |
| **Uptime Kuma** | ✅ | `services/uptime-kuma/data/` (SQLite) | `deploy-uptime-kuma.yml` — container + status page API sync |
| **Autokuma** | ✅ | `services/autokuma/data/` | `deploy-autokuma.yml` — label sync + status page groups |
| **Dozzle** | ✅ | `.env` only | `deploy-dozzle.yml` — log level, filter, Socket Proxy host, forward-auth header |

### Media stack (*arr + requests)

| Service | Compose only today | Config location | Suggested `deploy-*` scope |
| --- | --- | --- | --- |
| **Sonarr** | ⬜ | `services/sonarr/config/config.xml` + DB | `deploy-sonarr.yml` — root folders, qBittorrent download client, Prowlarr indexer sync, API key → `.env` for Homepage/Kuma |
| **Radarr** | ⬜ | `services/radarr/config/config.xml` + DB | `deploy-radarr.yml` — same pattern as Sonarr |
| **Prowlarr** | ⬜ | `services/prowlarr/config/config.xml` + DB | `deploy-prowlarr.yml` — indexers, app sync to Sonarr/Radarr |
| **Bazarr** | ⬜ | `services/bazarr/config/` | `deploy-bazarr.yml` — language profiles, links to Sonarr/Radarr |
| **Seerr** | ⬜ | `services/seerr/config/` | `deploy-seerr.yml` — Jellyfin/Plex link, Sonarr/Radarr, OIDC |

### Media apps

| Service | Compose only today | Config location | Suggested `deploy-*` scope |
| --- | --- | --- | --- |
| **Audiobookshelf** | ⬜ | `services/audiobookshelf/config/` | `deploy-audiobookshelf.yml` — libraries from `AUDIOBOOKS_DIR`, OIDC |
| **Mealie** | ⬜ | `services/mealie/data/` | `deploy-mealie.yml` — OIDC, OpenAI key from `.env`, default group |

### Other apps

| Service | Compose only today | Config location | Suggested `deploy-*` scope |
| --- | --- | --- | --- |
| **Jellyscope** | ✅ | `services/jellyscope/data/` | `deploy-jellyscope.yml` — admin from `.env`, Jellyfin key auto-ensured |
| **Sparky Fitness** | ⬜ | DB + uploads + Compose env | `deploy-sparkyfitness.yml` — DB passwords, auth secrets from `.env` (many keys already in `.env`) |
| **Memos** | ✅ | `services/memos/secrets/` + SQLite | `deploy-memos.yml` — Authelia OIDC via `/etc/secrets` |
| **McClean** | ⬜ | `services/mccleanengineering/data/` | `deploy-mcclean.yml` — `MCCLEAN_ADMIN_*` from `.env`. **If login fails after migration** with `readonly database`: stop container, delete `data.db-wal` + `data.db-shm`, restart |

---

## Suggested migration order

Work top-to-bottom; each step should leave the stack usable.

1. **Authelia** — everything depends on SSO
2. ~~**Traefik**~~ — done (static + Authelia middleware in Ansible; service routes stay on Compose labels)
3. ~~**Homepage**~~ — done (services template + static YAML + widget keys in `.env`)
4. ~~**Gluetun**~~ — done (VPN in `.env`, auth roles in Ansible)
5. **Sonarr → Radarr → Prowlarr → Bazarr** — *arr chain; share patterns (API + `config.xml` snippets)
6. **Seerr** — depends on Jellyfin + *arr
7. **Jellyfin** — libraries, OIDC, encoding (biggest remaining gap)
8. **Audiobookshelf / Mealie** — OIDC clients overlap with Authelia work
9. ~~**Uptime Kuma + Autokuma**~~ — done (AutoKuma monitors from labels; Ansible syncs `/status/default` groups)
10. ~~**Memos**~~ — done (Authelia OIDC via `/etc/secrets`)
11. ~~**Jellyscope**~~ — done (admin + Jellyfin key from Ansible)
12. **Sparky Fitness / McClean** — as needed

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
