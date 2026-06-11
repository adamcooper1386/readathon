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

## Deployment

### Option A — Fly.io (recommended, ~$2–3/month)

The included `Dockerfile` and `fly.toml` keep one small machine always on with
SQLite on a persistent volume.

```sh
fly launch --no-deploy            # accept the existing fly.toml; pick your app name
fly volumes create readathon_data --size 1
fly secrets set ANTHROPIC_API_KEY=sk-ant-... \
                APP_SECRET_TOKEN=$(openssl rand -hex 24) \
                TWILIO_AUTH_TOKEN=... \
                CHILD_NAME=Tommy TIMEZONE=America/New_York \
                PUBLIC_BASE_URL=https://YOUR-APP.fly.dev
fly deploy
```

Then upload the contacts file to the volume:

```sh
fly ssh console -C "sh -c 'cat > /data/contacts.json'" < contacts.json
```

Fly serves HTTPS automatically; point the Twilio webhook at
`https://YOUR-APP.fly.dev/sms`.

### Option B — small VPS (systemd + Caddy)

```sh
# as a deploy user on the server
git clone <this repo> /opt/readathon && cd /opt/readathon
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env       # fill in secrets; set TWILIO_VALIDATE=true
cp contacts.json.example contacts.json && nano contacts.json
```

`/etc/systemd/system/readathon.service`:

```ini
[Unit]
Description=Readathon reading log
After=network.target

[Service]
WorkingDirectory=/opt/readathon
ExecStart=/opt/readathon/.venv/bin/gunicorn --bind 127.0.0.1:8000 --workers 2 app:app
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

```sh
systemctl enable --now readathon
```

Caddy gives you automatic HTTPS — `/etc/caddy/Caddyfile`:

```
readathon.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Point the Twilio webhook at `https://readathon.example.com/sms` and set
`PUBLIC_BASE_URL=https://readathon.example.com` in `.env`.

### Backups

Everything lives in one SQLite file. Copy it periodically:

```sh
sqlite3 data/readathon.db ".backup backup.db"
```

## Correcting a mistyped session

The dashboard is read-only by design. Fix mistakes directly on the server:

```sh
sqlite3 data/readathon.db
sqlite> SELECT id, session_date, title, minutes, reader FROM sessions ORDER BY id DESC LIMIT 5;
sqlite> UPDATE sessions SET minutes = 25 WHERE id = 42;
sqlite> DELETE FROM sessions WHERE id = 43;
```

## Cost

- Twilio number ≈ $1.15/month plus ~$0.0079 per SMS each way.
- Claude Haiku parsing: a typical message costs a fraction of a cent; a whole
  summer of daily texts is well under $1.
- Hosting: ~$2–5/month on Fly.io or any small VPS.
