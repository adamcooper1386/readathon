"""Tests for the web app with the AI parser mocked out."""

import db
import parsing
from parsing import ParsedSession


def _mock_parse(monkeypatch, sessions):
    import app as app_module

    monkeypatch.setattr(app_module.parsing, "parse_message", lambda body: sessions)


def _send_sms(client, body, sender="+15550001111"):
    return client.post("/sms", data={"Body": body, "From": sender})


def test_single_session_stored_with_mapped_reader(client, monkeypatch):
    _mock_parse(
        monkeypatch,
        [ParsedSession(title="Magic Tree House", date="2026-06-11", minutes=25)],
    )
    resp = _send_sms(client, "Tommy read Magic Tree House for 25 minutes today")
    assert resp.status_code == 200
    assert b"Magic Tree House" in resp.data
    assert b"25 min with Mom" in resp.data
    rows = db.all_sessions()
    assert len(rows) == 1
    assert rows[0]["reader"] == "Mom"
    assert rows[0]["minutes"] == 25
    assert rows[0]["raw_message"] == "Tommy read Magic Tree House for 25 minutes today"


def test_named_reader_overrides_sender_map(client, monkeypatch):
    _mock_parse(
        monkeypatch,
        [ParsedSession(title="Charlotte's Web", date="2026-06-11", minutes=30, reader="Grandma")],
    )
    _send_sms(client, "read 3:15 to 3:45 with grandma, Charlotte's Web")
    assert db.all_sessions()[0]["reader"] == "Grandma"


def test_unknown_sender_records_unknown_reader(client, monkeypatch):
    _mock_parse(monkeypatch, [ParsedSession(title="Frog and Toad", date="2026-06-10", minutes=15)])
    _send_sms(client, "Frog and Toad 15 min", sender="+19998887777")
    assert db.all_sessions()[0]["reader"] == "Unknown"


def test_two_sessions_in_one_text_create_two_rows(client, monkeypatch):
    _mock_parse(
        monkeypatch,
        [
            ParsedSession(title="Dog Man", date="2026-06-11", minutes=20),
            ParsedSession(title="Frog and Toad", date="2026-06-11", minutes=15),
        ],
    )
    resp = _send_sms(client, "Dog Man 20 min and Frog and Toad 15 min before bed")
    assert db.session_count() == 2
    assert db.total_minutes() == 35
    assert b"35 min" in resp.data


def test_non_reading_message_stores_nothing_and_asks_to_rephrase(client, monkeypatch):
    _mock_parse(monkeypatch, [])
    resp = _send_sms(client, "thanks, see you tomorrow")
    assert db.session_count() == 0
    assert b"find a reading session" in resp.data


def test_parser_crash_returns_friendly_reply_not_500(client, monkeypatch):
    import app as app_module

    def boom(body):
        raise RuntimeError("api down")

    monkeypatch.setattr(app_module.parsing, "parse_message", boom)
    resp = _send_sms(client, "Dog Man 20 min")
    assert resp.status_code == 200
    assert b"something went wrong" in resp.data
    assert db.session_count() == 0


def test_running_total_accumulates(client, monkeypatch):
    _mock_parse(monkeypatch, [ParsedSession(title="A", date="2026-06-11", minutes=60)])
    _send_sms(client, "A for an hour")
    _mock_parse(monkeypatch, [ParsedSession(title="B", date="2026-06-11", minutes=30)])
    resp = _send_sms(client, "B for half an hour")
    assert b"90 min" in resp.data
    assert b"1h 30m" in resp.data


def test_dashboard_requires_token(client):
    assert client.get("/dashboard").status_code == 403
    assert client.get("/dashboard?token=wrong").status_code == 403
    assert client.get("/dashboard?token=test-token").status_code == 200


def test_export_requires_token(client):
    assert client.get("/export.csv").status_code == 403
    assert client.get("/export.csv?token=test-token").status_code == 200


def test_csv_contains_rows_and_total(client, monkeypatch):
    _mock_parse(
        monkeypatch,
        [
            ParsedSession(title="Dog Man", date="2026-06-11", minutes=20),
            ParsedSession(title="The Gruffalo", date="2026-06-10", minutes=30),
        ],
    )
    _send_sms(client, "two books")
    resp = client.get("/export.csv?token=test-token")
    text = resp.data.decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0] == "date,title,minutes,reader,logged_at"
    assert any("Dog Man" in l for l in lines)
    assert lines[-1].startswith("Total,,50")


def test_sessions_survive_reconnect(client, monkeypatch):
    """Sessions persist in SQLite across connections (restart survival)."""
    _mock_parse(monkeypatch, [ParsedSession(title="A", date="2026-06-11", minutes=10)])
    _send_sms(client, "A 10 min")
    # New connection, same file
    import config

    conn = db.get_conn(config.DB_PATH)
    rows = conn.execute("SELECT * FROM sessions").fetchall()
    conn.close()
    assert len(rows) == 1


def test_parsed_session_validation_filters_bad_durations():
    assert not parsing._is_valid(ParsedSession(title="X", date="2026-06-11", minutes=0))
    assert not parsing._is_valid(ParsedSession(title="X", date="2026-06-11", minutes=-5))
    assert not parsing._is_valid(ParsedSession(title="X", date="not-a-date", minutes=10))
    assert parsing._is_valid(ParsedSession(title="X", date="2026-06-11", minutes=1))


def test_log_page_requires_token_and_lists_contacts(client):
    assert client.get("/log").status_code == 403
    resp = client.get("/log?token=test-token")
    assert resp.status_code == 200
    assert b"Mom" in resp.data  # from the test contacts map


def test_web_log_stores_with_selected_reader(client, monkeypatch):
    _mock_parse(
        monkeypatch,
        [ParsedSession(title="Trudy Ran Away", date="2026-06-10", minutes=15)],
    )
    resp = client.post(
        "/log",
        data={
            "token": "test-token",
            "reader": "Mom",
            "message": "last night before bed we read Trudy Ran Away for 15 minutes",
        },
    )
    assert resp.status_code == 200
    assert b"Logged:" in resp.data
    row = db.all_sessions()[0]
    assert row["reader"] == "Mom"
    assert row["session_date"] == "2026-06-10"  # yesterday, not today
    assert row["sender"] == "+15550001111"  # attributed to Mom's phone


def test_web_log_named_reader_overrides_selection(client, monkeypatch):
    _mock_parse(
        monkeypatch,
        [ParsedSession(title="Dog Man", date="2026-06-11", minutes=20, reader="Grandma")],
    )
    client.post(
        "/log",
        data={"token": "test-token", "reader": "Mom", "message": "Dog Man 20 min with Grandma"},
    )
    assert db.all_sessions()[0]["reader"] == "Grandma"


def test_web_log_rejects_bad_token_and_empty_message(client, monkeypatch):
    resp = client.post("/log", data={"token": "wrong", "reader": "Mom", "message": "x"})
    assert resp.status_code == 403

    _mock_parse(monkeypatch, [])
    resp = client.post("/log", data={"token": "test-token", "reader": "Mom", "message": ""})
    assert b"Please enter" in resp.data
    assert db.session_count() == 0


def test_web_log_non_reading_message_stores_nothing(client, monkeypatch):
    _mock_parse(monkeypatch, [])
    resp = client.post(
        "/log",
        data={"token": "test-token", "reader": "Mom", "message": "hello there"},
    )
    assert b"find a reading session" in resp.data
    assert db.session_count() == 0


def test_privacy_and_terms_are_public_with_required_disclosures(client):
    privacy = client.get("/privacy")
    assert privacy.status_code == 200
    assert b"Message and data rates may apply" in privacy.data
    assert b"third parties" in privacy.data  # non-sharing statement
    assert b"Message frequency" in privacy.data or b"frequency varies" in privacy.data

    terms = client.get("/terms")
    assert terms.status_code == 200
    assert b"Message and data rates may apply" in terms.data
    assert b"STOP" in terms.data
    assert b"HELP" in terms.data


def test_twilio_signature_validation(client, monkeypatch):
    import base64
    import hashlib
    import hmac as hmac_mod

    import app as app_module
    import config

    monkeypatch.setattr(config, "TWILIO_VALIDATE", True)
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", "twilio-secret")
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")

    params = {"Body": "Dog Man 20 min", "From": "+15550001111"}
    url = "http://localhost/sms"
    payload = url + "".join(k + v for k, v in sorted(params.items()))
    sig = base64.b64encode(
        hmac_mod.new(b"twilio-secret", payload.encode(), hashlib.sha1).digest()
    ).decode()

    # Missing/bad signature rejected
    assert client.post("/sms", data=params).status_code == 403
    assert (
        client.post("/sms", data=params, headers={"X-Twilio-Signature": "bogus"}).status_code
        == 403
    )

    # Valid signature accepted
    monkeypatch.setattr(
        app_module.parsing, "parse_message", lambda body: []
    )
    resp = client.post("/sms", data=params, headers={"X-Twilio-Signature": sig})
    assert resp.status_code == 200
