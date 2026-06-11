import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Configure before app modules import config.
os.environ.setdefault("APP_SECRET_TOKEN", "test-token")
os.environ.setdefault("TIMEZONE", "America/New_York")
os.environ.setdefault("CHILD_NAME", "Testy")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "CONTACTS_PATH", str(tmp_path / "contacts.json"))
    monkeypatch.setattr(config, "APP_SECRET_TOKEN", "test-token")
    monkeypatch.setattr(config, "TWILIO_VALIDATE", False)

    (tmp_path / "contacts.json").write_text('{"+15550001111": "Mom"}')

    import db
    import app as app_module

    db.init_db()
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c
