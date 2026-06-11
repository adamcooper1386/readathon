# Readathon Reading Log

Track a child's summer reading over SMS. A parent or caregiver texts a dedicated
Twilio number with whatever they read ("25 min of Dog Man with Grandma today"),
Claude parses the message into structured sessions, each session is stored in
SQLite, and the sender gets a confirmation text with the running summer total.
The owner can view a token-protected dashboard or download a CSV at any time.

## How it works

```
SMS → Twilio → POST /sms → Claude (structured parse) → SQLite
                   ↓
        TwiML confirmation reply
```

- **`POST /sms`** — Twilio inbound-message webhook. Parses the text, stores
  sessions, replies with a confirmation and the running total. Optional Twilio
  signature validation.
- **`GET /dashboard?token=...`** — read-only table of all sessions, most recent
  first, with the summer total and session count.
- **`GET /export.csv?token=...`** — CSV of every session (date, title, minutes,
  reader, logged-at) ending with a total row. Opens cleanly in Excel/Sheets.
- **`python export_csv.py [file]`** — same CSV from the server command line.
- **`GET /healthz`** — health check.

Parsing handles multiple sessions per text, relative dates ("yesterday",
"last night", weekday names), time ranges ("3:15 to 3:45" → 30 min), and
natural durations ("half an hour" → 30 min). A named reader ("with Grandma")
overrides the sender's mapped name; unmapped senders are recorded as "Unknown".
Non-reading texts get a friendly reply asking to rephrase, and nothing is
stored. A parsing or API failure never crashes the service — the sender still
gets a reply.

## Local setup

Requires Python 3.10+.

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # fill in ANTHROPIC_API_KEY and APP_SECRET_TOKEN
cp contacts.json.example contacts.json   # map phone numbers to reader names

python app.py                   # dev server on http://localhost:8000
```

Run the tests with `pip install pytest && pytest`.

To test the webhook locally without Twilio:

```sh
curl -s -X POST http://localhost:8000/sms \
  -d "Body=25 min of Dog Man with Grandma today" -d "From=+15551234567"
```

## Configuration

All settings come from environment variables (or a local `.env` file).

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | **yes** | — | Claude API key for message parsing |
| `APP_SECRET_TOKEN` | **yes** | — | Token protecting `/dashboard` and `/export.csv` |
| `CHILD_NAME` | no | `Our reader` | Name shown on the dashboard |
| `TIMEZONE` | no | `America/New_York` | Used for date resolution and timestamps |
| `AI_MODEL` | no | `claude-haiku-4-5` | Switch to e.g. `claude-sonnet-4-6` if parsing misses |
| `TWILIO_VALIDATE` | no | `false` | Reject requests without a valid Twilio signature |
| `TWILIO_AUTH_TOKEN` | if validating | — | Twilio auth token used for signature validation |
| `PUBLIC_BASE_URL` | if validating behind a proxy | — | Public HTTPS base URL, e.g. `https://readathon.example.com` |
| `DB_PATH` | no | `data/readathon.db` | SQLite file — must be on a persistent path |
| `CONTACTS_PATH` | no | `contacts.json` | Phone-number → reader-name map |

`contacts.json` maps full international numbers to names and is re-read on
every message, so you can edit it without restarting:

```json
{"+15551234567": "Mom", "+15559876543": "Grandma"}
```

## Twilio setup

1. Buy a phone number in the [Twilio console](https://console.twilio.com)
   (≈ $1/month + per-message fees).
2. Under **Phone Numbers → Manage → Active numbers → your number →
   Messaging configuration**, set **"A message comes in"** to **Webhook**,
   URL `https://YOUR-DOMAIN/sms`, method **HTTP POST**. Twilio requires HTTPS.
3. For production, set `TWILIO_VALIDATE=true` and `TWILIO_AUTH_TOKEN` (from the
   Twilio console dashboard) so only signed Twilio requests are accepted. If the
   app runs behind a proxy/load balancer, also set `PUBLIC_BASE_URL`.
4. Text the number from a mapped phone and check you get a confirmation back.

## Production deployment — readathonlog.com

Production runs on the existing DigitalOcean droplets behind the load
balancer, deployed by `.github/workflows/deploy.yml` on every push to `main`
(same pattern as the dicey project).

### Architecture: one primary droplet owns the database

The app uses a single SQLite file, which cannot be shared across droplets.
So while the **code deploys to every droplet** (warm standby), the nginx site
for `readathonlog.com` on **every** droplet proxies to one designated
**primary** droplet's VPC private IP on port 3040:

```
Twilio → LB (TLS) → any droplet :80 (nginx) → primary droplet :3040 (gunicorn + SQLite)
```

The load balancer can route a request to any droplet and it still lands on
the same database. UFW restricts port 3040 to the VPC (`10.0.0.0/8`).
Failover: edit the `readathon_primary` upstream IP in
`/etc/nginx/sites-available/readathonlog.com` on each droplet and
`systemctl reload nginx`. The new primary starts with an empty DB unless you
copy `/var/lib/readathon/readathon.db` over.

On each droplet (provisioned by `cloud-init.yaml`):

| Thing | Where |
|---|---|
| App checkout | `/home/adam/readathon` (deployed by the workflow) |
| Virtualenv | `/home/adam/readathon/.venv` |
| Env file | `/home/adam/readathon/.env` (written from the `READATHON_PROD_ENV` secret) |
| Contacts | `/home/adam/readathon/contacts.json` (written from `READATHON_CONTACTS_JSON` if set) |
| SQLite DB | `/var/lib/readathon/readathon.db` (outside the checkout, survives redeploys) |
| Service | `readathon.service` → gunicorn on `0.0.0.0:3040` |
| nginx site | `readathonlog.com` → `http://<primary-private-ip>:3040` |

### One-time setup (manual steps)

1. **GitHub deploy key** — add the public half of the readathon deploy key
   (in `cloud-init.yaml`, comment `readathon-deploy-key`) to this GitHub
   repo under *Settings → Deploy keys* (read-only):

   ```
   ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIACfk+XLx0TjzzlGkVsqYUAISWwb3mPQ0bxVwV2JoMId readathon-deploy-key
   ```

2. **GitHub repo variables** (Settings → Secrets and variables → Actions →
   Variables): `DEPLOY_HOSTS` (droplet IPs, JSON array or whitespace
   separated), `DEPLOY_USER` (`adam`), optionally `DEPLOY_PORT`.

3. **GitHub repo secrets**:
   - `DEPLOY_SSH_KEY` — the existing github-actions deploy SSH private key
     (same one dicey uses; its public half is in cloud-init's
     `ssh_authorized_keys`).
   - `READATHON_PROD_ENV` — the full production env file:

     ```
     ANTHROPIC_API_KEY=sk-ant-...
     APP_SECRET_TOKEN=<openssl rand -hex 24>
     CHILD_NAME=Tommy
     TIMEZONE=America/New_York
     AI_MODEL=claude-haiku-4-5
     TWILIO_VALIDATE=true
     TWILIO_AUTH_TOKEN=<from Twilio console>
     PUBLIC_BASE_URL=https://readathonlog.com
     DB_PATH=/var/lib/readathon/readathon.db
     CONTACTS_PATH=/home/adam/readathon/contacts.json
     ```

   - `READATHON_CONTACTS_JSON` (optional) — the contacts map, e.g.
     `{"+15551234567": "Mom"}`. When set, the workflow rewrites
     `contacts.json` on every deploy (the secret is the source of truth);
     when unset, edit the file on the droplets by hand.

4. **Set the primary droplet's private IP** in the `readathon_primary`
   upstream in `cloud-init.yaml` (placeholder `10.124.0.2`) so future
   droplets get the right value, and in
   `/etc/nginx/sites-available/readathonlog.com` on existing droplets.

5. **Existing droplets** were provisioned before this config existed, so
   apply the new pieces once per droplet (new droplets get all of this from
   cloud-init automatically):

   ```sh
   sudo apt-get install -y python3-venv python3-pip
   sudo install -d -m 755 -o adam -g adam /home/adam/readathon /var/lib/readathon
   # copy from cloud-init.yaml: the readathon deploy key, nginx site, systemd unit
   sudo ufw allow from 10.0.0.0/8 to any port 3040 proto tcp
   sudo ln -sf /etc/nginx/sites-available/readathonlog.com /etc/nginx/sites-enabled/readathonlog.com
   sudo nginx -t && sudo systemctl reload nginx
   sudo systemctl daemon-reload && sudo systemctl enable readathon
   ```

   Also append `/bin/systemctl restart readathon` and
   `/bin/systemctl status readathon` to `/etc/sudoers.d/deploy-restarts`.

6. **DNS + load balancer** — point `readathonlog.com` (and `www`) at the
   load balancer; add a forwarding rule HTTPS 443 (with the LB-managed
   certificate for readathonlog.com) → HTTP 80 on the droplets. The LB
   health check stays on `/` port 80 (served by the nginx `healthcheck`
   site).

7. **Twilio** — set the number's inbound webhook to
   `https://readathonlog.com/sms` (HTTP POST).

8. **Deploy** — push to `main` (or run the workflow manually). Then send a
   test text and check `https://readathonlog.com/dashboard?token=...`.

### Backups

Everything lives in one SQLite file on the primary droplet. Copy it
periodically:

```sh
ssh adam@PRIMARY "sqlite3 /var/lib/readathon/readathon.db '.backup /tmp/readathon-backup.db'"
scp adam@PRIMARY:/tmp/readathon-backup.db ./backups/
```

## Correcting a mistyped session

The dashboard is read-only by design. Fix mistakes directly on the server:

```sh
ssh adam@PRIMARY
sqlite3 /var/lib/readathon/readathon.db
sqlite> SELECT id, session_date, title, minutes, reader FROM sessions ORDER BY id DESC LIMIT 5;
sqlite> UPDATE sessions SET minutes = 25 WHERE id = 42;
sqlite> DELETE FROM sessions WHERE id = 43;
```

## Cost

- Twilio number ≈ $1.15/month plus ~$0.0079 per SMS each way.
- Claude Haiku parsing: a typical message costs a fraction of a cent; a whole
  summer of daily texts is well under $1.
- Hosting: rides on the existing droplets + load balancer, so no extra cost.
