"""Заполняет базу начальным списком Pauper-архетипов. Идемпотентно."""

from core.database import SessionLocal
from core.models import Archetype

PAUPER_ARCHETYPES = [
    # Top 10 по данным метагейма (апрель 2026). meta_rank определяет порядок по умолчанию.
    {"name": "Mono Red Madness", "color_emoji": "🔴", "short_name": "MR Madness",  "meta_rank": 1},   # 12.2%
    {"name": "Blue Terror",      "color_emoji": "🔵", "short_name": "UB Terror",   "meta_rank": 2},   # 9.6%
    {"name": "Grixis Affinity",  "color_emoji": "⚙️", "short_name": "Grixis Aff", "meta_rank": 3},   # 8.8%
    {"name": "Elves",            "color_emoji": "🟢", "short_name": "Elves",       "meta_rank": 4},   # 8.0%
    {"name": "Jund Wildfire",    "color_emoji": "🟤", "short_name": "Jund WF",     "meta_rank": 5},   # 5.6%
    {"name": "Spy Combo",        "color_emoji": "🟢", "short_name": "Spy",         "meta_rank": 6},   # 4.3%
    {"name": "White Aggro",      "color_emoji": "⚪", "short_name": "WW",          "meta_rank": 7},   # 4.2%
    {"name": "Caw-Gates",        "color_emoji": "🔵", "short_name": "Caw-Gates",   "meta_rank": 8},   # 3.3%
    {"name": "Mono Red Rally",   "color_emoji": "🔴", "short_name": "MR Rally",    "meta_rank": 9},   # 3.2%
    {"name": "Tron",             "color_emoji": "⚙️", "short_name": "Tron",        "meta_rank": 10},  # ~3%
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
            elif existing.meta_rank != data.get("meta_rank"):
                existing.meta_rank = data.get("meta_rank")
                existing.color_emoji = data.get("color_emoji", existing.color_emoji)
                existing.short_name = data.get("short_name", existing.short_name)
        db.commit()
        if _own_session:
            print(f"Seeding complete: {added} archetypes added, {len(PAUPER_ARCHETYPES) - added} already existed.")
        return added
    finally:
        if _own_session:
            db.close()
