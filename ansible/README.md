# Homelab Ansible

Ansible playbooks for deploying and bootstrapping the homelab stack. **Secrets stay in `.env`** (gitignored); nothing sensitive is stored in this directory.

For a per-service migration tracker (what's done, what's todo, suggested order), see **[MIGRATION-CHECKLIST.md](MIGRATION-CHECKLIST.md)**.

## Prerequisites

```bash
sudo apt install ansible-core   # or pip install ansible
cd ansible
ansible-galaxy collection install -r requirements.yml
```

Ensure `.env` exists at the repo root (copy from `.env.example`).

Optional: override the repo path when running from elsewhere:

```bash
export HOMELAB_DIR=/home/mike/Documents/homelab
```

## Playbooks

| Playbook | Purpose |
| --- | --- |
| `playbooks/site.yml` | Ensure `services/` dirs + deploy the full Docker Compose stack |
| `playbooks/ensure-service-dirs.yml` | Create `services/` directory tree only (no Compose) |
| `playbooks/deploy-authelia.yml` | Render Authelia `users.yml` + `configuration.yml` from templates, `.env`, and vars |
| `playbooks/deploy-dispatcharr.yml` | Bootstrap admin + M3U/XC provider + logical channel groups (idempotent) |
| `playbooks/deploy-gluetun.yml` | Render Gluetun `config.toml` from template + `.env` |
| `playbooks/deploy-qbittorrent.yml` | Apply qBittorrent WebUI credentials, port + LAN auth bypass from `.env` |
| `playbooks/deploy-homepage.yml` | Deploy Homepage config from Ansible templates + `.env` |
| `playbooks/deploy-jellyfin.yml` | Deploy Jellyfin config (branding, CSS, M3U tuner, Live TV list layout) |
| `playbooks/deploy-services.yml` | Authelia + Dispatcharr + Gluetun + qBittorrent + Homepage + Jellyfin |

## Usage

From the `ansible/` directory:

```bash
# Deploy everything
ansible-playbook playbooks/site.yml

# Deploy Authelia users + configuration
ansible-playbook playbooks/deploy-authelia.yml

# Deploy Dispatcharr (admin + M3U provider + EPL/sports channels)
ansible-playbook playbooks/deploy-dispatcharr.yml

# Deploy Gluetun auth config (API key from .env)
ansible-playbook playbooks/deploy-gluetun.yml

# Deploy qBittorrent WebUI settings (port + LAN auth bypass from .env)
ansible-playbook playbooks/deploy-qbittorrent.yml

# Deploy Homepage config (widget creds/keys from .env)
ansible-playbook playbooks/deploy-homepage.yml

# Deploy Jellyfin config (custom CSS, M3U tuner, Live TV list layout)
ansible-playbook playbooks/deploy-jellyfin.yml

# Deploy all app services (Dispatcharr + Gluetun + Homepage + Jellyfin)
ansible-playbook playbooks/deploy-services.yml
```

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
| Jellyfin | `HOMEPAGE_JELLYFIN_API_KEY` |
| Audiobookshelf | `HOMEPAGE_AUDIOBOOKSHELF_API_KEY` |
| Mealie | `HOMEPAGE_MEALIE_API_KEY` |
| Wallos | `HOMEPAGE_WALLOS_API_KEY` |
| Sonarr, Radarr, Prowlarr, Bazarr | `HOMEPAGE_SONARR_API_KEY`, etc. |
| Seerr | `HOMEPAGE_SEERR_API_KEY` |
| Traefik dashboard | `HOMEPAGE_TRAEFIK_USERNAME`, `HOMEPAGE_TRAEFIK_PASSWORD` |
| Dispatcharr | `DISPATCHARR_ADMIN_*` |
| Gluetun | `GLUETUN_API_KEY` |

Gluetun `config.toml` is generated to `services/gluetun/config.toml` (gitignored) and bind-mounted into the container at `/gluetun/auth/config.toml`.

### Authelia

Authelia config is split across `.env`, gitignored files, and committed Ansible sources:

| Output | Source |
| --- | --- |
| `services/authelia/config/users.yml` | `authelia-users.yml` (repo root, gitignored) → [`templates/authelia/users.yml.j2`](templates/authelia/users.yml.j2) |
| `services/authelia/config/configuration.yml` | [`templates/authelia/configuration.yml.j2`](templates/authelia/configuration.yml.j2) + `.env` + [`vars/authelia_oidc_clients.yml`](vars/authelia_oidc_clients.yml) + `authelia-jwks.pem` |

Do not edit `users.yml` or `configuration.yml` directly — changes will be overwritten on the next deploy.

**Users** — copy `authelia-users.example.yml` → `authelia-users.yml`:

```yaml
users:
  mike:
    display_name: Mike
    email: mike@example.com
    password: your-plain-password
    groups:
      - admins
```

Use `password:` for plain text (Ansible hashes with argon2 at deploy time), or `password_hash:` to keep an existing hash until you set a new password.

**Secrets in `.env`** (migrate from your existing `configuration.yml` on first run):

| Variable | Purpose |
| --- | --- |
| `AUTHELIA_SESSION_SECRET` | Session cookie signing |
| `AUTHELIA_JWT_SECRET` | Password-reset token signing |
| `AUTHELIA_STORAGE_ENCRYPTION_KEY` | Encrypts `db.sqlite3` — **never change** unless you accept data loss |
| `AUTHELIA_OIDC_HMAC_SECRET` | OIDC HMAC |
| `OIDC_CLIENT_SECRET` | Plain secret shared by all OIDC apps; PBKDF2-hashed into `configuration.yml` at deploy |

**JWKS private key** — extract once from your existing `configuration.yml` into `authelia-jwks.pem` at the repo root (gitignored). Never regenerate unless deliberately rotating OIDC signing keys.

**OIDC clients** — structure (redirect URIs, scopes, etc.) lives in [`vars/authelia_oidc_clients.yml`](vars/authelia_oidc_clients.yml). Active clients: Audiobookshelf, Jellyfin, Mealie, Memos, Sparky Fitness, Wallos.

**Access control** — `vpn-status.${DOMAIN}` bypass auto-detects `traefik_network` and `socket_proxy` subnets via [`tasks/resolve-docker-network-subnets.yml`](tasks/resolve-docker-network-subnets.yml).

```bash
ansible-playbook playbooks/deploy-authelia.yml
# Restarts Authelia via docker compose when config changes
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
     audiobookshelf mealie wallos memos sparkyfitness seerr gluetun \
     qbittorrent sonarr radarr prowlarr bazarr dispatcharr mccleanengineering trilium; do
     [ -d "$d" ] && mv "$d" services/
   done
   ```

4. Bring the stack back: `ansible-playbook playbooks/site.yml` then `ansible-playbook playbooks/deploy-services.yml` if needed.

### Dry run (`--check`)

Preview Compose changes without applying them:

```bash
ansible-playbook playbooks/site.yml --check
ansible-playbook playbooks/site.yml --check --diff   # show config diffs where supported
```

Deploy playbooks (`deploy-*.yml`) are not fully simulatable in check mode — Docker exec steps are skipped. Use `--check` on `site.yml` only; run deploy playbooks for real when testing app setup.

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
```

Use `XC` for Xtream Codes (base URL + username/password). Use `STD` for a direct M3U playlist URL. The playbook skips creation if an account with the same name already exists.

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

Requires `JELLYFIN_API_KEY` in `.env` (Dashboard → API Keys) so the playbook can register the tuner and refresh channels.

The Live TV channel list uses a list layout via custom CSS in `files/jellyfin/livetv-channels-list.css`. The rules target Jellyfin 12+ (`#liveTvPage` and `#channelsTab`, flex row cards). Tweak that file if logos or text overlap on your screen size.

## Notes

- Playbooks use `community.docker.docker_compose_v2` and pass your `.env` file to Compose.
- Dispatcharr bootstrap waits on `http://127.0.0.1:9191` (published on the dispatcharr container).
- Web signup is disabled (`DISPATCHARR_SETUP_ALLOWED_IP=127.0.0.1`). Run `deploy-dispatcharr.yml` after `site.yml`.
- Starting Gluetun always includes all `network_mode: service:gluetun` sidecars (Sonarr, Radarr, etc.) so a Gluetun recreate cannot orphan them.
- Tasks that handle passwords use `no_log: true` so secrets are not printed in Ansible output.
