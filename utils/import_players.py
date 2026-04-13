"""
Импортирует список игроков из JSON в базу данных.

Формат входного файла:
[
  {"name": "Иван Иванов", "decks": ["Burn", "Affinity"]},
  {"name": "Мария",       "decks": ["Faeries"]}
]

Поле "name": "Имя Фамилия" (первое слово → first_name, остальное → last_name).

Что создаётся:
  - User с синтетическим отрицательным tg_id (placeholder до получения реального)
  - Archetype для каждой уникальной колоды

Идемпотентность: повторный запуск с теми же данными не создаёт дубликатов
(поиск пользователя по имени, архетипа по названию).

Использование:
  python -m utils.import_players players.json
  python -m utils.import_players players.json --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import func, select

from core.database import SessionLocal
from core.models import User, Archetype


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _next_placeholder_tg_id(db) -> int:
    """Следующий свободный отрицательный tg_id (уходит вниз от -1)."""
    min_val = db.execute(select(func.min(User.tg_id))).scalar()
    if min_val is None or min_val >= 0:
        return -1
    return min_val - 1


def _find_user_by_name(db, first_name: str, last_name: str | None) -> User | None:
    q = db.query(User).filter(User.first_name == first_name)
    if last_name:
        q = q.filter(User.last_name == last_name)
    else:
        q = q.filter(User.last_name.is_(None))
    return q.first()


def _parse_name(raw: str) -> tuple[str, str | None]:
    parts = raw.strip().split(None, 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else None
    return first, last


def _get_or_create_archetype(db, name: str, dry_run: bool) -> tuple[Archetype, bool]:
    existing = db.query(Archetype).filter_by(name=name).first()
    if existing:
        return existing, False
    arch = Archetype(name=name)
    if not dry_run:
        db.add(arch)
        db.flush()
    return arch, True


def _get_or_create_user(db, first_name: str, last_name: str | None, dry_run: bool) -> tuple[User, bool]:
    existing = _find_user_by_name(db, first_name, last_name)
    if existing:
        return existing, False
    tg_id = _next_placeholder_tg_id(db)
    user = User(tg_id=tg_id, first_name=first_name, last_name=last_name)
    if not dry_run:
        db.add(user)
        db.flush()
    return user, True


# ---------------------------------------------------------------------------
# main logic
# ---------------------------------------------------------------------------

def run(path: str, dry_run: bool = False) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    if not isinstance(data, list):
        print("Ошибка: JSON должен быть массивом объектов.", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        users_created = 0
        users_skipped = 0
        archetypes_created = 0
        archetypes_skipped = 0
        rows = []

        for entry in data:
            raw_name = entry.get("name", "").strip()
            decks = entry.get("decks", [])

            if not raw_name:
                print(f"  ⚠️  Пропущена запись без имени: {entry}", file=sys.stderr)
                continue

            first_name, last_name = _parse_name(raw_name)
            full_name = f"{first_name} {last_name}" if last_name else first_name

            user, u_created = _get_or_create_user(db, first_name, last_name, dry_run)
            if u_created:
                users_created += 1
                u_status = "✅ создан"
            else:
                users_skipped += 1
                u_status = "— уже есть"

            arch_names = []
            for deck in decks:
                deck = deck.strip()
                if not deck:
                    continue
                arch, a_created = _get_or_create_archetype(db, deck, dry_run)
                if a_created:
                    archetypes_created += 1
                else:
                    archetypes_skipped += 1
                arch_names.append(deck)

            tg_id_display = user.tg_id if not u_created else f"id{user.tg_id}"
            rows.append((full_name, tg_id_display, u_status, ", ".join(arch_names) or "—"))

        if not dry_run:
            db.commit()

        # --- вывод ---
        prefix = "[DRY RUN] " if dry_run else ""
        print(f"\n{prefix}Результат импорта")
        print("=" * 64)
        print(f"{'Игрок':<25} {'tg_id':<12} {'Статус':<16} {'Колоды'}")
        print("-" * 64)
        for name, tg_id, status, decks_str in rows:
            print(f"{name:<25} {str(tg_id):<12} {status:<16} {decks_str}")
        print("=" * 64)
        print(f"Пользователей: {users_created} создано, {users_skipped} пропущено")
        print(f"Архетипов:     {archetypes_created} создано, {archetypes_skipped} пропущено")
        if dry_run:
            print("\n[DRY RUN] — изменения в БД не сохранены.")

    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт игроков из JSON в БД")
    parser.add_argument("file", help="Путь к JSON-файлу")
    parser.add_argument("--dry-run", action="store_true", help="Показать что будет создано, не записывая в БД")
    args = parser.parse_args()
    run(args.file, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
