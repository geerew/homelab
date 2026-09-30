# Homelab Docker stack

Traefik, Authelia, media apps, and VPN-backed services (Gluetun, *arr, qBittorrent). Configuration lives in **`homelab.yaml`** (gitignored); Compose is rendered to **`compose.yaml`** (gitignored, contains secrets).

## Prerequisites

```bash
sudo apt install python3-yaml ansible-core docker-compose-plugin
cd ansible && ansible-galaxy collection install -r requirements.yml
```

## Quick start

1. **Create config**
   ```bash
   cp homelab.example.yaml homelab.yaml
   chmod 600 homelab.yaml
   ```
   Edit `homelab.yaml`: set `core.data_dir`, secrets under `authelia`, media paths, service sections, etc.

2. **Generate OIDC signing key** (first install only) — embed PEM in `authelia.jwks_private_key`:
   ```bash
   docker run --rm authelia/authelia:latest \
     authelia crypto pair rsa generate --private-key -
   ```
   Paste the output into `homelab.yaml` under `authelia.jwks_private_key` (YAML `|` block).

3. **Traefik ACME file**
   ```bash
   mkdir -p services/traefik/acme
   touch services/traefik/acme/acme.json
   chmod 600 services/traefik/acme/acme.json
   ```

4. **Start the stack**
   ```bash
   ./bin/homelab up
   ```
   This runs `compose generate` then `docker compose up -d`.

## Homelab CLI

| Command | Description |
| --- | --- |
| `./bin/homelab config validate` | Check required keys in `homelab.yaml` |
| `./bin/homelab compose generate` | Render `compose.tpl.yaml` → `compose.yaml` |
| `./bin/homelab status [service...]` | Container state, health, and Gluetun sidecar issues (exit 1 if any problems) |
| `./bin/homelab up [service...]` | Generate + start (`up gluetun` → full VPN stack; `up prowlarr` → gluetun + prowlarr) |
| `./bin/homelab down/stop [service...]` | Stop only the named service(s) |
| `./bin/homelab start/restart [service...]` | Start/restart (`restart gluetun` → full VPN stack) |
| `./bin/homelab deploy [service...]` | Ansible deploy playbooks |
| `./bin/homelab deploy --all` | Full deploy order |
| `./bin/homelab backup [service...]` | Copy `services/<name>/` → `backups/<name>/<timestamp>/` |
| `./bin/homelab backup --all` | Back up services marked `backup: true` in `config/services.yaml` |
| `./bin/homelab backup mealie --label manual` | Named backup (e.g. `manual-20260929T191045Z`) |
| `./bin/homelab backup --list` | Show which services `--all` includes |
| `./bin/homelab deploy SERVICE --check` | Dry-run deploy (no changes applied) |
| `./bin/homelab deploy SERVICE --check --diff` | Preview compose + Ansible file diffs (compact output) |
| `./bin/homelab deploy SERVICE --check -v` | Dry-run with full Ansible output including skipped tasks |

Service names and deploy playbooks are defined in [`config/services.yaml`](config/services.yaml).

## Service data

Configs and databases live under `services/` (gitignored). Ansible creates the tree on deploy; rendered Compose bind-mounts from `core.data_dir/services/<app>/`.

## Rotating the shared OIDC secret

1. Update `authelia.oidc_client_secret` in `homelab.yaml`.
2. `./bin/homelab deploy authelia`
3. `./bin/homelab up mealie sparkyfitness-server memos`
4. Update Jellyfin and Audiobookshelf if needed (Ansible bootstrap syncs Audiobookshelf OIDC on deploy).

## Audiobookshelf volumes and libraries

In `homelab.yaml`:

```yaml
audiobookshelf:
  volumes:
    - host: /mnt/audiobooks
      container: /audiobooks
    - host: /mnt/media2/Books
      container: /books
  libraries:
    - name: Audiobooks
      media_type: book
      folders:
        - /audiobooks/Books/AudioBooks
        - /books/More
```

Run `./bin/homelab compose generate` (or any `up`/`deploy`) after changes.
