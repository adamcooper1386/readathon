"""AI-powered parsing of free-form reading-log texts into structured sessions."""

import logging
from datetime import date, datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

import anthropic
from pydantic import BaseModel

import config

logger = logging.getLogger(__name__)


class ParsedSession(BaseModel):
    title: str
    date: str  # YYYY-MM-DD
    minutes: int
    reader: Optional[str] = None  # only set when the message names the reader


class ParseResult(BaseModel):
    sessions: List[ParsedSession]


_SYSTEM_PROMPT = """You extract children's reading-log sessions from casual text messages \
sent by a parent or caregiver.

Today's date is {weekday}, {today} (timezone: {timezone}).

Return a JSON object with a "sessions" array. One text may describe zero, one, or several \
reading sessions. For each session extract:

- title: the book or material read. If none is named, use "Unspecified".
- date: the calendar date the reading happened, as YYYY-MM-DD. Resolve relative dates \
against today's date: "today" or no date mentioned means {today}; "yesterday" and \
"last night" mean the day before; weekday names mean the most recent past occurrence \
of that weekday.
- minutes: the duration as a whole number of minutes. Convert time ranges \
(e.g. "3:15 to 3:45" is 30) and natural phrases ("half an hour" is 30, "an hour" is 60, \
"a quarter hour" is 15). Omit any session whose duration is zero, negative, or cannot \
be determined.
- reader: the name of the adult who read with the child, ONLY if the message explicitly \
names one (e.g. "with Grandma" -> "Grandma"). Otherwise null. The child being read to is \
not the reader.

If the message contains no reading information at all (greetings, chit-chat, questions), \
return an empty sessions array."""


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def parse_message(body: str) -> List[ParsedSession]:
    """Parse one SMS body into zero or more reading sessions.

    Raises on API errors; callers must handle failures so the service never
    crashes on a single bad message.
    """
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    system = _SYSTEM_PROMPT.format(
        weekday=now.strftime("%A"),
        today=now.date().isoformat(),
        timezone=config.TIMEZONE,
    )

    response = _client().messages.parse(
        model=config.AI_MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": body}],
        output_format=ParseResult,
    )
    result = response.parsed_output
    if result is None:
        raise ValueError("model returned no parseable output")

    return [s for s in result.sessions if _is_valid(s)]


def _is_valid(session: ParsedSession) -> bool:
    if session.minutes <= 0:
        return False
    try:
        date.fromisoformat(session.date)
    except ValueError:
        logger.warning("discarding session with bad date %r", session.date)
        return False
    return True
