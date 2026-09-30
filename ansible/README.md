# Homelab Ansible

Ansible playbooks for deploying and bootstrapping the homelab stack. **Secrets stay in `homelab.yaml`** (gitignored at repo root); nothing sensitive is stored in this directory.

Prefer the **`homelab` CLI** from the repo root (`./bin/homelab deploy …`) — it renders `compose.yaml` before running playbooks.

For a per-service migration tracker (what's done, what's todo, suggested order), see **[MIGRATION-CHECKLIST.md](MIGRATION-CHECKLIST.md)**.

## Prerequisites

```bash
sudo apt install python3-yaml ansible-core
cd ansible
ansible-galaxy collection install -r requirements.yml
```

Ensure `homelab.yaml` exists at the repo root (copy from `homelab.example.yaml`).

Optional: override the repo path when running from elsewhere:

```bash
export HOMELAB_DIR=/home/mike/Documents/homelab
```

## Playbooks

| Playbook | Purpose |
| --- | --- |
| `playbooks/site.yml` | Ensure `services/` dirs + deploy the full Docker Compose stack |
| `playbooks/ensure-service-dirs.yml` | Create `services/` directory tree only (no Compose) |
| `playbooks/deploy-socket-proxy.yml` | Validate Socket Proxy `.env` settings and apply container config |
| `playbooks/deploy-watchtower.yml` | Validate Watchtower `.env` settings and apply container config |
| `playbooks/deploy-dozzle.yml` | Validate Dozzle `.env` settings and apply container config |
| `playbooks/deploy-traefik.yml` | Render Traefik static config + Authelia forward-auth middleware |
| `playbooks/deploy-cloudflare-ddns.yml` | Validate Cloudflare DDNS `.env` settings and apply container config |
| `playbooks/deploy-authelia.yml` | Render Authelia `users.yml` + `configuration.yml` from `homelab.yaml` and vars |
| `playbooks/deploy-uptime-kuma.yml` | Start Uptime Kuma; wait for health |
| `playbooks/deploy-autokuma.yml` | Start Autokuma; sync public status page groups via Kuma API |
| `playbooks/deploy-memos.yml` | Render Memos Authelia OIDC config to `/etc/secrets`; apply Compose |
| `playbooks/deploy-audiobookshelf.yml` | Media mounts, libraries, Authelia OIDC bootstrap; backs up full service dir |
| `playbooks/deploy-dispatcharr.yml` | Bootstrap admin + M3U/XC provider + logical channel groups (idempotent) |
| `playbooks/deploy-gluetun.yml` | Render Gluetun `config.toml` from template + `.env` |
| `playbooks/deploy-qbittorrent.yml` | Apply qBittorrent WebUI credentials, port + LAN auth bypass from `.env` |
| `playbooks/deploy-prowlarr.yml` | Prowlarr external auth (hardcoded) + Cardigann indexers from `homelab.yaml`; backs up full service dir |
| `playbooks/deploy-radarr.yml` | Radarr volumes, root folders, Prowlarr indexers, qBittorrent, profiles from `homelab.yaml`; backs up full service dir |
| `playbooks/deploy-homepage.yml` | Deploy Homepage config from Ansible templates + `.env` |
| `playbooks/deploy-jellyfin.yml` | Deploy Jellyfin config (branding, CSS, M3U tuner, Live TV list layout) |
| `playbooks/deploy-jellyscope.yml` | Bootstrap Jellyscope admin + ensure Jellyfin API key; sync connection settings |
| `playbooks/deploy-services.yml` | All deploy playbooks in dependency order (see below) |

## Usage

From the `ansible/` directory:

```bash
# Deploy everything
ansible-playbook playbooks/site.yml

# Deploy infrastructure services (reads homelab.yaml)
ansible-playbook playbooks/deploy-socket-proxy.yml
ansible-playbook playbooks/deploy-watchtower.yml

# Deploy Dozzle log viewer settings from .env
ansible-playbook playbooks/deploy-dozzle.yml

# Deploy Traefik static config + Authelia middleware
ansible-playbook playbooks/deploy-traefik.yml

# Apply Cloudflare DDNS settings from .env
ansible-playbook playbooks/deploy-cloudflare-ddns.yml

# Deploy Authelia users + configuration
ansible-playbook playbooks/deploy-authelia.yml

# Deploy Uptime Kuma + Autokuma (monitors from labels; status page from vars)
ansible-playbook playbooks/deploy-uptime-kuma.yml
ansible-playbook playbooks/deploy-autokuma.yml

# Deploy Memos Authelia OIDC (shared OIDC_CLIENT_SECRET from .env)
ansible-playbook playbooks/deploy-memos.yml

# Deploy Audiobookshelf (media mounts, libraries, Authelia OIDC)
ansible-playbook playbooks/deploy-audiobookshelf.yml

# Deploy Dispatcharr (admin + M3U provider + EPL/sports channels)
ansible-playbook playbooks/deploy-dispatcharr.yml

# Deploy Gluetun auth config (API key from .env)
ansible-playbook playbooks/deploy-gluetun.yml

# Deploy qBittorrent WebUI settings (port + LAN auth bypass from .env)
ansible-playbook playbooks/deploy-qbittorrent.yml

# Deploy Prowlarr (auth + indexers from homelab.yaml)
ansible-playbook playbooks/deploy-prowlarr.yml

# Deploy Radarr (paths, indexers, download client, profiles from homelab.yaml)
ansible-playbook playbooks/deploy-radarr.yml

# Deploy Homepage config (widget creds/keys from .env)
ansible-playbook playbooks/deploy-homepage.yml

# Deploy Jellyfin config (custom CSS, M3U tuner, Live TV list layout)
ansible-playbook playbooks/deploy-jellyfin.yml

# Deploy everything in dependency order
ansible-playbook playbooks/deploy-services.yml
```

Run `site.yml` before any deploy playbook — Socket Proxy must be up before Traefik; Jellyfin needs Dispatcharr; qBittorrent needs Gluetun.

### Deploy order

| Step | Playbook | Waits on |
| --- | --- | --- |
| 0 | `site.yml` | — |
| 1 | `deploy-socket-proxy.yml` | Compose stack up |
| 2 | `deploy-watchtower.yml` | Compose stack up |
| 3 | `deploy-dozzle.yml` | Socket Proxy on `:2375` |
| 4 | `deploy-traefik.yml` | Socket Proxy on `:2375` |
| 5 | `deploy-cloudflare-ddns.yml` | `CLOUDFLARE_API_TOKEN`, DDNS vars in `.env` |
| 6 | `deploy-authelia.yml` | `traefik_network`, `socket_proxy` from Compose |
| 7 | `deploy-uptime-kuma.yml` | Compose stack up |
| 8 | `deploy-autokuma.yml` | Uptime Kuma healthy; syncs `/status/default` groups |
| 9 | `deploy-gluetun.yml` | Compose stack up |
| 10 | `deploy-dispatcharr.yml` | Dispatcharr on `:9191` |
| 11 | `deploy-qbittorrent.yml` | Gluetun + sidecars running |
| 12 | `deploy-prowlarr.yml` | Gluetun + Prowlarr on `:9696` |
| 13 | `deploy-radarr.yml` | Gluetun + Prowlarr indexers; qBittorrent creds from yaml |
| 14 | `deploy-jellyfin.yml` | Dispatcharr M3U export |
| 15 | `deploy-homepage.yml` | — (last) |

Use `deploy-services.yml` to run steps 1–13 in this order automatically.

### Socket Proxy

Filtered Docker socket proxy for services that need container discovery without full socket access. Settings are `SOCKET_PROXY_*` flags in `.env` (see `.env.example`). `deploy-socket-proxy.yml` validates and runs `docker compose up -d socket-proxy`.

### Watchtower

Auto-updates containers labelled `com.centurylinklabs.watchtower.enable=true`. Settings in `.env`:

| Variable | Purpose |
| --- | --- |
| `WATCHTOWER_CLEANUP` | Remove old images after update |
| `WATCHTOWER_POLL_INTERVAL` | Check interval in seconds |
| `WATCHTOWER_LABEL_ENABLE` | Only update labelled containers |

### Uptime Kuma + Autokuma

Status dashboard at `https://status.${DOMAIN}/` (Authelia on the admin UI; public page at `/status/default` for the Homepage widget).

| Component | Role |
| --- | --- |
| **Compose `kuma.*` labels** | Declarative monitor definitions (HTTP, Docker, port checks) |
| **Autokuma** | Creates/updates monitors in Kuma from those labels via Socket Proxy |
| **Ansible** | Syncs the public status page layout (`Services`, `Arr`, `System`) from [`vars/uptime_kuma_status_page.yml`](vars/uptime_kuma_status_page.yml) |

Kuma dashboard auth is **disabled** (`disableAuth=true`) — Authelia handles browser access at Traefik. Autokuma and Ansible talk to Kuma on the Docker network with auto-login; no `.env` credentials needed. On a **fresh install**, `deploy-uptime-kuma.yml` bootstraps Kuma (creates an internal user, immediately disables dashboard auth). `deploy-autokuma.yml` syncs the public status page at `/status/default`, which the **Homepage widget reads** (`slug: default` in `services.yaml.j2`). Edit group membership in [`vars/uptime_kuma_status_page.yml`](vars/uptime_kuma_status_page.yml), not manually in the UI, or Ansible will overwrite changes on the next deploy.

Optional: override per-monitor health URLs with `KUMA_SONARR_URL`, `KUMA_RADARR_URL`, etc. when `/ping` is insufficient.

### Dozzle

Web UI for container logs at `https://logs.${DOMAIN}/` (Authelia via Traefik). Reads container metadata via Socket Proxy — no direct Docker socket mount. Settings in `.env`:

| Variable | Purpose |
| --- | --- |
| `DOZZLE_LEVEL` | Log verbosity (`info`, `debug`, etc.) |
| `DOZZLE_FILTER` | Container filter (default `status=running`) |
| `DOZZLE_REMOTE_HOST` | Docker API endpoint (`tcp://socket-proxy:2375`) |
| `DOZZLE_AUTH_PROVIDER` | `forward-proxy` — trust Authelia user header from Traefik |
| `DOZZLE_AUTH_HEADER_USER` | Header name (`Remote-User`) |

### Traefik configuration

Static config and the Authelia forward-auth middleware deploy to `services/traefik/` (gitignored):

| File | Source |
| --- | --- |
| `traefik.yml` | [`templates/traefik/traefik.yml.j2`](templates/traefik/traefik.yml.j2) |
| `dynamic/authelia.yml` | [`templates/traefik/dynamic/authelia.yml.j2`](templates/traefik/dynamic/authelia.yml.j2) |

Requires `DOMAIN`, `ACME_EMAIL`, and `CLOUDFLARE_API_TOKEN` in `.env`. Per-service router labels stay on each container in `compose.yaml`; protected routes reference the `authelia@file` middleware.

`acme.json` is runtime data (certificate store) — never template or commit it.

### Cloudflare DDNS

Uses [favonia/cloudflare-ddns](https://github.com/favonia/cloudflare-ddns) with settings from `.env` (no config files on disk):

| Variable | Purpose |
| --- | --- |
| `CLOUDFLARE_API_TOKEN` | Shared with Traefik ACME — needs DNS edit permissions |
| `CLOUDFLARE_DDNS_DOMAINS` | Comma-separated records to update (e.g. `example.com,*.example.com`) |
| `CLOUDFLARE_DDNS_PROXIED` | `true` / `false` — orange-cloud proxy |
| `CLOUDFLARE_DDNS_DETECTION_MODE` | Public IP detection (`cloudflare.trace` recommended) |
| `CLOUDFLARE_DDNS_HTTP_TIMEOUT` | HTTP timeout for IP detection |

`deploy-cloudflare-ddns.yml` validates these vars and runs `docker compose up -d cloudflare-ddns`.

### Homepage configuration

All Homepage YAML lives in Ansible and deploys to `services/homepage/config/` (gitignored):

| File | Source |
| --- | --- |
| `services.yaml` | [`templates/homepage/services.yaml.j2`](templates/homepage/services.yaml.j2) |
| `bookmarks.yaml`, `settings.yaml`, `widgets.yaml`, `docker.yaml`, `proxmox.yaml`, `kubernetes.yaml` | [`files/homepage/`](files/homepage/) |

Edit the Ansible sources, then run `deploy-homepage.yml`. Do not edit files under `services/homepage/config/` directly — changes will be overwritten.

Widget secrets are read from `.env` only (nothing sensitive is committed in Ansible):

| Service | `.env` variable |
| --- | --- |
| Jellyfin | Auto — API key named `homepage` in `jellyfin.db` (see `deploy-homepage.yml`) |
| Audiobookshelf | Auto — API key named `homepage` in `services/audiobookshelf/homepage_api_key` (see `deploy-homepage.yml`) |
| Mealie | Auto — long-lived token named `homepage` in `services/mealie/homepage_api_key` (owned by `mealie.admin_username` service account; run `deploy mealie` first) |
| Prowlarr | Auto — API key from `services/prowlarr/config/config.xml` (run `deploy prowlarr` first) |
| Sonarr, Radarr, Bazarr | `HOMEPAGE_SONARR_API_KEY`, etc. |
| Seerr | `HOMEPAGE_SEERR_API_KEY` |
| Traefik widget | none — internal API is `insecure: true`; dashboard auth is Authelia at the edge |
| Dispatcharr | `DISPATCHARR_ADMIN_*` |
| Gluetun | Auto — control API key in `services/gluetun/control_api_key` (see `deploy-gluetun.yml`) |
| Gluetun VPN | `VPN_SERVICE_PROVIDER`, `VPN_TYPE`, `WIREGUARD_*`, `SERVER_CITIES`, `GLUETUN_DNS_ADDRESS`, `FIREWALL_OUTBOUND_SUBNETS` |

Gluetun VPN settings are in `homelab.yaml` under `gluetun:` and baked into rendered `compose.yaml`. Ansible auto-generates the HTTP control-server API key to `services/gluetun/control_api_key` if unset, and renders `config.toml` (gitignored) for Homepage widget auth.

### Authelia

Authelia config is rendered from **`homelab.yaml`** (repo root, gitignored) plus committed Ansible sources:

| Output | Source |
| --- | --- |
| `services/authelia/config/users.yml` | `authelia.users` in `homelab.yaml` → [`templates/authelia/users.yml.j2`](templates/authelia/users.yml.j2) |
| `services/authelia/config/configuration.yml` | [`templates/authelia/configuration.yml.j2`](templates/authelia/configuration.yml.j2) + `homelab.yaml` + [`vars/authelia_oidc_clients.yml`](vars/authelia_oidc_clients.yml) |

Do not edit `users.yml` or `configuration.yml` directly — changes will be overwritten on the next deploy.

**Users** — under `authelia.users` in `homelab.yaml`:

```yaml
authelia:
  users:
    mike:
      display_name: Mike
      email: mike@example.com
      password: your-plain-password
      groups:
        - admins
```

Use `password:` for plain text (Ansible hashes with argon2 at deploy time), or `password_hash:` to keep an existing hash.

**Secrets in `homelab.yaml`** under `authelia:`:

| Key | Purpose |
| --- | --- |
| `session_secret` | Session cookie signing |
| `jwt_secret` | Password-reset token signing |
| `storage_encryption_key` | Encrypts `db.sqlite3` — **never change** unless you accept data loss |
| `oidc_hmac_secret` | OIDC HMAC |
| `oidc_client_secret` | Plain secret shared by all OIDC apps |
| `jwks_private_key` | RSA PEM block (`\|` multiline) for OIDC token signing |

Generate a JWKS PEM once and paste into `authelia.jwks_private_key` (see root [README.md](../README.md)).

**OIDC clients** — structure (redirect URIs, scopes, etc.) lives in [`vars/authelia_oidc_clients.yml`](vars/authelia_oidc_clients.yml). Active clients: Audiobookshelf, Jellyfin, Mealie, Memos, Sparky Fitness.

**Access control** — `vpn-status.${DOMAIN}` bypass auto-detects `traefik_network` and `socket_proxy` subnets via [`tasks/resolve-docker-network-subnets.yml`](tasks/resolve-docker-network-subnets.yml).

```bash
ansible-playbook playbooks/deploy-authelia.yml
# Restarts Authelia via docker compose when config changes
```

### Memos OIDC

Memos 0.30+ loads login policy from deployment-managed JSON under `services/memos/secrets/` (mounted read-only at `/etc/secrets`). Ansible renders three files: Authelia IdP, SSO-only general settings (`disallowPasswordAuth: true`), and private access mode. The Authelia OIDC client definition lives in [`vars/authelia_oidc_clients.yml`](vars/authelia_oidc_clients.yml).

| Setting | Source |
| --- | --- |
| OAuth2 client ID / secret | `OIDC_CLIENT_SECRET` in `.env` (client id `memos`) |
| Canonical URL | `MEMOS_INSTANCE_URL=https://notes.${DOMAIN}` in Compose |
| IdP endpoints | `https://auth.${DOMAIN}/api/oidc/*` |
| SSO-only login | `memos-instance-setting-general.json` (`disallowPasswordAuth: true`) |
| Private instance | `memos-instance-setting-access.json` |
| Instance admin | `MEMOS_ADMIN_USERNAME` / `MEMOS_ADMIN_PASSWORD` in `.env` (created on first install) |

Memos requires at least one user before the setup wizard clears. Ansible backs up `services/memos/` before changes, creates the instance admin from `MEMOS_ADMIN_USERNAME` and `MEMOS_ADMIN_PASSWORD` on first install, then the main login page shows Authelia SSO. Local admin sign-in: `https://notes.${DOMAIN}/auth/admin`. Run after Authelia:

```bash
ansible-playbook playbooks/deploy-memos.yml
# Restarts Memos when the secrets file changes
```

### Audiobookshelf

Audiobookshelf uses in-app Authelia OIDC (Traefik does not forward-auth the app). Ansible backs up `services/audiobookshelf/` before changes, regenerates `compose.yaml` (volume mounts from `homelab.yaml`), and bootstraps via API.

| Setting | Source in `homelab.yaml` |
| --- | --- |
| Media bind mounts | `audiobookshelf.volumes` — list of `host` / `container` |
| Libraries + folder paths | `audiobookshelf.libraries` — folder paths use **container** paths |
| Break-glass root login | `audiobookshelf.root_username` / `root_password` |
| OIDC client secret | `authelia.oidc_client_secret` (client id `audiobookshelf`) |

Run after Authelia: `./bin/homelab deploy audiobookshelf` (or `ansible-playbook playbooks/deploy-audiobookshelf.yml`).

### Mealie

Mealie uses in-app Authelia OIDC for humans (same pattern as Audiobookshelf). Ansible backs up `services/mealie/data/` to `backups/mealie/<timestamp>/` before changes, creates a local **service admin** from `mealie.admin_username` / `mealie.admin_password` (for Homepage API tokens and break-glass access), removes Mealie's seeded placeholder user, optionally configures the group OpenAI provider from `mealie.openai_api_key`, fixes root-owned data dirs, and applies the container from rendered `compose.yaml`. Password login is hidden in the UI; family sign in via Authelia only.

Bootstrap runs **after** Mealie has started once (so the database exists). The service admin is a local (`MEALIE` auth) account — OIDC users are unchanged. Break-glass local login: `https://food.${DOMAIN}/login?direct=1`.

| Setting | Source in `homelab.yaml` |
| --- | --- |
| Service admin | `mealie.admin_username`, `mealie.admin_password` (min 8 chars) — automation / Homepage |
| Service admin email (optional) | `mealie.admin_email` — defaults to `{admin_username}@mealie.local` |
| OIDC client secret | `authelia.oidc_client_secret` (client id `mealie`) |
| OpenAI (optional) | `mealie.openai_api_key` — recipe import / image services |
| Authelia groups | `mealie-admins` → Mealie admin; `mealie-users` → regular user |

On first install Mealie creates group **Home** and household **Family** by default. New OIDC users are placed there (`DEFAULT_GROUP` / `DEFAULT_HOUSEHOLD` in compose — change these if you rename the group/household in the UI). No extra household setup is required unless you want multiple households.

```bash
./bin/homelab deploy mealie
# Run after deploy-authelia.yml, then deploy homepage
```

### Jellyscope

Jellyscope has no OIDC — Authelia protects the edge only. Ansible backs up `services/jellyscope/data/` to `backups/jellyscope/<timestamp>/` before changes, reads or creates a dedicated Jellyfin API key named `jellyscope` in `jellyfin.db`, and creates/updates the instance admin from `.env`.

| Setting | `.env` variable |
| --- | --- |
| Login cookie secret | `JELLYSCOPE_SECRET_KEY` |
| Instance admin | `JELLYSCOPE_ADMIN_USERNAME` / `JELLYSCOPE_ADMIN_PASSWORD` |
| UI language | `JELLYSCOPE_UI_LANGUAGE` (`en` default; Jellyscope’s built-in default is Czech) |

Sign-up is not public: `/setup` only appears when the database has zero accounts. After bootstrap, only admins can add users in Settings.

```bash
ansible-playbook playbooks/deploy-jellyscope.yml
# Run after deploy-jellyfin.yml
```

### qBittorrent WebUI

WebUI credentials, port, and LAN auth bypass are managed from `.env` and applied to `services/qbittorrent/config/qBittorrent/qBittorrent.conf` (gitignored).

| Setting | `.env` variable |
| --- | --- |
| Username | `QBITTORRENT_WEBUI_USERNAME` — used by Sonarr/Radarr/Prowlarr download-client API |
| Password | `QBITTORRENT_WEBUI_PASSWORD` (PBKDF2 hash generated at deploy) |
| WebUI port | `QBITTORRENT_WEBUI_PORT` |
| LAN auth bypass | `QBITTORRENT_LAN_AUTH_BYPASS` |

**Username/password are always required.** Sonarr, Radarr, and Prowlarr run on the Gluetun network and connect to qBittorrent's API with these credentials — they are not covered by the subnet whitelist.

When `QBITTORRENT_LAN_AUTH_BYPASS=true` (default): Traefik and Homepage (on `traefik_network`) skip the WebUI login prompt; external browser access still goes through Authelia. When `false`, every WebUI request also requires qBittorrent credentials.

The playbook backs up the live config to `qBittorrent.conf.bak` before changes. A snapshot of your pre-Ansible config is kept at [`files/qbittorrent/qBittorrent.conf.backup`](files/qbittorrent/qBittorrent.conf.backup).

On an **existing** install, deploy only updates WebUI auth keys (username, password, port, whitelist) so other preferences changed in the qBittorrent UI are preserved. On a **fresh** install, the full baseline config is rendered from [`templates/qbittorrent/qBittorrent.conf.j2`](templates/qbittorrent/qBittorrent.conf.j2).

### Prowlarr

Cardigann indexers are managed from `homelab.yaml` (`prowlarr.indexers`). Auth is always **external** (Authelia at Traefik via `Remote-User` header) — enforced by bootstrap, not configurable in yaml. The playbook backs up the full `services/prowlarr/` tree before changes.

| Setting | `homelab.yaml` key |
| --- | --- |
| Indexers | `prowlarr.indexers[]` — `name`, `definition` (Cardigann id), `enable`, `private` |
| Private creds | `username`, `password` on indexers where `private: true` (tracker site login, not Prowlarr) |
| Homepage widget | Auto — API key read from `config.xml` by `deploy-homepage.yml` |

Sonarr/Radarr should **not** use Prowlarr Applications sync. Add Torznab indexers pointing at `http://localhost:9696/{prowlarr_indexer_id}/` with the Prowlarr API key from `config.xml`.

```bash
ansible-playbook playbooks/deploy-prowlarr.yml
# Run after deploy-gluetun.yml (Prowlarr shares Gluetun's network)
```

### Radarr

Radarr settings are managed from `homelab.yaml` (`radarr.*`). Auth is always **external** (Authelia at Traefik). The playbook backs up the full `services/radarr/` tree, regenerates compose volume mounts, and bootstraps via API.

| Setting | `homelab.yaml` key |
| --- | --- |
| Volume mounts | `radarr.volumes[]` — `host` / `container` (like Audiobookshelf) |
| Library root paths | `radarr.root_folders[]` — container paths (e.g. `/media/Movies`) |
| Indexers | `radarr.indexers[]` — Prowlarr name (string) or `{ name?, prowlarr_indexer }`; Torznab URL/id resolved at deploy |
| Download client | Defaults to qBittorrent (`localhost`, `gluetun.ports.qbittorrent_webui`, creds from `qbittorrent.*`); optional `radarr.download_clients[]` overrides |
| Naming | `radarr.naming` — optional overrides only (omit = Radarr defaults) |
| Media management | `radarr.media_management` — optional overrides only |
| Quality overrides | `radarr.qualities` — optional map of 720/1080-tier quality name → `true`/`false` |
| Quality profiles | `radarr.quality_profiles[]` — `name`, `cutoff`, `qualities[]` (which source types are allowed) |
| Quality definitions | `radarr.quality_definitions` — min/preferred/max in **MB/min** per quality or tier (`720p`, `1080p`); rejects releases outside size range |
| Library import | `radarr.library_import` — mirrors UI library import: scans root folders for unmapped folders, TMDB lookup, bulk import with `monitor: none` and quality profile `Any` by default; set `enabled: false` to skip |

Deploy **prowlarr** before radarr (indexers resolve Prowlarr ids at bootstrap time). qBittorrent credentials come from `qbittorrent.webui_*`.

```bash
ansible-playbook playbooks/deploy-radarr.yml
# Run after deploy-prowlarr.yml and deploy-qbittorrent.yml
```

### Jellyfin branding

Custom CSS and the Live TV channel list layout deploy to `services/jellyfin/config/config/branding.xml` (gitignored):

| Content | Source |
| --- | --- |
| Intro Skipper, Authelia SSO button | [`files/jellyfin/custom.css`](files/jellyfin/custom.css) |
| Live TV channel list layout | [`files/jellyfin/livetv-channels-list.css`](files/jellyfin/livetv-channels-list.css) |
| `branding.xml` wrapper | [`templates/jellyfin/branding.xml.j2`](templates/jellyfin/branding.xml.j2) |
| Live TV M3U tuner | [`templates/jellyfin/livetv.xml.j2`](templates/jellyfin/livetv.xml.j2) |

Edit the Ansible sources, then run `deploy-jellyfin.yml`. Do not edit `branding.xml` or `livetv.xml` in the Jellyfin UI — changes will be overwritten on the next deploy. Jellyfin caches config at startup, so the playbook restarts the container when either file changes; hard-refresh the browser after deploy.

### Migrating data to `services/`

Compose and Ansible now expect data under `services/`. **Do not restart the stack until existing data is moved**, or containers will mount empty directories.

1. Stop the stack: `docker compose down` (from repo root).
2. Create the target tree (optional — Ansible can do this): `ansible-playbook playbooks/ensure-service-dirs.yml`
3. Move each top-level service dir into `services/` (only move dirs that exist):

   ```bash
   cd "${DATA_DIR:-.}"   # repo root if DATA_DIR=./
   mkdir -p services
   for d in traefik authelia uptime-kuma autokuma homepage jellyfin jellyscope \
     audiobookshelf mealie memos sparkyfitness seerr gluetun \
     qbittorrent sonarr radarr prowlarr bazarr dispatcharr mccleanengineering trilium; do
     [ -d "$d" ] && mv "$d" services/
   done
   ```

4. Bring the stack back: `ansible-playbook playbooks/site.yml` then `ansible-playbook playbooks/deploy-services.yml` if needed.

### Dry run (`--check`)

Prefer the homelab CLI from the repo root:

```bash
./bin/homelab deploy audiobookshelf --check --diff   # compose.yaml preview + Ansible template diffs
./bin/homelab deploy authelia --check --diff
```

Or run Ansible directly:

```bash
ansible-playbook playbooks/site.yml --check --diff
ansible-playbook playbooks/deploy-authelia.yml --check --diff
```

### Service backups (Mealie, Audiobookshelf, Jellyscope, Memos)

Manual backups:

```bash
./bin/homelab backup mealie --label manual
./bin/homelab backup --all
./bin/homelab backup --list   # services included in --all
```

Before deploy changes, Ansible runs the same CLI (`homelab backup <name> --label deploy`). Each backup copies the full live tree at `services/<name>/` to `backups/<name>/<label>-<timestamp>/` (same layout — e.g. Mealie includes `data/`, `homepage_api_key`, etc.). Add `backup: true` to a service in [`config/services.yaml`](../config/services.yaml) to include it in `backup --all`.

To restore:

```bash
docker stop mealie   # or the relevant container
rsync -a --delete backups/mealie/<timestamp>/ services/mealie/
docker start mealie
```

Backups and Docker/API bootstrap steps are skipped in check mode. Template and `file` tasks (e.g. Authelia config, Homepage YAML, service data dirs) still run with `--diff` so you can preview changes even on a fresh install with no backup dir yet.

### Reset app data for bootstrap testing

Stop the services, wipe their data dirs, then re-run the playbooks:

```bash
cd ..   # repo root
docker compose stop dispatcharr
rm -rf services/dispatcharr/data/*
# Do not use `docker compose run dispatcharr ...` for cleanup — it runs as root and creates root-owned files.

cd ansible
ansible-playbook playbooks/deploy-dispatcharr.yml
```

## Required `.env` variables

### Dispatcharr

`deploy-dispatcharr.yml` reads all of these from `.env`:

```env
DISPATCHARR_ADMIN_USERNAME=mike
DISPATCHARR_ADMIN_PASSWORD=your-secure-password
DISPATCHARR_ADMIN_EMAIL=mike@example.com
DISPATCHARR_M3U_NAME=MyProvider
DISPATCHARR_M3U_URL=http://your-provider.example.com
DISPATCHARR_M3U_USERNAME=your-provider-username
DISPATCHARR_M3U_PASSWORD=your-provider-password
DISPATCHARR_M3U_ACCOUNT_TYPE=XC
DISPATCHARR_M3U_MAX_STREAMS=1
DISPATCHARR_M3U_REFRESH_INTERVAL=24
```

Use `XC` for Xtream Codes (base URL + username/password). Use `STD` for a direct M3U playlist URL. The playbook skips creation if an account with the same name already exists.

`DISPATCHARR_M3U_REFRESH_INTERVAL` sets Dispatcharr’s scheduled provider refresh in hours (`0` = disabled). After each refresh, Dispatcharr auto-runs channel sync for groups with `auto_channel_sync` enabled (configured by this playbook).

XC accounts have a two-step setup: create discovers channel groups (`pending_setup`), then a full refresh imports streams. The playbook handles both steps automatically and waits for `success`. Re-run it if an account is stuck on `pending_setup`.

EPL/sports channel groups are defined in [`vars/dispatcharr_epl_channel_groups.yml`](vars/dispatcharr_epl_channel_groups.yml):

- **Logical groups** (created automatically): `EPL`, `TNT Sports`, `Sky Sports HD`, `Sky Sports SD`, `US EPL`
- **Provider groups** are matched by **name regex** at deploy time (no hardcoded IDs — survives Strong reshuffles)
- Each rule maps matching provider groups into a logical group with a fixed channel-number block (EPL 100+, TNT 200+, Sky HD 300+, Sky SD 400+)
- **Name cleanup** on sync (Dispatcharr built-ins):
  - Skip separator streams: `^#{2,}` (e.g. `##### PREMIER LEAGUE #####`)
  - Strip prefixes: `UK:`, `NOW:`, `US:` from channel names
  - **US EPL** (500+): filtered Peacock/NBC/USA Network groups for US Premier League coverage
- Channels are sorted **by name** within each block on sync

To add a provider group: add a `name_pattern` rule to [`vars/dispatcharr_epl_channel_groups.yml`](vars/dispatcharr_epl_channel_groups.yml), then re-run `deploy-dispatcharr.yml`. The playbook prints resolved group names/IDs and warns if a pattern matches nothing.

Test playback via **Channels** in the UI, VLC with `https://dispatch.${DOMAIN}/output/m3u/`, or Jellyfin Live TV (M3U tuner, deployed by `deploy-jellyfin.yml`).

Dispatcharr runs **outside** Gluetun so IPTV provider traffic uses your home IP (many providers block VPN/datacenter exits). *arr apps stay on the VPN.

### IPTV clients (UHF, iPlayTV, etc.) — remote XC access

Set `DISPATCHARR_XC_PASSWORD` in `.env` (letters, numbers, `.`, `_`, `@`, `-` only). `deploy-dispatcharr.yml` applies it to your admin user as the XC password.

Traefik exposes two routes on `dispatch.${DOMAIN}`:

- **UI + raw M3U** (`/output/m3u`, `/output/epg`) — behind Authelia
- **XC API** (`/get.php`, `/player_api.php`, `/live/…`, `/xmltv.php`) — no Authelia; Dispatcharr validates username + XC password

In your IPTV app, choose **Xtream Codes** (not plain M3U):

| Field | Value |
|-------|--------|
| Server / URL | `https://dispatch.${DOMAIN}` |
| Username | `DISPATCHARR_ADMIN_USERNAME` |
| Password | `DISPATCHARR_XC_PASSWORD` |

EPG is usually discovered automatically via XC. Do **not** share the raw `/output/m3u` URL — it has no built-in password (Authelia only protects it via the web domain).

### Jellyfin Live TV

`deploy-jellyfin.yml` configures an **M3U tuner** pointing at Dispatcharr (`http://dispatcharr:9191/output/m3u/`). Dispatcharr exports `group-title` from the logical channel groups (EPL, TNT Sports, Sky Sports HD, Sky Sports SD). On first deploy the playbook removes the legacy HDHomeRun tuner, re-imports channels from M3U, and styles Dispatcharr's separator rows as section headers in the list CSS.

Requires Jellyfin to have run once (`jellyfin.db` exists). The playbook reads or creates an API key named `ansible` automatically — no manual Dashboard step.

The Live TV channel list uses a list layout via custom CSS in `files/jellyfin/livetv-channels-list.css`. The rules target Jellyfin 12+ (`#liveTvPage` and `#channelsTab`, flex row cards). Tweak that file if logos or text overlap on your screen size.

## Notes

- Playbooks use `community.docker.docker_compose_v2` against rendered `compose.yaml` (see `tasks/ensure-compose-generated.yml`).
- Dispatcharr bootstrap waits on `http://127.0.0.1:9191` (published on the dispatcharr container).
- Web signup is disabled (`DISPATCHARR_SETUP_ALLOWED_IP=127.0.0.1`). Run `deploy-dispatcharr.yml` after `site.yml`.
- Starting Gluetun always includes all `network_mode: service:gluetun` sidecars (Sonarr, Radarr, etc.) so a Gluetun recreate cannot orphan them.
- Tasks that handle passwords use `no_log: true` so secrets are not printed in Ansible output.
