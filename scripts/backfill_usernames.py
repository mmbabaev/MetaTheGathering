"""Backfill username для пользователей с tg_id > 0 у которых username IS NULL.

Использует Telegram Bot API getChatMember через группу (бот должен быть её членом).
chat_id групп берётся автоматически из таблицы tournaments.

Запускать: python scripts/backfill_usernames.py [--dry-run] [--limit N]
"""

import argparse
import os
import sys
import time

import requests
from dotenv import load_dotenv
from sqlalchemy import select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

load_dotenv()

from core import models
from core.database import SessionLocal


def get_chat_member(token: str, chat_id: int, tg_id: int, verbose: bool = False) -> dict | None:
    url = f"https://api.telegram.org/bot{token}/getChatMember"
    try:
        r = requests.get(url, params={"chat_id": chat_id, "user_id": tg_id}, timeout=10)
        data = r.json()
        if data.get("ok"):
            return data["result"].get("user")
        if verbose:
            print(f"    getChatMember({chat_id}, {tg_id}): {data.get('error_code')} {data.get('description')}")
        return None
    except Exception as e:
        if verbose:
            print(f"    getChatMember({chat_id}, {tg_id}): HTTP error {e}")
        return None


def resolve_username(token: str, chat_ids: list[int], tg_id: int, verbose: bool = False) -> str | None | bool:
    """Пробует все group chat_ids. Возвращает username, None (нет username в TG) или False (не найден ни в одной группе)."""
    for chat_id in chat_ids:
        user = get_chat_member(token, chat_id, tg_id, verbose=verbose)
        if user is not None:
            return user.get("username")  # None если нет username
    return False  # не нашли ни в одной группе


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Не сохранять изменения")
    parser.add_argument("--limit", type=int, default=None, help="Обработать не более N пользователей")
    parser.add_argument("--verbose", action="store_true", help="Показывать ошибки Telegram API")
    args = parser.parse_args()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN не задан в .env")

    db = SessionLocal()
    try:
        users = (
            db.execute(
                select(models.User).where(
                    models.User.tg_id > 0,
                    models.User.username.is_(None),
                )
            )
            .scalars()
            .all()
        )

        chat_ids = list({row[0] for row in db.execute(select(models.Tournament.chat_id)).all()})
    finally:
        db.close()

    print(f"Группы из БД: {chat_ids}")
    print(f"Найдено пользователей без username: {len(users)}")
    if args.limit:
        users = users[: args.limit]
        print(f"Обрабатываем первые {args.limit}")

    updated = 0
    no_username = 0
    not_found = 0

    for user in users:
        result = resolve_username(token, chat_ids, user.tg_id, verbose=args.verbose)
        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "—"

        if result is False:
            print(f"  [NOT_FOUND] tg_id={user.tg_id} ({name}) — не найден ни в одной группе")
            not_found += 1
        elif result is None:
            print(f"  [NO_USERNAME] tg_id={user.tg_id} ({name}) — username не задан в TG (приватность)")
            no_username += 1
        else:
            print(f"  [UPDATE] tg_id={user.tg_id} ({name}) → @{result}")
            if not args.dry_run:
                db = SessionLocal()
                try:
                    u = db.execute(select(models.User).where(models.User.tg_id == user.tg_id)).scalar_one_or_none()
                    if u:
                        u.username = result
                        db.commit()
                finally:
                    db.close()
            updated += 1

        time.sleep(0.05)

    print(f"\nИтого: обновлено={updated}, без username в TG={no_username}, не найдены в группах={not_found}")
    if args.dry_run:
        print("(dry-run, изменения не сохранены)")


if __name__ == "__main__":
    main()
