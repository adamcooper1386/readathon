#!/usr/bin/env python3
"""Command-line CSV export. Run on the server:

    python export_csv.py                 # prints CSV to stdout
    python export_csv.py reading.csv     # writes to a file
"""

import sys

import db
import export


def main() -> None:
    db.init_db()
    csv_text = export.build_csv()
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8", newline="") as f:
            f.write(csv_text)
        print(f"Wrote {sys.argv[1]}", file=sys.stderr)
    else:
        sys.stdout.write(csv_text)


if __name__ == "__main__":
    main()
