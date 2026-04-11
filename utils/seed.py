"""Заполняет базу начальным списком Pauper-архетипов. Идемпотентно."""

from core.database import SessionLocal
from core.models import Archetype

PAUPER_ARCHETYPES = [
    {"name": "Burn", "color_emoji": "🔴", "short_name": "RDW"},
    {"name": "Affinity", "color_emoji": "⚙️", "short_name": "Affinity"},
    {"name": "Faeries", "color_emoji": "🔵", "short_name": "UB Faeries"},
    {"name": "Mono-Blue Faeries", "color_emoji": "🔵", "short_name": "MUF"},
    {"name": "Goblins", "color_emoji": "🔴", "short_name": "Goblins"},
    {"name": "Bogles", "color_emoji": "🟢", "short_name": "Bogles"},
    {"name": "Stompy", "color_emoji": "🟢", "short_name": "Stompy"},
    {"name": "Dimir Control", "color_emoji": "🔵", "short_name": "UB Control"},
    {"name": "Izzet Faeries", "color_emoji": "🔵", "short_name": "UR Faeries"},
    {"name": "Elves", "color_emoji": "🟢", "short_name": "Elves"},
    {"name": "Boros Bully", "color_emoji": "🟡", "short_name": "WR Bully"},
    {"name": "Tron", "color_emoji": "⚙️", "short_name": "Tron"},
    {"name": "Caw-Gate", "color_emoji": "⚪", "short_name": "Caw-Gate"},
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
        db.commit()
        if _own_session:
            print(f"Seeding complete: {added} archetypes added, {len(PAUPER_ARCHETYPES) - added} already existed.")
        return added
    finally:
        if _own_session:
            db.close()
