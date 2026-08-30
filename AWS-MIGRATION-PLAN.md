# AWS Migration Plan — Battery Finder + Pipeline App

## Context

The pipeline app currently ships as a PyInstaller `.exe` (a Windows desktop wrapper around the
same FastAPI server). This creates distribution, update, and reliability problems — especially
for long-running pipeline jobs that die if the laptop sleeps or disconnects.

The goal is a single always-on server that:
- Serves the **Battery Finder web app** to the public at all times
- Makes the **pipeline dashboard** available at `/pipeline/` whenever needed in a browser

Both apps run inside one process, one systemd service, one nginx vhost.

EC2 is chosen over Lightsail because it sits in the AWS VPC, giving a clear path to add
ElastiCache Redis and a load balancer when horizontal scaling is needed later.

## Why No Redis Now

The app uses Python `@lru_cache` (in-process) to hold the entire `vehicle_years`,
`battery_specs`, and `model_aliases` tables in RAM at startup. Every recommendation request reads
from memory — RDS is only hit for writes (feedback, read-counter flush, admin edits, pipeline
runs). Adding Redis between the app and RDS would add network latency for no gain.

Redis becomes necessary only when a second EC2 instance is added (to share cache state across
instances and fix per-process rate limiting). That is a future decision.

---

## Architecture

```
Browser (public)   → app.chlorideexide.co.ke/        → Battery Finder SPA
Browser (pipeline) → app.chlorideexide.co.ke/pipeline/ → Pipeline Dashboard SPA
         ↓
    Route 53 → EC2 t3.small (Ubuntu 22.04)
                 nginx (SSL, port 443)
                      ↓
                 uvicorn (FastAPI, port 8000) — 1 worker, always-on
                 ├── root app.py          →  /api/*  and  /
                 └── pipeline_app mounted →  /pipeline/*
                      ↓
                 RDS db.t3.small (PostgreSQL 15) — private subnet
```

---

## Cost

| Service | Spec | On-demand | 1-yr reserved |
|---|---|---|---|
| EC2 t3.small | 2 vCPU, 2 GB RAM | $17/month | ~$10/month |
| RDS db.t3.small | PostgreSQL 15, 2 GB RAM | $28/month | ~$16/month |
| RDS storage | 20 GB gp3 | $2.30/month | $2.30/month |
| Route 53 | Hosted zone + A record | $1/month | $1/month |
| SSL (Let's Encrypt) | — | Free | Free |
| **Total** | | **~$48/month** | **~$30/month** |

Start on-demand. After 1 month of stable operation, convert both to 1-year reserved to save ~40%.

---

## Code Changes (already applied)

| File | Change |
|---|---|
| `app.py` | Mount `pipeline_app.app` at `/pipeline` (2 lines at bottom) |
| `pipeline_app/app.py` | Static file serving + SPA fallback for `frontend/dist/` (bottom of file) |
| `pipeline_app/frontend/src/lib/api.ts` | `BASE` switches to `/pipeline/api` in production |
| `pipeline_app/frontend/vite.config.ts` | Added `base: '/pipeline/'`, fixed `__dirname` |

---

## Prerequisites

- AWS account with billing set up
- A domain or subdomain (e.g. `app.chlorideexide.co.ke`)
- PostgreSQL dump of existing data if migrating, OR plan to re-run pipelines to repopulate

---

## Phase 1 — AWS Infrastructure

### 1.1 Security Groups

Use the default VPC. Create two security groups:

**`battery-finder-app` (EC2):**
- Inbound: 22 (SSH, your IP only), 80 (HTTP, 0.0.0.0/0), 443 (HTTPS, 0.0.0.0/0)
- Outbound: all

**`battery-finder-db` (RDS):**
- Inbound: 5432 from `battery-finder-app` only
- Outbound: none

### 1.2 Create RDS Instance

1. RDS → Create database → Standard create
2. Engine: PostgreSQL 15, instance: `db.t3.small`, storage: 20 GB gp3
3. DB name: `batteryfinderdb`, set master username + strong password
4. VPC: default, attach `battery-finder-db` security group
5. **Public access: No**
6. Note the endpoint URL

### 1.3 Launch EC2 Instance

1. AMI: Ubuntu Server 22.04 LTS, type: `t3.small`
2. Key pair: create or use existing (save `.pem`)
3. Attach `battery-finder-app` security group, storage: 20 GB gp3
4. Allocate an Elastic IP and associate it

---

## Phase 2 — Server Setup

`ssh -i your-key.pem ubuntu@<elastic-ip>`

### 2.1 Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip nginx certbot python3-certbot-nginx git nodejs npm
curl -fsSL https://bun.sh/install | bash && source ~/.bashrc
```

### 2.2 Clone and Install

```bash
git clone <your-repo-url> /opt/battery-finder
cd /opt/battery-finder
python3.11 -m venv .venv
source .venv/bin/activate
# pipeline set = runtime + data-pipeline deps; this host runs both.
# Use requirements.txt alone for a web-only host.
pip install -r requirements-pipeline.txt
```

### 2.3 Build Both Frontends

```bash
# Main Battery Finder frontend
cd /opt/battery-finder/frontend
bun install && bun run build

# Pipeline dashboard frontend
cd /opt/battery-finder/pipeline_app/frontend
npm install && npm run build
cd /opt/battery-finder
```

### 2.4 Create `.env`

```bash
nano /opt/battery-finder/.env
```

```env
DATABASE_URL=postgresql://<user>:<password>@<rds-endpoint>:5432/batteryfinderdb
ADMIN_COOKIE_SECURE=true
```

```bash
chmod 600 /opt/battery-finder/.env
```

### 2.5 Create Pipeline Directories

```bash
mkdir -p /opt/battery-finder/pipeline_app/cache
mkdir -p /opt/battery-finder/pipeline_app/uploads
```

### 2.6 Run Migrations and Create Admin

```bash
source /opt/battery-finder/.venv/bin/activate
cd /opt/battery-finder
alembic upgrade head
```

There is no CLI script for admin creation — set `ADMIN_BOOTSTRAP_TOKEN` in the environment (SSM), then visit `/admin/setup` once the app is running to create the first admin account. See README's "Create First Admin User" for details.

---

## Phase 3 — systemd Service

```bash
sudo nano /etc/systemd/system/battery-finder.service
```

```ini
[Unit]
Description=Chloride Exide Battery Finder
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/battery-finder
EnvironmentFile=/opt/battery-finder/.env
ExecStart=/opt/battery-finder/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable battery-finder
sudo systemctl start battery-finder
sudo systemctl status battery-finder
```

---

## Phase 4 — nginx + SSL

```bash
sudo nano /etc/nginx/sites-available/battery-finder
```

```nginx
server {
    listen 80;
    server_name app.chlorideexide.co.ke;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/battery-finder /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d app.chlorideexide.co.ke
```

---

## Phase 5 — DNS

In Route 53 → hosted zone:
```
A record:  app.chlorideexide.co.ke  →  <elastic-ip>  TTL 300
```

---

## Phase 6 — Data Migration (if applicable)

Local:
```bash
pg_dump -U <local-user> -d batteryfinderdev -F c -f backup.dump
scp backup.dump ubuntu@<elastic-ip>:/tmp/
```

Server:
```bash
sudo apt install -y postgresql-client
pg_restore -h <rds-endpoint> -U <db-user> -d batteryfinderdb /tmp/backup.dump
```

---

## Phase 7 — Verification Checklist

- [ ] `https://app.chlorideexide.co.ke` loads the Battery Finder home page
- [ ] Make/model/year dropdowns populate
- [ ] Battery recommendation returns a result
- [ ] `https://app.chlorideexide.co.ke/pipeline/` loads the pipeline dashboard login
- [ ] Admin login works on pipeline dashboard
- [ ] Web Validate → run a small batch → status updates live in browser
- [ ] CRSP → upload an Excel file → pipeline starts without error
- [ ] `pipeline_app/cache/` populates after first pipeline run
- [ ] `sudo systemctl status battery-finder` stays green

---

## Update Workflow (after go-live)

```bash
cd /opt/battery-finder
git pull
source .venv/bin/activate
pip install -r requirements-pipeline.txt                      # if requirements changed
alembic upgrade head                                          # if new migrations
cd frontend && bun run build && cd ..                         # if main frontend changed
cd pipeline_app/frontend && npm run build && cd ../..         # if pipeline frontend changed
sudo systemctl restart battery-finder
```

---

## Future Scaling Path

1. Add ElastiCache Redis (same VPC, works natively with EC2)
2. Replace `@lru_cache` decorators with Redis-backed cache
3. Switch `slowapi` to Redis storage backend
4. Add a second EC2 t3.small + Application Load Balancer
5. Convert RDS to Multi-AZ for high availability
