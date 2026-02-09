# Docker Compose stack

Single Compose file for Traefik, Authelia, media apps, and VPN-backed services (Gluetun, *arr, qBittorrent). Safe to version in Git: secrets and service data live in `.env` and local directories, not in the repo.

## Quick start

1. **Copy env and set values**
   ```bash
   cp .env.example .env
   ```
   Edit `.env`: set `DATA_DIR` (path to this repo or your data root), `PUID`/`PGID`/`TZ`, and all secrets (Cloudflare, OIDC, WireGuard, Mealie OpenAI, media paths, etc.). See comments in `.env.example`.

2. **Traefik ACME file**
   Ensure the ACME JSON file exists and has strict permissions (required for TLS):
   ```bash
   mkdir -p "${DATA_DIR}/traefik/acme"
   touch "${DATA_DIR}/traefik/acme/acme.json"
   chmod 600 "${DATA_DIR}/traefik/acme/acme.json"
   ```
   If you use a different `DATA_DIR` in `.env`, run the same with that path.

3. **Start the stack**
   From this directory (the one containing `compose.yaml`):
   ```bash
   docker compose up -d
   ```
   Compose automatically loads `.env` from this directory; you do not need to `source` it.

## Service data

Service data (configs, databases, cache) is stored under the directories listed in `.gitignore` (e.g. `authelia/`, `jellyfin/`, `traefik/`). Only `.keep` files are committed so the folder structure exists after clone; **all other contents are ignored**. Populate or restore these directories yourself (e.g. from backup or by letting the apps create them on first run). Back up `DATA_DIR` (or each service folder) separately if you need to preserve data.

## Changing the shared OIDC secret

All Authelia OIDC clients (Audiobookshelf, Jellyfin, Mealie, Wallos, Trilium) use the same client secret. To rotate it:

1. Generate a new hash, e.g. `docker run --rm authelia/authelia authelia crypto hash generate pbkdf2 --password 'YourNewSecret'`.
2. Update `authelia/config/configuration.yml`: set `client_secret` to the new hash for every client.
3. Update `OIDC_CLIENT_SECRET` in `.env` and restart Mealie and Trilium (`docker compose up -d mealie trilium`).
4. Update Jellyfin, Audiobookshelf, and Wallos in their own config/UIs to use the same new secret.

## Optional: Kuma health checks for *arr apps

If your Sonarr/Radarr/Prowlarr/Bazarr require an API key in the status URL, set in `.env`:

- `KUMA_SONARR_URL=http://gluetun:8989/api/v3/system/status?apiKey=YOUR_KEY`
- `KUMA_RADARR_URL=...`
- `KUMA_PROWLARR_URL=...`
- `KUMA_BAZARR_URL=...`

If unset, the compose file uses the same URLs without the query parameter (may work if the app allows unauthenticated status when restricted to localhost).
