"""Application configuration, loaded from environment variables / .env file."""

import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


# AI parsing
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "claude-haiku-4-5")

# Access control for dashboard + CSV export
APP_SECRET_TOKEN = os.environ.get("APP_SECRET_TOKEN", "")

# Display
CHILD_NAME = os.environ.get("CHILD_NAME", "Our reader")

# All date resolution and timestamps use this timezone
TIMEZONE = os.environ.get("TIMEZONE", "America/New_York")

# Twilio request signature validation (recommended on in production)
TWILIO_VALIDATE = _bool("TWILIO_VALIDATE")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
# Public base URL of this app (e.g. https://readathon.example.com). Needed for
# signature validation when running behind a proxy that rewrites the URL.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")

# Storage
DB_PATH = os.environ.get("DB_PATH", os.path.join("data", "readathon.db"))
CONTACTS_PATH = os.environ.get("CONTACTS_PATH", "contacts.json")
