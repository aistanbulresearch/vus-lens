# VUS-Lens — isolated deploy runbook (Hetzner)

Deploys the live demo page to **https://vuslens.aistanbulresearch.com** as a
**self-contained second service** that never touches the main pipeline.

Every step is tagged **[MAIN: none]** (no effect on the main pipeline),
**[MAIN: read-only]** (only inspects it), or **[MAIN: graceful]** (a zero-downtime
nginx reload that also serves the main site). There is **no [MAIN: mutates]** step.
Run everything as a sudo-capable user. Estimated time: ~15 minutes once DNS points.

---

## Why this is isolated (isolation-by-construction)

| Concern | Main pipeline | This deploy | Collision? |
|---|---|---|---|
| Directory | (wherever it lives) | `/opt/vuslens` | No |
| Linux user | (its own) | `vuslens` (new system user) | No |
| Port | (its own) | `127.0.0.1:8001` | No (verified in step 0) |
| systemd unit | (its own) | `vuslens.service` | No |
| Python venv | (its own) | `/opt/vuslens/.venv` | No |
| Env / secrets | (its own) | `/opt/vuslens/vuslens.env` | No (separate key) |
| nginx | (its own server block) | new `vuslens.conf` file | No (additive) |

Even if the main pipeline is the *same* app, this is a **separate instance** on a
separate port with its own process, venv, and config. They share nothing at runtime.

## Subdomain config — confirmed

Because we serve a **subdomain at root** (`vuslens.aistanbulresearch.com/`), **both
knobs stay EMPTY**:

- `VUS_ROOT_PATH=` — empty. `root_path` is only for a sub-*path* mount (e.g.
  `example.com/vuslens`). Here the app is rooted at `/`.
- `VUS_PUBLIC_BASE=` — empty. The browser calls **same-origin** `/api/*` on the
  subdomain; nginx proxies that to `127.0.0.1:8001`. No prefix needed.

(They exist so a future sub-path deploy is a config change, not a code change.)

---

## Prerequisites

- **DNS**: an `A`/`AAAA` record for `vuslens.aistanbulresearch.com` → this server's
  public IP. Create it at the DNS provider first; `dig +short
  vuslens.aistanbulresearch.com` must return the server IP before step 8 (TLS).
- **Packages** (install if missing — none affects the main app):
  ```bash
  sudo apt update
  sudo apt install -y git nginx certbot python3-certbot-nginx
  # uv (Python manager) system-wide, so the vuslens user can use it in setup:
  command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
  ```

---

## Step 0 — Pre-flight checks  [MAIN: read-only]

```bash
# Port 8001 must be FREE (nothing should print):
sudo ss -ltnp | grep ':8001' || echo "8001 free — good"

# Note the main pipeline's service + port so you can confirm it's untouched later.
# Replace <main-service> with its real unit name; write down its port too:
systemctl is-active <main-service> ; sudo ss -ltnp | grep -vE ':(22|80|443)\b' | head

# BASELINE the main site + free memory BEFORE touching anything, so Step 9 can
# prove "still normal, no change". Write both numbers down:
curl -s -o /dev/null -w "main baseline: HTTP %{http_code} in %{time_total}s\n" https://vus.aistanbulresearch.com/
free -h | awk 'NR==1 || /^Mem:/'      # note "available" on this 4 GB box
```

## Step 1 — Isolated user + code  [MAIN: none]

```bash
# New system user; its home IS the app dir. No login shell.
sudo useradd --system --create-home --home-dir /opt/vuslens --shell /usr/sbin/nologin vuslens

# Clone the repo into /opt/vuslens (the bundled data — Turkish Variome
# subset.parquet, cohort/validation JSON — comes WITH the clone; only the API
# key is external).
sudo git clone https://github.com/aistanbulresearch/vus-lens.git /opt/vuslens
sudo chown -R vuslens:vuslens /opt/vuslens
```

## Step 2 — Isolated venv + dependencies  [MAIN: none]

```bash
# Creates /opt/vuslens/.venv from uv.lock and installs the project editable.
# Downloads Python deps into THIS venv only; the main venv is not touched.
cd /opt/vuslens
sudo -u vuslens env HOME=/opt/vuslens uv sync --frozen --no-dev

# Sanity: the venv's uvicorn exists and vus_lens imports from source.
sudo -u vuslens /opt/vuslens/.venv/bin/python -c "import vus_lens; print(vus_lens.__file__)"
# -> /opt/vuslens/backend/vus_lens/__init__.py
```

## Step 3 — Production env file (the API key)  [MAIN: none]

> The key is **yours to paste** — it is never in git and never leaves this file.

```bash
sudo cp /opt/vuslens/deploy/vuslens.env.example /opt/vuslens/vuslens.env
sudo nano /opt/vuslens/vuslens.env      # set ANTHROPIC_API_KEY=<prod key>; leave VUS_* empty
sudo chown vuslens:vuslens /opt/vuslens/vuslens.env
sudo chmod 600 /opt/vuslens/vuslens.env
```

## Step 4 — Smoke-test before systemd  [MAIN: none — binds 8001 only]

Confirms the app boots and serves a real card. (The key is loaded properly by
systemd in step 5; here we only check the process comes up and the deterministic
pipeline answers — `credentials:true` is verified over TLS in step 8.)

```bash
cd /opt/vuslens
sudo -u vuslens /opt/vuslens/.venv/bin/uvicorn vus_lens.web.app:app --host 127.0.0.1 --port 8001 &
sleep 4
curl -s -o /dev/null -w "live:%{http_code}\n" http://127.0.0.1:8001/live          # live:200
curl -s -X POST http://127.0.0.1:8001/api/evaluate -H 'Content-Type: application/json' \
  -d '{"id":"atm-hero"}' | grep -o '"acmg_class":"[^"]*"'   # -> "acmg_class":"Uncertain significance"
sudo pkill -u vuslens -f 'uvicorn vus_lens'      # stop the test process
```

## Step 5 — Install + start the service  [MAIN: none — new unit]

```bash
sudo cp /opt/vuslens/deploy/vuslens.service /etc/systemd/system/vuslens.service
sudo systemctl daemon-reload
sudo systemctl enable --now vuslens
systemctl --no-pager status vuslens        # Active: running
journalctl -u vuslens -n 20 --no-pager
```

## Step 6 — nginx server block  [MAIN: none to install; graceful reload]

```bash
sudo cp /opt/vuslens/deploy/nginx-vuslens.conf /etc/nginx/sites-available/vuslens.conf
sudo ln -s /etc/nginx/sites-available/vuslens.conf /etc/nginx/sites-enabled/vuslens.conf

sudo nginx -t                    # [MAIN: read-only] validates ALL configs; we only ADDED a file
sudo systemctl reload nginx      # [MAIN: graceful] zero-downtime; the main site keeps serving
```

## Step 7 — TLS certificate  [MAIN: none — edits only the vuslens block]

> Requires DNS (prereq) to already resolve to this server.

```bash
sudo certbot --nginx -d vuslens.aistanbulresearch.com
# certbot matches the block by `server_name`, adds the :443 server + HTTP->HTTPS
# redirect INSIDE vuslens.conf, and preserves the SSE proxy directives.
systemctl --no-pager status certbot.timer   # auto-renewal armed
```

## Step 8 — Verify live, end to end  [MAIN: none]

```bash
# 1) Page + real card over TLS
curl -sI https://vuslens.aistanbulresearch.com/live | head -1          # HTTP/2 200
curl -s -X POST https://vuslens.aistanbulresearch.com/api/evaluate \
  -H 'Content-Type: application/json' -d '{"id":"atm-hero"}' \
  | grep -o '"acmg_class":"[^"]*"\|"credentials":[a-z]*'               # VUS + credentials:true

# 2) SSE actually STREAMS through nginx (proves proxy_buffering off + timeouts).
#    You should see several `data: {...}` lines dribble in over ~20s, not all at once:
curl -N -s --max-time 45 "https://vuslens.aistanbulresearch.com/api/reason?key=atm-hero" | head -5
```

Then open **https://vuslens.aistanbulresearch.com/live** in a browser:
toggle **confidence** → Claude's read streams live; type **rs1800562** → a
different variant (HFE / Benign) renders; click each **Try** chip → all resolve.
Check DevTools console: no errors.

## Step 9 — Post-deploy resource + isolation check  [MAIN: read-only]

Confirms vuslens is light AND the main pipeline is unchanged: process, port, and an
actual HTTP response compared against the Step-0 baseline (not merely "active").

```bash
# --- vuslens footprint (single worker; loads subset.parquet once) ---
systemctl show vuslens.service -p MemoryCurrent     # expect ~150-250 MB
sudo ss -ltnp | grep ':8001'                        # only vuslens on 8001

# --- (a) MAIN pipeline (vus.aistanbulresearch.com) still responding NORMALLY ---
systemctl is-active <main-service>                                   # active
curl -s -o /dev/null -w "main now: HTTP %{http_code} in %{time_total}s\n" \
  https://vus.aistanbulresearch.com/                                 # must match the Step-0 baseline
sudo ss -ltnp | grep ':<main-port>'                                  # still listening

# --- (b) RAM headroom on the 4 GB box with BOTH apps running ---
free -h                                             # look at Mem: "available"
systemctl show <main-service> vuslens.service -p MemoryCurrent       # memory of both services
```

Expectations on the 4 GB box: vuslens adds only ~0.2 GB, so **available memory should
stay comfortably above ~1 GB**. If `available` falls under ~300 MB the box was already
tight (not caused by vuslens) — add swap or trim the main app before the demo; the main
pipeline must never be pushed into swap.

**If the main site's HTTP status or latency differs from the Step-0 baseline, STOP and
roll back (below).** The main pipeline must not degrade.

---

## Rollback (full reverse; main pipeline untouched at every step)

```bash
sudo systemctl disable --now vuslens                       # stop + unenable
sudo rm -f /etc/nginx/sites-enabled/vuslens.conf           # unhook nginx
sudo nginx -t && sudo systemctl reload nginx               # graceful; main keeps serving
# optional, if fully removing:
sudo rm -f /etc/systemd/system/vuslens.service && sudo systemctl daemon-reload
sudo certbot delete --cert-name vuslens.aistanbulresearch.com
sudo rm -rf /opt/vuslens && sudo userdel vuslens
```

## Updating to a newer build (later)

```bash
cd /opt/vuslens
sudo -u vuslens git pull
sudo -u vuslens env HOME=/opt/vuslens uv sync --frozen --no-dev
sudo systemctl restart vuslens
```

---

## Operational notes

- **Single worker on purpose.** The reasoning stream reuses an in-process cache
  (`_CACHE`) built by `/api/evaluate`. Multiple workers would send a follow-up
  `/api/reason` to a worker that never saw the evaluate → free-text variants would
  fail. One worker is correct for this demo and plenty for jury traffic. (Presets
  self-heal on cache miss; free-text does not — so keep it single-process.)
- **App binds `127.0.0.1` only.** Port 8001 is never exposed publicly; nginx is the
  sole front door. Keep it that way.
- **Bundled data.** `data/turkish_variome/subset.parquet` (the CC BY demo-gene
  subset) ships in the repo, so no separate data transfer is needed. The large raw
  index under `data/turkish_variome/raw/` is *not* required at runtime.
- **No key → graceful.** If `ANTHROPIC_API_KEY` is unset, `/api/evaluate` still
  returns real deterministic cards; only the streamed reasoning is replaced by a
  "needs credentials" note. So a key mistake degrades, it does not crash.
