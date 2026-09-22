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
| `playbooks/site.yml` | Deploy the full Docker Compose stack |
| `playbooks/bootstrap-dispatcharr.yml` | Create Dispatcharr superuser (idempotent) |
| `playbooks/bootstrap-yamtrack.yml` | Promote an existing Yamtrack user to admin |
| `playbooks/bootstrap-apps.yml` | Run both bootstrap playbooks |

## Usage

From the `ansible/` directory:

```bash
# Deploy everything
ansible-playbook playbooks/site.yml

# Create Dispatcharr admin (reads credentials from .env)
ansible-playbook playbooks/bootstrap-dispatcharr.yml

# Promote Yamtrack user to admin (user must exist — log in via Authelia first)
ansible-playbook playbooks/bootstrap-yamtrack.yml

# Both bootstraps
ansible-playbook playbooks/bootstrap-apps.yml
```

### Dry run (`--check`)

Preview Compose changes without applying them:

```bash
ansible-playbook playbooks/site.yml --check
ansible-playbook playbooks/site.yml --check --diff   # show config diffs where supported
```

Bootstrap playbooks (`bootstrap-*.yml`) are not fully simulatable in check mode — Docker exec steps are skipped. Use `--check` on `site.yml` only; run bootstraps for real when testing admin setup.

### Reset app data for bootstrap testing

Stop the services, wipe their data dirs (keeps `.keep`), then re-run the playbooks:

```bash
cd ..   # repo root
docker compose stop yamtrack yamtrack-redis dispatcharr
rm -rf yamtrack/db/* yamtrack/redis/*
rm -rf dispatcharr/data/*
# Do not use `docker compose run dispatcharr ...` for cleanup — it runs as root and creates root-owned files.

cd ansible
ansible-playbook playbooks/bootstrap-dispatcharr.yml
# Log in to Yamtrack via Authelia once, then:
ansible-playbook playbooks/bootstrap-yamtrack.yml
```

## Required `.env` variables

### Dispatcharr bootstrap

```env
DISPATCHARR_ADMIN_USERNAME=mike
DISPATCHARR_ADMIN_PASSWORD=your-secure-password
DISPATCHARR_ADMIN_EMAIL=mike@example.com
```

### Yamtrack admin promotion

```env
YAMTRACK_ADMIN_USERNAME=mike
```

Log in to Yamtrack via Authelia once before running the Yamtrack playbook so the user record exists.

## Notes

- Playbooks use `community.docker.docker_compose_v2` and pass your `.env` file to Compose.
- Dispatcharr bootstrap waits on `http://127.0.0.1:9191` (published on Gluetun).
- Web signup is disabled (`DISPATCHARR_SETUP_ALLOWED_IP=127.0.0.1`). Run `bootstrap-dispatcharr.yml` after `site.yml` to create the admin.
- Starting Gluetun always includes all `network_mode: service:gluetun` sidecars (Sonarr, Radarr, etc.) so a Gluetun recreate cannot orphan them.
- Yamtrack bootstrap waits for the container to be running, then promotes the user via Django shell.
- Tasks that handle passwords use `no_log: true` so secrets are not printed in Ansible output.
