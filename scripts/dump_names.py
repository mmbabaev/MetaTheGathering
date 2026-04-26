"""
Dump all users with both first_name and last_name filled.

Usage:
    DATABASE_URL=postgresql://... python3 scripts/dump_names.py
    DATABASE_URL=postgresql://... python3 scripts/dump_names.py > names.csv
"""

import os
import sys

from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL")
if not url:
    print("ERROR: DATABASE_URL not set", file=sys.stderr)
    sys.exit(1)

engine = create_engine(url)
with engine.connect() as conn:
    rows = conn.execute(
        text(
            "SELECT id, first_name, last_name FROM users "
            "WHERE first_name IS NOT NULL AND first_name != '' "
            "AND last_name IS NOT NULL AND last_name != '' "
            "ORDER BY id"
        )
    )
    print("id,first_name,last_name")
    for row in rows:
        print(f"{row[0]},{row[1]},{row[2]}")
