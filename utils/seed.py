"""Заполняет базу начальным списком Pauper-архетипов. Идемпотентно."""

from core.database import SessionLocal
from core.models import Archetype

PAUPER_ARCHETYPES = [
    # Начальный каталог. Порядок меню хранится отдельно в meta_rank и обновляется
    # недельной джобой — seed не должен возвращать устаревший зашитый рейтинг.
    {"name": "Mono Red Madness", "color_emoji": "🔴", "short_name": "MR Madness"},
    {"name": "Blue Terror", "color_emoji": "🔵", "short_name": "UB Terror"},
    {"name": "Grixis Affinity", "color_emoji": "⚙️", "short_name": "Grixis Aff"},
    {"name": "Elves", "color_emoji": "🟢", "short_name": "Elves"},
    {"name": "Jund Wildfire", "color_emoji": "🟤", "short_name": "Jund WF"},
    {"name": "Spy Combo", "color_emoji": "🟢", "short_name": "Spy"},
    {"name": "White Aggro", "color_emoji": "⚪", "short_name": "WW"},
    {"name": "Caw-Gates", "color_emoji": "🔵", "short_name": "Caw-Gates"},
    {"name": "Mono Red Rally", "color_emoji": "🔴", "short_name": "MR Rally"},
    {"name": "Tron", "color_emoji": "⚙️", "short_name": "Tron"},
]


def seed(db=None) -> int:
    """Заполняет архетипы. Принимает опциональную сессию (для тестов).
    Возвращает количество добавленных архетипов."""
    _own_session = db is None
    if _own_session:
        db = SessionLocal()
    try:
        added = 0
        for data in PAUPER_ARCHETYPES:
            existing = db.query(Archetype).filter_by(name=data["name"]).first()
            if not existing:
                db.add(Archetype(**data))
                added += 1
            else:
                existing.color_emoji = data.get("color_emoji", existing.color_emoji)
                existing.short_name = data.get("short_name", existing.short_name)
        db.commit()
        if _own_session:
            print(f"Seeding complete: {added} archetypes added, {len(PAUPER_ARCHETYPES) - added} already existed.")
        return added
    finally:
        if _own_session:
            db.close()
