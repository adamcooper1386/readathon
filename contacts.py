"""Phone-number -> reader-name mapping, kept in an editable JSON file.

The file is re-read on every lookup so the owner can edit it without
restarting the service. Keys are full international numbers, e.g.:

    {"+15551234567": "Mom", "+15559876543": "Grandma"}
"""

import json
import logging
from typing import Optional

import config

logger = logging.getLogger(__name__)

UNKNOWN_READER = "Unknown"


def load_contacts(path: Optional[str] = None) -> dict:
    try:
        with open(path or config.CONTACTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("contacts file %s not found", path or config.CONTACTS_PATH)
        return {}
    except (json.JSONDecodeError, OSError):
        logger.exception("could not read contacts file")
        return {}


def resolve_reader(named_reader: Optional[str], sender: str) -> str:
    """A reader named in the message wins; otherwise fall back to the sender map."""
    if named_reader and named_reader.strip():
        return named_reader.strip()
    return load_contacts().get(sender, UNKNOWN_READER)
