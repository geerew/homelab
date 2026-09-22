# Homelab Ansible

Ansible playbooks for deploying and bootstrapping the homelab stack. **Secrets stay in `.env`** (gitignored); nothing sensitive is stored in this directory.

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
| `playbooks/deploy-dispatcharr.yml` | Bootstrap admin + M3U/XC provider + EPL/sports channels (idempotent) |
| `playbooks/deploy-gluetun.yml` | Render Gluetun `config.toml` from template + `.env` |
| `playbooks/deploy-homepage.yml` | Deploy Homepage config from Ansible templates + `.env` |
| `playbooks/deploy-jellyfin.yml` | Deploy Jellyfin config (branding, custom CSS, Live TV channel list) |
| `playbooks/deploy-services.yml` | Dispatcharr + Gluetun + Homepage + Jellyfin |

## Usage

From the `ansible/` directory:

```bash
# Deploy everything
ansible-playbook playbooks/site.yml

# Deploy Dispatcharr (admin + M3U provider + EPL/sports channels)
ansible-playbook playbooks/deploy-dispatcharr.yml

# Deploy Gluetun auth config (API key from .env)
ansible-playbook playbooks/deploy-gluetun.yml

# Deploy Homepage config (widget creds/keys from .env)
ansible-playbook playbooks/deploy-homepage.yml

# Deploy Jellyfin config (custom CSS, Live TV channel list)
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

### Jellyfin branding

Custom CSS and the Live TV channel list layout deploy to `services/jellyfin/config/config/branding.xml` (gitignored):

| Content | Source |
| --- | --- |
| Intro Skipper, Authelia SSO button | [`files/jellyfin/custom.css`](files/jellyfin/custom.css) |
| Live TV channel list layout | [`files/jellyfin/livetv-channels-list.css`](files/jellyfin/livetv-channels-list.css) |
| `branding.xml` wrapper | [`templates/jellyfin/branding.xml.j2`](templates/jellyfin/branding.xml.j2) |

Edit the Ansible sources, then run `deploy-jellyfin.yml`. Do not edit `branding.xml` in the Jellyfin UI — changes will be overwritten on the next deploy. Jellyfin caches branding at startup, so the playbook restarts the container when `branding.xml` changes; hard-refresh the browser after deploy.

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
DISPATCHARR_M3U_NAME=Strong8k
DISPATCHARR_M3U_URL=http://cf.strong8high.xyz
DISPATCHARR_M3U_USERNAME=your-provider-username
DISPATCHARR_M3U_PASSWORD=your-provider-password
DISPATCHARR_M3U_ACCOUNT_TYPE=XC
```

Use `XC` for Xtream Codes (base URL + username/password). Use `STD` for a direct M3U playlist URL. The playbook skips creation if an account with the same name already exists.

XC accounts have a two-step setup: create discovers channel groups (`pending_setup`), then a full refresh imports streams. The playbook handles both steps automatically and waits for `success`. Re-run it if an account is stuck on `pending_setup`.

EPL/sports channel groups are defined in [`vars/dispatcharr_epl_channel_groups.yml`](vars/dispatcharr_epl_channel_groups.yml):

- EPL Premier League PPV (+ VIP) and Premier League+
- TNT Sport HD and NOW TV Sport (Sky)

Channels are numbered from 100, 200, 300, etc. Test playback via **Channels** in the UI, VLC with `https://dispatch.${DOMAIN}/output/m3u/`, or Jellyfin Live TV (`http://dispatcharr:9191/hdhr`).

Dispatcharr runs **outside** Gluetun so IPTV provider traffic uses your home IP (many providers block VPN/datacenter exits). *arr apps stay on the VPN.

### Jellyfin Live TV

Add an **HDHomeRun** tuner at `http://dispatcharr:9191/hdhr` (not `gluetun:9191`). If Dispatcharr was moved off the VPN, update the tuner URL in **Dashboard → Live TV** and refresh channels — Jellyfin caches stream URLs and will fail with `Connection refused (gluetun:9191)` until re-scanned.

The Live TV channel list uses a list layout via custom CSS in `files/jellyfin/livetv-channels-list.css` (deployed by `deploy-jellyfin.yml`). The rules target Jellyfin 12+ (`#liveTvPage` and `#channelsTab`, flex row cards). Tweak that file if logos or text overlap on your screen size.

## Notes

- Playbooks use `community.docker.docker_compose_v2` and pass your `.env` file to Compose.
- Dispatcharr bootstrap waits on `http://127.0.0.1:9191` (published on the dispatcharr container).
- Web signup is disabled (`DISPATCHARR_SETUP_ALLOWED_IP=127.0.0.1`). Run `deploy-dispatcharr.yml` after `site.yml`.
- Starting Gluetun always includes all `network_mode: service:gluetun` sidecars (Sonarr, Radarr, etc.) so a Gluetun recreate cannot orphan them.
- Tasks that handle passwords use `no_log: true` so secrets are not printed in Ansible output.
