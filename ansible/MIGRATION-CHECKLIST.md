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
ansible-playbook playbooks/deploy-traefik.yml      # edge config; before Authelia middleware goes live
ansible-playbook playbooks/deploy-authelia.yml     # auth; needs Docker networks from site.yml
ansible-playbook playbooks/deploy-gluetun.yml      # VPN before *arr / qBittorrent
ansible-playbook playbooks/deploy-dispatcharr.yml  # IPTV; before Jellyfin Live TV
ansible-playbook playbooks/deploy-qbittorrent.yml  # WebUI on gluetun network
ansible-playbook playbooks/deploy-jellyfin.yml     # M3U tuner → Dispatcharr
ansible-playbook playbooks/deploy-homepage.yml     # widgets last
```

**Why order matters**

| Playbook | Depends on |
| --- | --- |
| `site.yml` | — (run first: containers + `traefik_network` / `socket_proxy`) |
| `deploy-traefik.yml` | `site.yml` |
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
| **Traefik** | `deploy-traefik.yml` | **Yes** — static config + Authelia forward-auth middleware; `acme.json` is runtime |
| **Authelia** | `deploy-authelia.yml` | **Yes** — `users.yml` + `configuration.yml` templated; SQLite DB + notification log are auto-created at runtime (not Ansible todos) |
| **Dispatcharr** | `deploy-dispatcharr.yml` | **Yes** — admin, M3U/XC provider, XC password, EPL/sports channel groups, auto channel sync |
| **Gluetun** | `deploy-gluetun.yml` | **Yes** — VPN settings in `.env`, HTTP control-server auth in `config.toml`; ports/Traefik labels stay in Compose |
| **Jellyfin** | `deploy-jellyfin.yml` | **No** — Live TV + branding/CSS only; libraries, users, OIDC, transcoding, plugins still manual |
| **qBittorrent** | `deploy-qbittorrent.yml` | **Mostly for WebUI** — port + LAN auth bypass; BitTorrent session prefs intentionally left to UI on existing installs |
| **Homepage** | `deploy-homepage.yml` | **Mostly** — service list + widgets; `bookmarks.yaml` referenced but missing from `files/homepage/` |

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

### Traefik — ✅

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-traefik.yml` |
| **In `deploy-services.yml`** | Yes (first) |
| **Ansible sources** | `templates/traefik/traefik.yml.j2`, `templates/traefik/dynamic/authelia.yml.j2` |
| **`.env` keys** | `DOMAIN`, `ACME_EMAIL`, `CLOUDFLARE_API_TOKEN` |
| **Configured by Ansible** | Entrypoints, HTTP→HTTPS redirect, Docker + file providers, Cloudflare ACME resolver, Authelia `forwardAuth` middleware, dashboard route |
| **Still in Compose only** | Per-service router labels, Kuma labels, image version, port 80/443 publish |
| **Auto-managed at runtime (not Ansible)** | `acme.json` — Let's Encrypt certificates; created/renewed by Traefik |
| **Fresh stand-up** | Set Traefik/DNS vars in `.env`, run `deploy-traefik.yml`, then `docker compose up -d traefik` |

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
| **`.env` keys** | `DISPATCHARR_ADMIN_*`, `DISPATCHARR_M3U_*`, `DISPATCHARR_XC_PASSWORD` |
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
| **`.env` keys** | `DOMAIN`, `JELLYFIN_API_KEY` |
| **Configured by Ansible** | Custom CSS (Intro Skipper styling, Authelia SSO button), Live TV M3U tuner → Dispatcharr, remove legacy HDHomeRun tuner, channel re-import on livetv.xml change |
| **Still outside Ansible** | Media libraries + folder paths, users, OIDC (`OIDC_CLIENT_SECRET`), transcoding/HW accel, plugins, server name, remote access, collections, most `system.xml` / `encoding.xml` |
| **Next steps** | Template `system.xml` / network settings; API or templated library paths from `MEDIA1_DIR` / `MEDIA2_DIR`; OIDC provider block; Intro Skipper plugin config if file-based |

---

### Homepage — 🟡

| | |
| --- | --- |
| **Playbook** | `playbooks/deploy-homepage.yml` |
| **In `deploy-services.yml`** | Yes |
| **Ansible sources** | `templates/homepage/services.yaml.j2`, `files/homepage/{settings,widgets,docker,proxmox,kubernetes}.yaml` |
| **`.env` keys** | `DOMAIN`, `DISPATCHARR_ADMIN_*`, `GLUETUN_API_KEY`, all `HOMEPAGE_*_API_KEY`, `HOMEPAGE_TRAEFIK_*` |
| **Configured by Ansible** | Service list with widget URLs/keys, static YAML configs |
| **Still outside Ansible** | **`bookmarks.yaml` missing** from `files/homepage/` (playbook references it — add file or remove from loop); `HOMEPAGE_ALLOWED_HOSTS` still hardcoded in Compose |
| **Next steps** | Add `files/homepage/bookmarks.yaml`; move allowed hosts to `.env`; template any per-service widget creds still hardcoded |

---

## Services without deploy playbooks (todo)

Priority suggestion: **Authelia + Traefik** (auth edge) → ***arr stack** (Sonarr/Radarr/Prowlarr/Bazarr) → **Seerr** → OIDC apps → rest.

### Core / edge

| Service | Compose only today | Config location | Suggested `deploy-*` scope |
| --- | --- | --- | --- |
| **Traefik** | ✅ | `services/traefik/traefik.yml`, `dynamic/authelia.yml`, `acme/acme.json` | `deploy-traefik.yml` — static + Authelia middleware; per-service routes stay on Compose labels |
| **Authelia** | ✅ | `services/authelia/config/configuration.yml`, `users.yml` | `deploy-authelia.yml` — config done; `db.sqlite3` / `notification.txt` auto-created at runtime |
| **Cloudflare DDNS** | ⬜ | Compose env | `deploy-cloudflare-ddns.yml` — likely env-only, low priority |
| **Socket proxy** | ⬜ | Compose only | Skip — no app config |
| **Watchtower** | ⬜ | Compose only | Skip — no app config |

### Monitoring / ops

| Service | Compose only today | Config location | Suggested `deploy-*` scope |
| --- | --- | --- | --- |
| **Uptime Kuma** | ⬜ | `services/uptime-kuma/data/` (SQLite) | `deploy-uptime-kuma.yml` — monitors from Compose `kuma.*` labels + API; backup/restore strategy |
| **Autokuma** | ⬜ | `services/autokuma/data/` | `deploy-autokuma.yml` — pair with Kuma URL/API key from `.env` |
| **Dozzle** | ⬜ | Compose only | Skip or env-only |

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
| **Wallos** | ⬜ | `services/wallos/db/` | `deploy-wallos.yml` — OIDC, currency/settings |

### Other apps

| Service | Compose only today | Config location | Suggested `deploy-*` scope |
| --- | --- | --- | --- |
| **Jellyscope** | ⬜ | `services/jellyscope/data/` | `deploy-jellyscope.yml` — `JELLYSCOPE_SECRET_KEY`, Jellyfin connection |
| **Sparky Fitness** | ⬜ | DB + uploads + Compose env | `deploy-sparkyfitness.yml` — DB passwords, auth secrets from `.env` (many keys already in `.env`) |
| **Memos** | ⬜ | `services/memos/` | `deploy-memos.yml` — low priority |
| **McClean** | ⬜ | `services/mccleanengineering/data/` | `deploy-mcclean.yml` — `MCCLEAN_ADMIN_*` from `.env`. **If login fails after migration** with `readonly database`: stop container, delete `data.db-wal` + `data.db-shm`, restart |

---

## Suggested migration order

Work top-to-bottom; each step should leave the stack usable.

1. **Authelia** — everything depends on SSO
2. ~~**Traefik**~~ — done (static + Authelia middleware in Ansible; service routes stay on Compose labels)
3. **Homepage** — fix missing `bookmarks.yaml`; quick win
4. ~~**Gluetun**~~ — done (VPN in `.env`, auth roles in Ansible)
5. **Sonarr → Radarr → Prowlarr → Bazarr** — *arr chain; share patterns (API + `config.xml` snippets)
6. **Seerr** — depends on Jellyfin + *arr
7. **Jellyfin** — libraries, OIDC, encoding (biggest remaining gap)
8. **Audiobookshelf / Mealie / Wallos** — OIDC clients overlap with Authelia work
9. **Uptime Kuma + Autokuma** — mostly derived from existing Compose labels
10. **Sparky Fitness / Jellyscope / McClean / Memos** — as needed

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
