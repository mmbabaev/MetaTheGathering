"""
Swap first_name ↔ last_name for the given user IDs.

Usage:
    DATABASE_URL=postgresql://... python3 scripts/swap_names.py 32 33 36 78
    DATABASE_URL=postgresql://... python3 scripts/swap_names.py --file ids.txt
    DATABASE_URL=postgresql://... python3 scripts/swap_names.py --apply 32 33 36

IDs can come from:
  - command-line arguments
  - --file <path>  (one ID per line, lines starting with # ignored)
  - stdin if neither is given

Default is dry-run. Pass --apply to commit changes.
"""

import os
import sys

from sqlalchemy import create_engine, text

# ── parse args ────────────────────────────────────────────────────────────────
args = sys.argv[1:]
apply = "--apply" in args
args = [a for a in args if a != "--apply"]

ids: list[int] = []

if "--file" in args:
    idx = args.index("--file")
    path = args[idx + 1]
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                ids.append(int(line))
elif args:
    ids = [int(a) for a in args]
else:
    for line in sys.stdin:
        line = line.strip()
        if line and not line.startswith("#"):
            ids.append(int(line))

if not ids:
    print("No IDs provided.", file=sys.stderr)
    sys.exit(1)

# ── connect ───────────────────────────────────────────────────────────────────
url = os.environ.get("DATABASE_URL")
if not url:
    print("ERROR: DATABASE_URL not set", file=sys.stderr)
    sys.exit(1)

engine = create_engine(url)

with engine.connect() as conn:
    rows = conn.execute(
        text("SELECT id, first_name, last_name FROM users WHERE id = ANY(:ids)"),
        {"ids": ids},
    ).fetchall()

    by_id = {r[0]: r for r in rows}
    missing = set(ids) - set(by_id)
    if missing:
        print(f"WARNING: IDs not found: {sorted(missing)}", file=sys.stderr)

    print(f"{'DRY-RUN' if not apply else 'APPLY'} — {len(rows)} users to swap:\n")
    for user_id in ids:
        if user_id not in by_id:
            continue
        _, fn, ln = by_id[user_id]
        print(f"  id={user_id}: [{fn} | {ln}]  →  [{ln} | {fn}]")

    if apply:
        for user_id in ids:
            if user_id not in by_id:
                continue
            _, fn, ln = by_id[user_id]
            conn.execute(
                text("UPDATE users SET first_name = :ln, last_name = :fn WHERE id = :id"),
                {"ln": ln, "fn": fn, "id": user_id},
            )
        conn.commit()
        print("\n✅ Done.")
    else:
        print("\n(dry-run — pass --apply to commit)")
