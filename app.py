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
    token = request.args.get("token", "") or request.form.get("token", "")
    if not config.APP_SECRET_TOKEN or not hmac.compare_digest(
        token, config.APP_SECRET_TOKEN
    ):
        abort(403)


def _store_sessions(sessions, sender: str, body: str, fallback_reader=None) -> str:
    """Store parsed sessions and return the confirmation text.

    Reader precedence: named in the message > fallback_reader (web form
    selection) > sender's contacts-map entry > "Unknown".
    """
    received_at = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat(timespec="seconds")
    lines = []
    for s in sessions:
        if s.reader and s.reader.strip():
            reader = s.reader.strip()
        elif fallback_reader:
            reader = fallback_reader
        else:
            reader = contacts.resolve_reader(None, sender)
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
    return (
        "Logged: "
        + "; ".join(lines)
        + f". Summer total: {total} min ({_format_duration(total)})."
    )


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

    return _twiml(_store_sessions(sessions, sender, body))


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
  &nbsp;·&nbsp; <a href="/log?token={{ token }}">Log reading</a>
  &nbsp;·&nbsp; <a href="/export.csv?token={{ token }}">Download CSV</a>
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
        token=request.args.get("token", ""),
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


# ---------------------------------------------------------------- web logging


_LOG_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Log Reading — {{ child_name }}</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; margin: 2rem auto; max-width: 36rem; padding: 0 1rem; color: #222; }
  h1 { font-size: 1.5rem; }
  label { display: block; margin: 1rem 0 0.25rem; font-weight: 600; }
  select, textarea { width: 100%; padding: 0.5rem; font: inherit; border: 1px solid #bbb; border-radius: 6px; box-sizing: border-box; }
  textarea { min-height: 6rem; }
  button { margin-top: 1rem; padding: 0.6rem 1.5rem; font: inherit; font-weight: 600; color: #fff; background: #2563eb; border: 0; border-radius: 6px; cursor: pointer; }
  .result { margin: 1rem 0; padding: 0.75rem 1rem; border-radius: 6px; }
  .result.ok { background: #ecfdf5; border: 1px solid #6ee7b7; }
  .result.warn { background: #fffbeb; border: 1px solid #fcd34d; }
  .hint { color: #666; font-size: 0.9rem; margin-top: 0.25rem; }
  nav { margin-top: 2rem; font-size: 0.9rem; }
</style>
</head>
<body>
<h1>Log {{ child_name }}'s Reading</h1>
{% if result %}<div class="result {{ result_kind }}">{{ result }}</div>{% endif %}
<form method="post" action="/log">
  <input type="hidden" name="token" value="{{ token }}">
  <label for="reader">Who are you?</label>
  <select id="reader" name="reader" required>
    {% for name in names %}
    <option value="{{ name }}" {% if name == selected %}selected{% endif %}>{{ name }}</option>
    {% endfor %}
  </select>
  <label for="message">What did you read?</label>
  <textarea id="message" name="message" required
    placeholder="e.g. last night before bed we read Trudy Ran Away for 15 minutes"></textarea>
  <p class="hint">Write it like a text message — books, minutes, and when
  ("yesterday", "last night", "Tuesday") are all understood. Naming someone
  else ("with Grandma") logs them as the reader instead of you.</p>
  <button type="submit">Log it</button>
</form>
<nav><a href="/dashboard?token={{ token }}">View the dashboard</a></nav>
</body>
</html>"""


def _render_log_page(result=None, result_kind="ok", selected=None):
    names = contacts.reader_names() or [contacts.UNKNOWN_READER]
    return render_template_string(
        _LOG_TEMPLATE,
        child_name=config.CHILD_NAME,
        names=names,
        selected=selected,
        token=request.args.get("token", "") or request.form.get("token", ""),
        result=result,
        result_kind=result_kind,
    )


@app.get("/log")
def log_form():
    _require_token()
    return _render_log_page()


@app.post("/log")
def log_submit():
    _require_token()
    reader = request.form.get("reader", "").strip()
    body = request.form.get("message", "").strip()
    if not body:
        return _render_log_page("Please enter what was read.", "warn", reader)

    try:
        sessions = parsing.parse_message(body)
    except Exception:
        logger.exception("parse failed for web log from %s", reader)
        return _render_log_page(ERROR_REPLY, "warn", reader)

    if not sessions:
        return _render_log_page(REPHRASE_HINT, "warn", reader)

    # Attribute the entry to the selected contact's phone number so web logs
    # and texted logs are audited the same way.
    sender = contacts.phone_for(reader) or "web"
    confirmation = _store_sessions(sessions, sender, body, fallback_reader=reader)
    return _render_log_page(confirmation, "ok", reader)


# ------------------------------------------- SMS campaign compliance pages

_LEGAL_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} — Readathon Reading Log</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; margin: 2rem auto; max-width: 44rem; padding: 0 1rem; color: #222; line-height: 1.6; }
  h1 { font-size: 1.5rem; }
  h2 { font-size: 1.15rem; margin-top: 1.5rem; }
  footer { margin-top: 2rem; font-size: 0.9rem; color: #666; }
</style>
</head>
<body>
<h1>{{ title }}</h1>
<p><em>Effective date: {{ effective_date }}</em></p>
{{ body|safe }}
<footer>Readathon Reading Log · <a href="/privacy">Privacy Policy</a> · <a href="/terms">Terms &amp; Conditions</a></footer>
</body>
</html>"""

_EFFECTIVE_DATE = "June 11, 2026"
_CONTACT_EMAIL = "adamcooper1386@gmail.com"

_PRIVACY_BODY = f"""
<p>Readathon Reading Log ("the Service") is a private, family-run SMS service
that lets a small group of invited family members and caregivers log a
child's reading sessions by text message.</p>

<h2>Information we collect</h2>
<p>We collect only what is needed to operate the Service: the mobile phone
numbers of invited participants, the content of the text messages they send
(descriptions of reading sessions), and the date and time each message was
received.</p>

<h2>How we use it</h2>
<p>Messages are used solely to record reading sessions and to send each
sender an automated confirmation reply with a running reading total. The
data is reviewed only by the family that operates the Service.</p>

<h2>No sharing of mobile information</h2>
<p>We do not sell, rent, or share personal information &mdash; including
mobile phone numbers &mdash; with third parties or affiliates for marketing
or promotional purposes. Text messaging originator opt-in data and consent
are not shared with any third party. Message content is processed by our
service providers (Twilio for SMS delivery and Anthropic for automated
message interpretation) only as necessary to operate the Service.</p>

<h2>Message frequency and rates</h2>
<p>Message frequency varies based on how often you choose to text the
Service; you will receive one automated reply per message you send.
<strong>Message and data rates may apply.</strong></p>

<h2>Opting out</h2>
<p>Text <strong>STOP</strong> at any time to stop receiving messages. Text
<strong>HELP</strong> for help. You may also contact us at
<a href="mailto:{_CONTACT_EMAIL}">{_CONTACT_EMAIL}</a>.</p>

<h2>Data retention and security</h2>
<p>Reading-session records are kept for the duration of the reading program
and are stored on access-controlled servers. You may request deletion of
your information at any time using the contact address above.</p>

<h2>Children's privacy</h2>
<p>The Service is used by adults to log a child's reading. The child does
not use the Service directly, and no information is collected from the
child.</p>

<h2>Contact</h2>
<p>Questions about this policy: <a href="mailto:{_CONTACT_EMAIL}">{_CONTACT_EMAIL}</a>.</p>
"""

_TERMS_BODY = f"""
<p>These terms govern the Readathon Reading Log SMS program ("the
Program").</p>

<h2>Program description</h2>
<p>The Program is a private, invitation-only SMS service that lets family
members and caregivers log a child's reading sessions by texting a dedicated
phone number. Each message receives one automated confirmation reply
summarizing what was logged and the running reading total.</p>

<h2>Opt-in</h2>
<p>Participation is limited to family members and caregivers who have asked
to take part. By sending a text message to the Program's phone number, you
consent to receive automated reply messages at that number.</p>

<h2>Message frequency</h2>
<p>Message frequency varies based on your use: you receive one automated
reply for each message you send. No promotional or recurring scheduled
messages are sent.</p>

<h2>Cost</h2>
<p><strong>Message and data rates may apply</strong> according to your
mobile carrier's plan. The Program itself is free to use.</p>

<h2>Opting out and help</h2>
<p>Text <strong>STOP</strong> to cancel at any time; after that you will
receive no further messages (a single confirmation of your opt-out may be
sent). Text <strong>START</strong> to rejoin. Text <strong>HELP</strong> or
email <a href="mailto:{_CONTACT_EMAIL}">{_CONTACT_EMAIL}</a> for help.</p>

<h2>Carriers</h2>
<p>Mobile carriers are not liable for delayed or undelivered messages.</p>

<h2>Privacy</h2>
<p>See our <a href="/privacy">Privacy Policy</a> for how we handle your
information, including our commitment not to share mobile numbers with
third parties for marketing purposes.</p>

<h2>Changes and contact</h2>
<p>We may update these terms from time to time; the current version is
always available at this page. Questions:
<a href="mailto:{_CONTACT_EMAIL}">{_CONTACT_EMAIL}</a>.</p>
"""


@app.get("/privacy")
def privacy():
    return render_template_string(
        _LEGAL_PAGE_TEMPLATE,
        title="Privacy Policy",
        effective_date=_EFFECTIVE_DATE,
        body=_PRIVACY_BODY,
    )


@app.get("/terms")
def terms():
    return render_template_string(
        _LEGAL_PAGE_TEMPLATE,
        title="SMS Terms & Conditions",
        effective_date=_EFFECTIVE_DATE,
        body=_TERMS_BODY,
    )


@app.get("/healthz")
def healthz():
    return {"ok": True}


if __name__ == "__main__":
    app.run(debug=True, port=8000)
