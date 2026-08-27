# Infrastructure

## Overview

```
GitHub (push/PR)
    │
    ▼
GitHub Actions
    │
    ├── Tests (pytest + ruff + alembic heads check)
    │
    ├── deploy_bot_debug.sh  ──────────────► Server: meta-the-gathering[-debug]
    └── deploy_web_debug.sh  ──────────────► Server: meta-the-gathering[-debug]-web
```

**Server:** `158.160.9.28` (Yandex Cloud), user `mbabaev`

---

## Environments

| | Production | Debug |
|---|---|---|
| Trigger | push to `main` | open PR to `main` |
| Directory | `/home/mbabaev/MetaTheGathering/meta_the_gathering` | `/home/mbabaev/MetaTheGathering/meta_the_gatheringDebug` |
| Bot service | `meta-the-gathering` | `meta-the-gathering-debug` |
| Web service | `meta-the-gathering-web` | `meta-the-gathering-debug-web` |
| OTel service | `otel-collector` | `otel-collector-debug` |
| Env file | `bot/.env` | `bot/.env.debug` |
| Database schema | default | `metagatherer_pr_<PR number>` |
| Web port | `8080` (127.0.0.1) | `8081` (0.0.0.0) |
| BOT_ENV | `prod` | `debug` |

---

## GitHub Actions

### `deploy.yml` — Production deploy

Trigger: push to `main`

Steps:
1. Setup SSH from `SSH_PRIVATE_KEY` secret
2. Write `ENV_FILE` secret → `bot/.env`
3. Run `bot/deploy_bot.sh` (→ `deploy_bot_debug.sh --release`)

### `deploy_web.yml` — Production web deploy

Trigger: push to `main`, only when `web/**`, `bot/systemd/meta-the-gathering-web.service`, or `bot/deploy_web*.sh` changed

Steps:
1. Setup SSH
2. Run `bot/deploy_web.sh` (→ `deploy_web_debug.sh --release`)

### `pr.yml` — PR pipeline

Trigger: PR to `main`

Jobs run in order: tests, then one serialized debug deploy job:

**test:**
- `pip install` + `ruff check` + alembic heads check + `pytest`
- Env: `TELEGRAM_BOT_TOKEN=0000000000:test_token_for_ci`, `DATABASE_URL=sqlite:///:memory:`

**deploy-debug** (needs: test):
- Write `ENV_FILE_DEBUG` secret → `bot/.env.debug`
- Add the non-secret `DATABASE_SCHEMA=metagatherer_pr_<PR number>` override
- Run `bot/deploy_bot_debug.sh`
- The bot deploy installs the full repository and restarts both debug bot and debug web

The PR pipeline does not call `deploy_web_debug.sh` afterwards: that would upload and
install the same repository twice. The standalone web script remains available for the
path-filtered production workflow and manual web-only operations.

The deploy job shares a GitHub Actions concurrency group with other debug deploys.
The scripts also acquire the same environment-specific remote `flock`, so a manual
deploy cannot mutate the directory and virtualenv concurrently with CI.

### GitHub Secrets

| Secret | Used by | Description |
|---|---|---|
| `SSH_PRIVATE_KEY` | all deploy jobs | Private key for `mbabaev@158.160.9.28` |
| `SERVER_HOST` | all deploy jobs | `158.160.9.28` (used for `ssh-keyscan`) |
| `ENV_FILE` | `deploy.yml` | Full contents of prod `bot/.env` |
| `ENV_FILE_DEBUG` | `pr.yml` | Full contents of debug `bot/.env.debug` |

---

## Deploy Scripts

### `bot/deploy_bot_debug.sh`

Deploys the Telegram bot. `deploy_bot.sh` is a thin wrapper that calls it with `--release`.

```
Local machine                          Server
─────────────────────────────────────────────────────────────
tar archive (excludes .env*, tests,
  __pycache__, venv, .git)
  │
  check /tmp has archive size + 200 MiB free
  scp archive → unique /tmp path
  scp env file → unique /tmp path
  │
  ssh remote under environment deploy lock:
    debug: remove stale alembic/versions left by another PR
    extract archive → REMOTE_DIR
    mv unique env file → bot/.env[.debug]
    python3 -m venv venv
    pip install -r requirements.txt
    source bot/.env[.debug]
    alembic heads check (abort if > 1)
    alembic upgrade head
    install otelcol if missing
    systemctl restart otel-collector[-debug]
    systemctl restart meta-the-gathering[-debug]
    systemctl restart meta-the-gathering-debug-web  (debug only)
  always delete this deploy's local and remote temporary files
```

### `bot/deploy_web_debug.sh`

Deploys the web UI only. `deploy_web.sh` is a thin wrapper that calls it with `--release`.

```
Local machine                          Server
─────────────────────────────────────────────────────────────
tar archive (same excludes as bot,
  plus .claude/, .ruff_cache/, etc.)
  │
  check /tmp has archive size + 200 MiB free
  scp archive → unique /tmp path
  │
  ssh remote under the same environment deploy lock:
    check bot/.env[.debug] exists (abort if not)
    extract archive → REMOTE_DIR
    pip install -r requirements.txt
    source bot/.env[.debug]
    alembic heads check
    alembic upgrade head
    systemctl restart meta-the-gathering[-debug]-web
  always delete this deploy's local and remote temporary files
```

**Note:** The web deploy does not upload the env file — it expects `bot/.env.debug`
to already be on the server. In the PR pipeline it starts only after the bot deploy;
for a first manual deploy to a fresh server, run the bot deploy first.

PR previews share a PostgreSQL database server but use a separate schema per PR. An
unmerged migration therefore cannot contaminate another PR's Alembic history. The
legacy/default debug schema is not dropped or reset automatically. Preview-schema
retention and a stable staging environment from `main` remain tracked in
[#270](https://github.com/mmbabaev/MetaTheGathering/issues/270).

---

## Env Files

Env files are **never committed** to git (`.gitignored`). They are:
- Delivered to the server by `deploy_bot_debug.sh` (via GitHub Actions secrets)
- Read by systemd `EnvironmentFile=` directive at service start
- Sourced by the deploy script before running alembic migrations

### Location on server

| Environment | Path |
|---|---|
| Production | `/home/mbabaev/MetaTheGathering/meta_the_gathering/bot/.env` |
| Debug | `/home/mbabaev/MetaTheGathering/meta_the_gatheringDebug/bot/.env.debug` |

### Variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | Bot token from @BotFather |
| `DATABASE_URL` | yes | PostgreSQL DSN, e.g. `postgresql+psycopg2://user:pass@localhost/dbname` |
| `DATABASE_SCHEMA` | no | PostgreSQL schema override; CI sets `metagatherer_pr_<PR number>` for debug previews |
| `ADMIN_IDS` | no | Comma-separated Telegram user IDs with admin access |
| `MONIUM_PROJECT` | no | Monium monitoring project ID |
| `MONIUM_API_KEY` | no | Monium API key |
| `YOOKASSA_SHOP_ID` | no | YooKassa shop ID for payments |
| `YOOKASSA_SECRET_KEY` | no | YooKassa secret key |
| `PAYMENT_AMOUNT` | no | Payment amount (default: `525.00`) |
| `WEB_SECRET_KEY` | no | Session secret for web UI (default: `dev-secret-change-in-prod`) |
| `WEB_BASE_URL` | no | Public URL of the web UI |
| `WEB_PORT` | no | Web UI port (default: `8080`) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | no | SMTP config for email |
| `CELLAR_COORDINATOR_USERNAMES` | no | Preferred production-only comma-separated Telegram usernames. They receive immediate booking/cancellation DMs and the one-hour pre-event summary, and can view the `/cellar` booking overview. Debug ignores the list. |
| `CELLAR_COORDINATOR_TG_IDS` | no | Optional legacy comma-separated IDs with the same production-only notifications and access. |

`BOT_ENV=debug` is set via the systemd `Environment=` directive (not in the env file).

---

## Systemd Services

All services run as user `mbabaev`. Logs via `journalctl`.

```bash
# View logs
sudo journalctl -u meta-the-gathering -f
sudo journalctl -u meta-the-gathering-debug -f

# Restart
sudo systemctl restart meta-the-gathering
sudo systemctl restart meta-the-gathering-debug

# Status
sudo systemctl status meta-the-gathering --no-pager -l
```

### Service dependencies

```
otel-collector[-debug]
    │
    └── meta-the-gathering[-debug]
            │
            └── meta-the-gathering[-debug]-web
```

Each service waits for the previous one (`After=`) before starting.

---

## OpenTelemetry Collector

Installed at `/usr/local/bin/otelcol` (version 0.114.0).
Config: `otel-collector.yaml` in the deployment directory.
Reads credentials from the same `EnvironmentFile` as the bot.

The deploy script installs otelcol automatically if the binary is missing.

---

## Manual Operations

### First deploy to a fresh server

```bash
# 1. Create directories
ssh mbabaev@158.160.9.28 'mkdir -p /home/mbabaev/MetaTheGathering/meta_the_gatheringDebug/bot'

# 2. Upload env file
scp bot/.env.debug mbabaev@158.160.9.28:/home/mbabaev/MetaTheGathering/meta_the_gatheringDebug/bot/.env.debug

# 3. Push to trigger CI, or run deploy locally:
PREVIEW_ID=271 bash bot/deploy_bot_debug.sh  # debug (use the relevant PR number)
bash bot/deploy_bot.sh            # prod
```

### Useful SSH shortcuts

```bash
# Tail logs
ssh mbabaev@158.160.9.28 'sudo journalctl -u meta-the-gathering-debug -f'

# Restart bot
ssh mbabaev@158.160.9.28 'sudo systemctl restart meta-the-gathering-debug'

# Check all services
ssh mbabaev@158.160.9.28 'sudo systemctl status meta-the-gathering meta-the-gathering-debug meta-the-gathering-debug-web --no-pager'
```

Or via `server.sh`:

```bash
./server.sh remote-logs debug
./server.sh remote-restart debug
./server.sh remote-status debug
```
