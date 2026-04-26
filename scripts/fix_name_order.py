"""
Detect and fix wrong lastname/firstname order in the users table.

Problems detected:
  1. Wrong order: first_name looks like a surname, last_name looks like a given name → swap
  2. Duplicates: two users whose names are exact reverses of each other

Usage (from repo root):
    python3 scripts/fix_name_order.py           # dry-run (report only)
    python3 scripts/fix_name_order.py --apply   # apply fixes

Or with an explicit DATABASE_URL:
    DATABASE_URL=postgresql://... python3 scripts/fix_name_order.py
"""

import argparse
import os
import sys
from pathlib import Path

# Support running from repo root or from scripts/
_here = Path(__file__).resolve().parent
_root = _here.parent if _here.name == "scripts" else _here
sys.path.insert(0, str(_root))

from sqlalchemy import create_engine, select
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from core import models

# Allow DATABASE_URL override (e.g. when script file is outside the project)
_db_url = os.environ.get("DATABASE_URL")
if _db_url:
    from sqlalchemy.orm import sessionmaker

    _engine = create_engine(_db_url)
    SessionLocal = sessionmaker(bind=_engine)
else:
    from core.database import SessionLocal

_FAMILY_SUFFIXES = (
    "ов",
    "ев",
    "ёв",
    "ин",
    "ын",
    "ый",
    "ий",
    "ой",
    "ский",
    "цкий",
    "ской",
    "ная",
    "ных",
    "ых",
    "ина",
    "ева",
    "ова",
    "ская",
)


def _looks_like_family_name(word: str) -> bool:
    w = word.lower()
    return any(w.endswith(s) for s in _FAMILY_SUFFIXES)


def _norm(s: str) -> str:
    return s.strip().lower().replace("ё", "е")


def _display(user: models.User) -> str:
    fn = user.first_name or ""
    ln = user.last_name or ""
    stored = f"first_name={fn!r} last_name={ln!r}"
    return f"id={user.id} tg={user.tg_id} {stored}"


def find_wrong_order(users: list[models.User]) -> list[models.User]:
    """Users where first_name looks like a surname and last_name doesn't."""
    result = []
    for u in users:
        if u.first_name and u.last_name:
            if _looks_like_family_name(u.first_name) and not _looks_like_family_name(u.last_name):
                result.append(u)
    return result


def find_duplicates(users: list[models.User]) -> list[tuple[models.User, models.User]]:
    """Pairs of users whose names are exact reverses of each other."""
    pairs = []
    seen_ids: set[int] = set()
    for i, u1 in enumerate(users):
        if u1.id in seen_ids or not u1.first_name or not u1.last_name:
            continue
        for u2 in users[i + 1 :]:
            if u2.id in seen_ids or not u2.first_name or not u2.last_name:
                continue
            if _norm(u1.first_name) == _norm(u2.last_name) and _norm(u1.last_name) == _norm(u2.first_name):
                pairs.append((u1, u2))
                seen_ids.add(u1.id)
                seen_ids.add(u2.id)
    return pairs


def pick_canonical(db, u1: models.User, u2: models.User) -> tuple[models.User, models.User]:
    """Return (keep, drop) — prefer real user (tg_id > 0), then one with deck history."""
    real1 = u1.tg_id > 0
    real2 = u2.tg_id > 0
    if real1 and not real2:
        return u1, u2
    if real2 and not real1:
        return u2, u1

    hist1 = db.execute(
        select(models.UserDeckHistory.id).where(models.UserDeckHistory.user_id == u1.id).limit(1)
    ).scalar_one_or_none()
    if hist1:
        return u1, u2
    return u2, u1


def merge_users(db, keep: models.User, drop: models.User) -> None:
    """Transfer all records from drop → keep, then delete drop."""
    db.execute(
        sa_update(models.UserDeckHistory).where(models.UserDeckHistory.user_id == drop.id).values(user_id=keep.id)
    )

    already_in = {
        row[0]
        for row in db.execute(
            select(models.Participant.tournament_id).where(models.Participant.user_id == keep.id)
        ).all()
    }
    if already_in:
        db.execute(
            sa_delete(models.Participant).where(
                models.Participant.user_id == drop.id,
                models.Participant.tournament_id.in_(already_in),
            )
        )
    db.execute(sa_update(models.Participant).where(models.Participant.user_id == drop.id).values(user_id=keep.id))

    db.delete(drop)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix name order and duplicates in users table.")
    parser.add_argument("--apply", action="store_true", help="Apply fixes (default: dry-run)")
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        all_users: list[models.User] = db.execute(select(models.User)).scalars().all()
        print(f"Total users: {len(all_users)}\n")

        # ── 1. Wrong order ─────────────────────────────────────────────────
        wrong = find_wrong_order(all_users)
        print(f"=== Wrong name order ({len(wrong)}) ===")
        for u in wrong:
            print(f"  {_display(u)}  →  swap to: [{u.first_name} {u.last_name}]")
            if args.apply:
                u.first_name, u.last_name = u.last_name, u.first_name

        # ── 2. Duplicates ──────────────────────────────────────────────────
        # Re-fetch after potential swaps so duplicate detection is consistent
        if args.apply and wrong:
            db.flush()

        pairs = find_duplicates(all_users)
        print(f"\n=== Duplicate pairs ({len(pairs)}) ===")
        for u1, u2 in pairs:
            keep, drop = pick_canonical(db, u1, u2)
            print(f"  KEEP  {_display(keep)}")
            print(f"  DROP  {_display(drop)}")
            print()
            if args.apply:
                merge_users(db, keep, drop)

        if args.apply:
            db.commit()
            print("✅ Changes committed.")
        else:
            print("\n(dry-run — pass --apply to commit changes)")

    finally:
        db.close()


if __name__ == "__main__":
    main()
