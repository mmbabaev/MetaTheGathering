"""
Seed user_deck_history from results.csv (output of merge_and_fetch.py).

Processes only rows with status == 'fuzzy_ok'.
For each player:
  - upsert user in `users` (tg_id + first/last name from ru_name)
  - ensure each deck exists in `archetypes`
  - insert user_deck_history rows (skip duplicates via ON CONFLICT)

Usage:
    python3 scripts/seed_deck_history.py [--csv scripts/results.csv] [--dry-run]
"""

import argparse
import csv
import sys
from pathlib import Path

# Allow importing project modules from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from core import models
from core.database import SessionLocal

SOURCE = "datalens_import"


def split_ru_name(ru_name: str) -> tuple[str, str | None]:
    """'Бабаев Михаил' → ('Бабаев', 'Михаил'). Single word → (word, None)."""
    parts = ru_name.strip().split(None, 1)
    return parts[0], parts[1] if len(parts) > 1 else None


def upsert_user(db, tg_id: int, ru_name: str, tg_name: str, username: str) -> models.User:
    """Get or create user by tg_id; update name if it was a placeholder."""

    first_name, last_name = split_ru_name(ru_name)
    clean_username = username.lstrip("@") if username and username != "(no username)" else None

    user = db.execute(select(models.User).where(models.User.tg_id == tg_id)).scalar_one_or_none()
    if user is None:
        user = models.User(
            tg_id=tg_id,
            username=clean_username,
            first_name=first_name,
            last_name=last_name,
        )
        db.add(user)
        db.flush()
    else:
        # Update name only if not already set (avoid overwriting manual edits)
        if not user.first_name:
            user.first_name = first_name
            user.last_name = last_name
        if not user.username and clean_username:
            user.username = clean_username

    return user


def get_or_create_archetype(db, name: str) -> models.Archetype:

    arch = db.execute(select(models.Archetype).where(models.Archetype.name == name)).scalar_one_or_none()
    if arch is None:
        arch = models.Archetype(name=name)
        db.add(arch)
        db.flush()
    return arch


def add_deck_history(db, user: models.User, archetype: models.Archetype) -> bool:
    """Insert a user_deck_history row. Returns True if inserted, False if already existed."""

    exists = db.execute(
        select(models.UserDeckHistory).where(
            models.UserDeckHistory.user_id == user.id,
            models.UserDeckHistory.archetype_id == archetype.id,
        )
    ).scalar_one_or_none()

    if exists:
        return False

    db.add(
        models.UserDeckHistory(
            user_id=user.id,
            archetype_id=archetype.id,
            source=SOURCE,
        )
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", default="scripts/results.csv", help="Path to results.csv")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no DB writes")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        sys.exit(f"File not found: {csv_path}")

    rows = []
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["status"] == "fuzzy_ok" and row["ru_name"] and row["decks"]:
                rows.append(row)

    print(f"fuzzy_ok rows with decks: {len(rows)}")

    if args.dry_run:
        for r in rows[:5]:
            print(f"  {r['tg_id']} | {r['ru_name']} | {r['decks'][:60]}")
        print("  ...")
        return

    db = SessionLocal()
    try:
        users_created = 0
        users_updated = 0
        archetypes_created = 0
        history_added = 0

        for row in rows:
            tg_id = int(row["tg_id"])
            ru_name = row["ru_name"]
            deck_names = [d.strip() for d in row["decks"].split(",") if d.strip()]

            existed = db.execute(select(models.User).where(models.User.tg_id == tg_id)).scalar_one_or_none()

            user = upsert_user(db, tg_id, ru_name, row["tg_name"], row["username"])

            if existed is None:
                users_created += 1
            else:
                users_updated += 1

            for deck_name in deck_names:
                arch_existed = db.execute(
                    select(models.Archetype).where(models.Archetype.name == deck_name)
                ).scalar_one_or_none()

                arch = get_or_create_archetype(db, deck_name)
                if arch_existed is None:
                    archetypes_created += 1

                if add_deck_history(db, user, arch):
                    history_added += 1

        db.commit()
        print("Done.")
        print(f"  Users created:     {users_created}")
        print(f"  Users updated:     {users_updated}")
        print(f"  Archetypes created:{archetypes_created}")
        print(f"  History rows added:{history_added}")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
