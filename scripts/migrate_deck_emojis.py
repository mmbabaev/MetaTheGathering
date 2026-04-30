#!/usr/bin/env python3
"""
Ищет в БД архетипы с emoji-префиксом, добавляет маппинги в bot/deck_emoji.py
и обрезает эмоджи в базе (с дедупликацией участников).

Запуск:
    python scripts/migrate_deck_emojis.py
    python scripts/migrate_deck_emojis.py --dry-run   # только показать, не менять
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Добавляем корень проекта в path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / "bot" / ".env")
load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import create_engine, text

from core.config import settings

DECK_EMOJI_PATH = PROJECT_ROOT / "bot" / "deck_emoji.py"
LEADING_EMOJI_RE = re.compile(r"^([^\w]+)\s*(.+)$", re.UNICODE)


def find_emoji_archetypes(conn: object) -> list[tuple[int, str, str, str]]:
    """Возвращает [(id, original_name, emoji_prefix, clean_name), ...]."""
    rows = conn.execute(text("SELECT id, name FROM archetypes ORDER BY name")).fetchall()
    result = []
    for arch_id, name in rows:
        m = LEADING_EMOJI_RE.match(name)
        if m:
            emoji = m.group(1).strip()
            clean = m.group(2).strip()
            result.append((arch_id, name, emoji, clean))
    return result


def add_to_deck_emoji_file(new_mappings: dict[str, str], dry_run: bool) -> None:
    content = DECK_EMOJI_PATH.read_text(encoding="utf-8")
    lines_to_add = []
    for clean_name in sorted(new_mappings):
        emoji = new_mappings[clean_name]
        if f'"{clean_name}"' in content or f"'{clean_name}'" in content:
            print(f"  [skip] '{clean_name}' уже есть в deck_emoji.py")
            continue
        lines_to_add.append(f'    "{clean_name}": "{emoji}",')
        print(f"  [add]  '{clean_name}': '{emoji}'")

    if not lines_to_add:
        print("Нечего добавлять в deck_emoji.py")
        return

    if dry_run:
        print("\n  (dry-run: файл не изменён)")
        return

    insertion = content.rfind("}")
    new_block = "\n".join(lines_to_add) + "\n"
    updated = content[:insertion] + new_block + content[insertion:]
    DECK_EMOJI_PATH.write_text(updated, encoding="utf-8")
    print(f"  ✓ deck_emoji.py обновлён ({len(lines_to_add)} записей)")


def clean_db(conn: object, emoji_archetypes: list, dry_run: bool) -> None:
    for arch_id, original, emoji, clean_name in emoji_archetypes:
        existing = conn.execute(
            text("SELECT id FROM archetypes WHERE name = :n AND id != :id"),
            {"n": clean_name, "id": arch_id},
        ).fetchone()

        if existing:
            target_id = existing[0]
            print(f"  [merge]  '{original}' → '{clean_name}' (id {arch_id} → {target_id})")
            if not dry_run:
                conn.execute(
                    text("UPDATE participants SET archetype_id = :tid WHERE archetype_id = :sid"),
                    {"tid": target_id, "sid": arch_id},
                )
                conn.execute(text("DELETE FROM archetypes WHERE id = :id"), {"id": arch_id})
        else:
            print(f"  [rename] '{original}' → '{clean_name}'")
            if not dry_run:
                conn.execute(
                    text("UPDATE archetypes SET name = :n WHERE id = :id"),
                    {"n": clean_name, "id": arch_id},
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Только показать, не менять")
    args = parser.parse_args()
    dry_run: bool = args.dry_run

    engine = create_engine(str(settings.DATABASE_URL))
    with engine.connect() as conn:
        emoji_archetypes = find_emoji_archetypes(conn)

        if not emoji_archetypes:
            print("Архетипов с emoji-префиксом не найдено. Всё чисто.")
            return

        print(f"Найдено {len(emoji_archetypes)} архетипов с emoji-префиксом:\n")
        for _, original, emoji, clean in emoji_archetypes:
            print(f"  {original!r:<35} →  emoji={emoji!r}, clean={clean!r}")

        print()
        new_mappings = {clean: emoji for _, _, emoji, clean in emoji_archetypes}

        print("=== deck_emoji.py ===")
        add_to_deck_emoji_file(new_mappings, dry_run)

        print("\n=== База данных ===")
        clean_db(conn, emoji_archetypes, dry_run)

        if not dry_run:
            conn.commit()
            print("\n✓ Готово.")
        else:
            print("\n(dry-run: изменения не применены)")


if __name__ == "__main__":
    main()
