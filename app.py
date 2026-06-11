"""Readathon reading log — SMS intake, dashboard, and CSV export."""

import base64
import hashlib
import hmac
import logging
from datetime import datetime
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from flask import Flask, Response, abort, render_template_string, request

import config
import contacts
import db
import export
import parsing

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
db.init_db()

REPHRASE_HINT = (
    "Sorry, I couldn't find a reading session in that message. "
    'Try something like: "25 min of Dog Man with Grandma today".'
)
ERROR_REPLY = (
    "Sorry, something went wrong logging that. Please try again in a minute, "
    'e.g. "25 min of Dog Man with Grandma today".'
)


# ---------------------------------------------------------------- helpers


def _twiml(message: str) -> Response:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{escape(message)}</Message></Response>"
    )
    return Response(xml, mimetype="application/xml")


def _format_duration(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _valid_twilio_signature(req) -> bool:
    """Validate X-Twilio-Signature per Twilio's spec: HMAC-SHA1 over the full
    request URL concatenated with the sorted POST params, keyed by the auth token."""
    signature = req.headers.get("X-Twilio-Signature", "")
    if not signature or not config.TWILIO_AUTH_TOKEN:
        return False
    if config.PUBLIC_BASE_URL:
        qs = req.query_string.decode()
        url = config.PUBLIC_BASE_URL.rstrip("/") + req.path + (f"?{qs}" if qs else "")
    else:
        url = req.url
    payload = url + "".join(k + v for k, v in sorted(req.form.items()))
    digest = hmac.new(
        config.TWILIO_AUTH_TOKEN.encode(), payload.encode("utf-8"), hashlib.sha1
    ).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


def _require_token():
    token = request.args.get("token", "")
    if not config.APP_SECRET_TOKEN or not hmac.compare_digest(
        token, config.APP_SECRET_TOKEN
    ):
        abort(403)


# ---------------------------------------------------------------- SMS intake


@app.post("/sms")
def sms():
    if config.TWILIO_VALIDATE and not _valid_twilio_signature(request):
        abort(403)

    body = request.form.get("Body", "").strip()
    sender = request.form.get("From", "").strip()

    if not body:
        return _twiml(REPHRASE_HINT)

    try:
        sessions = parsing.parse_message(body)
    except Exception:
        logger.exception("parse failed for message from %s", sender)
        return _twiml(ERROR_REPLY)

    if not sessions:
        return _twiml(REPHRASE_HINT)

    received_at = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat(timespec="seconds")
    lines = []
    for s in sessions:
        reader = contacts.resolve_reader(s.reader, sender)
        db.insert_session(
            session_date=s.date,
            title=s.title,
            minutes=s.minutes,
            reader=reader,
            sender=sender,
            raw_message=body,
            received_at=received_at,
        )
        lines.append(f"{s.title} — {s.minutes} min with {reader} on {s.date}")

    total = db.total_minutes()
    reply = (
        "Logged: "
        + "; ".join(lines)
        + f". Summer total: {total} min ({_format_duration(total)})."
    )
    return _twiml(reply)


# ---------------------------------------------------------------- dashboard


_DASHBOARD_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{{ child_name }}'s Reading Log</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; margin: 2rem auto; max-width: 56rem; padding: 0 1rem; color: #222; }
  h1 { font-size: 1.5rem; }
  .totals { margin: 1rem 0; font-size: 1.1rem; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 0.4rem 0.75rem; border-bottom: 1px solid #ddd; }
  th { background: #f5f5f5; }
  td.num { text-align: right; }
</style>
</head>
<body>
<h1>{{ child_name }}'s Summer Reading</h1>
<p class="totals">
  <strong>{{ total }} minutes</strong> ({{ total_pretty }}) across
  <strong>{{ count }}</strong> session{{ '' if count == 1 else 's' }}.
</p>
<table>
<thead><tr><th>Date</th><th>Title</th><th>Minutes</th><th>Reader</th><th>Logged at</th></tr></thead>
<tbody>
{% for s in sessions %}
<tr>
  <td>{{ s['session_date'] }}</td>
  <td>{{ s['title'] }}</td>
  <td class="num">{{ s['minutes'] }}</td>
  <td>{{ s['reader'] }}</td>
  <td>{{ s['received_at'] }}</td>
</tr>
{% endfor %}
</tbody>
</table>
</body>
</html>"""


@app.get("/dashboard")
def dashboard():
    _require_token()
    total = db.total_minutes()
    return render_template_string(
        _DASHBOARD_TEMPLATE,
        child_name=config.CHILD_NAME,
        sessions=db.all_sessions(),
        total=total,
        total_pretty=_format_duration(total),
        count=db.session_count(),
    )


# ---------------------------------------------------------------- export


@app.get("/export.csv")
def export_csv():
    _require_token()
    return Response(
        export.build_csv(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=reading-log.csv"},
    )


@app.get("/healthz")
def healthz():
    return {"ok": True}


if __name__ == "__main__":
    app.run(debug=True, port=8000)
