# Deployment

Two halves, deployed independently:

| Half | Where | How |
|---|---|---|
| React frontend | GitHub Pages — `https://toothlessos.github.io/llm-picker/` | `.github/workflows/deploy-frontend.yml`, on push to `main` |
| Django / DRF backend | Your own server | Docker Compose, from `backend/` |

The frontend is a **project** Pages site, so it is served from a subpath — `frontend/vite.config.ts` derives
Vite's `base` from `actions/configure-pages`, and `src/main.tsx` passes the matching `basename` to
`BrowserRouter`. Neither needs touching when you deploy.

Throughout this document, replace **`api.example.com`** with your real API hostname.

---

## 1. Prerequisites

- A server with a public IPv4 address and root or sudo access.
- **An existing reverse proxy (nginx) already serving :80 and :443.** This stack does not terminate TLS
  itself — it publishes the API on **loopback only** and your proxy fronts it. See §5.
- A DNS **A record** for `api.example.com` pointing at that address, and a certificate for that name in your
  proxy. Since Let's Encrypt validates over HTTP, the name must resolve before a certificate can be issued.
- Docker Engine with the Compose v2 plugin (**≥ 2.20**, for `--wait` and `-T`).

Verify DNS before going further:

```bash
dig +short api.example.com     # must print your server's IP
```

> **Why there is no nginx or certbot in this stack.** Let's Encrypt's HTTP-01 challenge requires serving
> `/.well-known/acme-challenge/` on port **80**. If another service already owns that port, an in-stack ACME
> client can never validate — the certificate would never be issued, and the failure is a confusing retry loop
> rather than a clear error. Reusing the proxy that already has a certificate avoids the problem entirely and
> removes two containers, two volumes and a TLS bootstrap phase.

---

## 2. One-time server setup

```bash
# Docker (the distro's `docker.io` package is usually too old for `--wait`)
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker
docker compose version        # must be >= 2.20

# A deploy user. NOTE: membership in `docker` is root-equivalent -- the daemon
# runs as root and a member can mount the host filesystem into a container.
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy

# Firewall. 80/443 are for your existing reverse proxy, not for this stack --
# it publishes nothing but 127.0.0.1:8000, which no firewall rule can expose.
sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw enable

# The checkout that deploys operate on
sudo mkdir -p /opt/llm-picker && sudo chown deploy:deploy /opt/llm-picker
sudo -u deploy git clone https://github.com/ToothlessOS/llm-picker.git /opt/llm-picker
```

The repository is public, so cloning needs no credentials.

> `usermod -aG docker` only takes effect in a **new** login session. Log out and back in before continuing.

---

## 3. Configure `backend/.env`

```bash
cd /opt/llm-picker/backend
cp .env.example .env
chmod 600 .env
```

`.env` is gitignored and untracked, so it survives every redeploy. Fill in:

```bash
# --- Secrets ---------------------------------------------------------------
AA_API_KEY=<your Artificial Analysis key>

# REQUIRED. An *empty* value is worse than a missing one: settings.env() only
# falls back to its default when the variable is UNSET, so `DJANGO_SECRET_KEY=`
# reaches Django as "" and raises ImproperlyConfigured on the first request.
DJANGO_SECRET_KEY=<generate one, below>

# --- Deployment ------------------------------------------------------------
DOMAIN=api.example.com
```

There is no `CERTBOT_EMAIL`: TLS belongs to your host proxy (§5), not to this stack.

Generate the secret key with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

The remaining production values (`DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`,
`DJANGO_CORS_ALLOWED_ORIGINS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_NUM_PROXIES`, `REDIS_URL`,
`SQLITE_PATH`) are **set in `docker-compose.yml`**, not here. That is deliberate: `environment:` beats
`env_file:`, so the deployment's shape is reviewable in one diff and a fresh server cannot come up with
`DEBUG` on because a line was forgotten.

If your Pages site is not `https://toothlessos.github.io`, override the CORS origin by adding
`CORS_ALLOWED_ORIGINS=<your origin>` to `.env`. It must be the **bare origin** — scheme and host only, no
path, no trailing slash.

Validate before starting anything. This catches a missing or empty secret immediately:

```bash
sudo -u deploy docker compose config -q && echo "configuration OK"
```

---

## 4. Deploy

```bash
cd /opt/llm-picker/backend
sudo -u deploy docker compose up -d --build
```

Containers start in a defined order:

1. **`redis`** becomes healthy.
2. **`init`** runs once and exits: `check --deploy`, then `migrate`. It is a one-shot service on purpose —
   `web`, `worker` and `beat` share one image, and letting each migrate on start would mean three concurrent
   writers to one SQLite file. (`collectstatic` is not here; it runs at image build time and WhiteNoise serves
   the result out of the image.)
3. **`web`**, **`worker`** and **`beat`** start, gated on `init` exiting **0**.

`web` publishes **`127.0.0.1:8000` only** — reachable from your proxy on the same host, and from nowhere on
the internet. That is deliberate: publishing on `0.0.0.0` would let clients bypass the proxy, losing TLS and
making every request appear to come from the proxy's own IP for rate-limiting purposes.

Check it:

```bash
sudo -u deploy docker compose ps        # init must read "exited (0)"; web must be "healthy"
sudo -u deploy docker compose logs init # check --deploy + migrate output
curl -s -H 'Host: api.example.com' http://127.0.0.1:8000/api/v1/leaderboard/metadata/ | head -c 300
```

Then seed the database. **The API serves an empty board until this runs:**

```bash
sudo -u deploy docker compose exec web python manage.py refresh_leaderboard --source=all
```

This downloads the LMArena dataset and calls the Artificial Analysis API. It is cached in the `hf_cache`
volume, so later container recreations do not re-download it.

> **Artificial Analysis quota:** the free tier is **100 requests per 24h, shared across every key in the
> organization**, and one full refresh costs **4**. Do not re-run the seed to make a number move — check
> `/api/v1/leaderboard/metadata/` instead. `worker` also runs `refresh_if_stale` on startup, and `beat`
> schedules the refresh twice daily at 08:00 and 20:00 `Asia/Shanghai`.

---

## 5. TLS and the host proxy

TLS is terminated by your existing nginx. Add a server block for `api.example.com`:

```nginx
# HTTP: redirect everything to HTTPS. Keep your existing ACME location block here
# if this host runs certbot -- it must stay on port 80 to serve renewals.
server {
    listen 80;
    listen [::]:80;
    server_name api.example.com;

    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;                      # not `listen 443 ssl http2`, deprecated since nginx 1.25.1
    server_name api.example.com;

    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    location / {
        # Bare form -- no trailing path, or nginx rewrites the URI and every
        # endpoint 404s.
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 10s;
        proxy_send_timeout    60s;
        proxy_read_timeout    60s;
    }
}
```

Then `sudo nginx -t && sudo systemctl reload nginx`.

Three of those headers are load-bearing:

- **`X-Forwarded-Proto $scheme`** — without it Django believes every request arrived over plain HTTP. Because
  `SECURE_SSL_REDIRECT` is on in production, that becomes an **infinite redirect loop**; the admin login also
  breaks, since Django compares the browser's `https://…` Origin against the `http://…` it reconstructed.
- **`X-Forwarded-For $proxy_add_x_forwarded_for`** — this **appends** the client address rather than replacing
  the header. DRF reads the *rightmost* entry (that is what `DJANGO_NUM_PROXIES=1` selects), so a client that
  sends a fabricated header cannot escape its rate-limit bucket. Do **not** use `$http_x_forwarded_for` here,
  which would pass a client-controlled value straight through.
- **`Host $host`** — `DJANGO_ALLOWED_HOSTS` is checked against it. Getting this wrong yields `400
  DisallowedHost` on every request, which `manage.py check --deploy` does **not** catch.

No `/static/` location is needed. WhiteNoise serves it from inside the container, so it reaches the browser
through this same `location /`.

**Renewal** stays with whatever already renews your certificates — this stack has no ACME client by design
(§1).

> If your nginx runs on a **different host** from Docker, `127.0.0.1:8000` is not reachable. Change the publish
> in `docker-compose.yml` to that host's private address — e.g. `"10.0.0.5:8000:8000"` — and never to
> `0.0.0.0`, which would expose the API directly to the internet and defeat both TLS and per-client throttling.

---

## 6. Verify end to end

These go through your proxy and TLS, unlike the loopback check in §4. If §4 passes and these fail, the problem
is the proxy config (§5), not the application.

```bash
cd /opt/llm-picker/backend

# 1. Data is present and fresh
curl -s https://api.example.com/api/v1/leaderboard/metadata/ | head -c 600

# 2. CORS for the deployed frontend -- must print an Access-Control-Allow-Origin header
curl -s -H 'Origin: https://toothlessos.github.io' -D- -o /dev/null \
  https://api.example.com/api/v1/leaderboard/overview/ | grep -i access-control-allow-origin

# 3. beat materialised the schedule (absent until worker + beat run)
sudo -u deploy docker compose exec web python manage.py shell -c \
  "from django_celery_beat.models import PeriodicTask; print(list(PeriodicTask.objects.values_list('name','enabled')))"

# 4. Persistence: the database survives a container recreate
sudo -u deploy docker compose restart web
curl -s https://api.example.com/api/v1/leaderboard/overview/ | head -c 200
```

### The one failure that is silent

Rate limiting fails **open** by design — a cache outage serves the request uncounted rather than 500ing. So a
misconfigured `REDIS_URL` disables rate limiting entirely and *nothing looks broken*. Confirm it is counting:

```bash
sudo -u deploy docker compose exec redis redis-cli --scan --pattern 'leaderboard:throttle:*' | head
```

No keys after real traffic means the API is effectively unlimited. Then confirm per-client counting: from one
machine make ~70 requests in a minute and check that **that** machine starts getting `429` with a readable
`Retry-After`, while a second machine on a different IP still gets `200`. If both are throttled together,
`DJANGO_NUM_PROXIES` is not `1`.

> `DJANGO_NUM_PROXIES=1` is load-bearing, not a tuning knob. At `0` DRF's `get_ident` returns `REMOTE_ADDR`
> and **never reads `X-Forwarded-For`**. Because `web` publishes on loopback and every request arrives via the
> host proxy, `REMOTE_ADDR` is the same address for every visitor on earth — Docker's bridge gateway. The
> 60/min and 2000/day budgets would then apply to the whole internet at once, and the first busy minute would
> take the API down for everyone.

---

## 7. Updating

```bash
cd /opt/llm-picker
sudo -u deploy git fetch --prune origin
sudo -u deploy git checkout --force -B main origin/main
cd backend
sudo -u deploy docker compose up -d --build
```

`git checkout --force` discards any edit made on the server. That is intended — this machine is a deploy
target, not a workspace. `backend/.env` survives (untracked and gitignored), and the database lives on a
volume. **Never run `git clean -fdx`**, which would delete `.env`.

`init` re-runs on every `up`, so migrations and `collectstatic` are applied automatically.

---

## 8. Rollback

```bash
cd /opt/llm-picker
sudo -u deploy git checkout --force <previous-commit-sha>
cd backend && sudo -u deploy docker compose up -d --build
```

Migrations are deliberately **not** reversed — rolling the code back does not require rolling the schema back,
and the extra columns are inert. Migrations in this project are additive; keep them that way, or split a
destructive change into two deploys (add nullable column → deploy → drop the old one).

If you must undo a schema change, restore a snapshot. **There is no automatic backup** — take one yourself
before any deploy that touches migrations (§9), then:

```bash
cd /opt/llm-picker/backend
sudo -u deploy docker compose stop beat worker web
sudo -u deploy docker compose cp ./backup-<STAMP>.sqlite3 web:/tmp/restore.sqlite3
sudo -u deploy docker compose run --rm --no-deps web python -c "
import os, sqlite3
src = sqlite3.connect('/tmp/restore.sqlite3')
dst = sqlite3.connect(os.environ['SQLITE_PATH'])
with dst: src.backup(dst)
"
sudo -u deploy docker compose up -d
```

Use `sqlite3.Connection.backup()`, **not `cp`** — a plain file copy ignores the `-wal` sidecar and can leave a
corrupt database.

---

## 9. Backups

One thing is irreplaceable:

- **The database** — `sqlite_data` volume. Everything in it except the Django admin user can be rebuilt with
  `manage.py refresh_leaderboard`, so back it up mainly to preserve admin accounts and `ModelAlias` edits.

The other volumes (`redis_data`, `hf_cache`) are pure caches — Redis holds only counters and locks, and the
HuggingFace cache re-downloads. Certificates are your host proxy's concern, not this stack's.

Take one **before any deploy that runs migrations**:

```bash
cd /opt/llm-picker/backend
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

# sqlite3.Connection.backup() is the online backup API: safe while the stack is
# serving, and it checkpoints the -wal sidecar correctly, which a plain `cp`
# does not. Written to /tmp (ephemeral) and copied out, so the snapshot never
# mixes into the live data volume.
sudo -u deploy docker compose exec -T web python -c "
import os, sqlite3
src = sqlite3.connect(os.environ['SQLITE_PATH'])
dst = sqlite3.connect('/tmp/backup.sqlite3')
with dst: src.backup(dst)
dst.close(); src.close()
"
sudo -u deploy docker compose cp web:/tmp/backup.sqlite3 "./backup-$STAMP.sqlite3"
ls -la "./backup-$STAMP.sqlite3"
```

Do **not** place these volumes on NFS or CIFS. SQLite's locking is POSIX advisory and corrupts silently on
network filesystems.

---

## 10. Troubleshooting

| Symptom | Cause |
|---|---|
| `docker compose config` fails on a missing variable | A required value is absent or **empty** in `backend/.env`. Empty counts as missing. |
| `init` exits non-zero | Read `docker compose logs init`. Usually a migration error or a missing `AA_API_KEY`. |
| Every request returns `400 DisallowedHost` | `ALLOWED_HOSTS` does not include your hostname. `check --deploy` does **not** catch this. |
| API returns `200` but the browser shows nothing | CORS. The response is missing `Access-Control-Allow-Origin` — check the origin is bare (no path, no trailing slash). |
| Frontend shows an empty board | The backend has not been seeded, or `VITE_API_BASE_URL` points somewhere else. |
| Board never updates | `worker`/`beat` are not running, or `REDIS_URL` cannot reach the `redis` service. |
| Browser shows a redirect loop / `ERR_TOO_MANY_REDIRECTS` | Your proxy is not sending `X-Forwarded-Proto: https`, so Django sees plaintext and `SECURE_SSL_REDIRECT` bounces it back. See §5. |
| Admin login returns `403 CSRF verification failed` | Same cause as above — Django compares the Origin against the scheme it reconstructed. |
| `502 Bad Gateway` from your proxy | `web` is not healthy. `docker compose ps` and `docker compose logs web`. |
| Static files (`/static/…`) 404 | `collectstatic` did not run at image build. Rebuild: `docker compose build web`. |
| Rate limiting appears to do nothing | `REDIS_URL` is wrong; throttling fails open. See §6. |
| `database is locked` | Should not happen — WAL plus a 20s busy timeout plus `IMMEDIATE` transactions are configured. If it does, something is writing outside Celery. |

Useful commands:

```bash
sudo -u deploy docker compose ps
sudo -u deploy docker compose logs -f --tail=100 web
sudo -u deploy docker compose exec web python manage.py check --deploy
sudo -u deploy docker compose exec web python manage.py report_unmatched --format=md
```

---

## 11. Frontend

Already continuous: `.github/workflows/deploy-frontend.yml` runs lint, typecheck and tests, builds, and
publishes to Pages on every push to `main` that touches `frontend/`.

Two one-time settings in the GitHub UI:

1. **Settings → Pages → Source = "GitHub Actions"**. Required — `actions/configure-pages` cannot enable Pages
   with the default token.
2. **Settings → Secrets and variables → Actions → Variables → `VITE_API_BASE_URL`** =
   `https://api.example.com/api/v1/leaderboard/` (trailing slash required).

`VITE_API_BASE_URL` is **inlined into the bundle at build time**. Changing it requires re-running the workflow
(`workflow_dispatch`) — it is not a runtime setting.

---

## 12. Continuous deployment of the backend

**Not yet wired up.** The backend is deployed manually with §7. An SSH-based GitHub Actions workflow was
designed but not implemented; it would:

- run `uv sync --frozen` and `pytest` as a gate (CI needs a dummy `AA_API_KEY`, because
  `test_the_configuration_report_does_not_probe_the_source` asserts it is configured);
- write a deploy key from repository secrets, with a **verified** `known_hosts` entry (`ssh-keyscan` is
  unauthenticated and trusts whatever answers);
- pipe `backend/scripts/deploy.sh` over SSH stdin — that indirection is load-bearing, since the script
  force-checks-out `origin/main` and would otherwise rewrite the file it is executing;
- call `docker compose up -d --build`.

Until then, §7 is the update path.
