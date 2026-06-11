"""CSV export of all reading sessions, shared by the web endpoint and the CLI."""

import csv
import io

import db

CSV_HEADER = ["date", "title", "minutes", "reader", "logged_at"]


def build_csv() -> str:
    """All sessions as CSV text (oldest first), ending with a total row.

    Includes a UTF-8 BOM so Excel detects the encoding correctly.
    """
    rows = list(reversed(db.all_sessions()))  # oldest first reads naturally
    buf = io.StringIO()
    buf.write("\ufeff")  # BOM for Excel
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADER)
    total = 0
    for row in rows:
        writer.writerow(
            [row["session_date"], row["title"], row["minutes"], row["reader"], row["received_at"]]
        )
        total += row["minutes"]
    writer.writerow(["Total", "", total, "", ""])
    return buf.getvalue()
