"""Заполняет базу начальным списком Pauper-архетипов. Идемпотентно."""

from core.database import SessionLocal
from core.models import Archetype

PAUPER_ARCHETYPES = [
    # Top 10 по данным метагейма (апрель 2026)
    {"name": "Mono Red Madness", "color_emoji": "🔴", "short_name": "MR Madness"},   # 12.2%
    {"name": "Blue Terror",      "color_emoji": "🔵", "short_name": "UB Terror"},     # 9.6%
    {"name": "Grixis Affinity",  "color_emoji": "⚙️", "short_name": "Grixis Aff"},   # 8.8%
    {"name": "Elves",            "color_emoji": "🟢", "short_name": "Elves"},          # 8.0%
    {"name": "Jund Wildfire",    "color_emoji": "🟤", "short_name": "Jund WF"},        # 5.6%
    {"name": "Spy Combo",        "color_emoji": "🟢", "short_name": "Spy"},            # 4.3%
    {"name": "White Aggro",      "color_emoji": "⚪", "short_name": "WW"},             # 4.2%
    {"name": "Caw-Gates",        "color_emoji": "🔵", "short_name": "Caw-Gates"},      # 3.3%
    {"name": "Mono Red Rally",   "color_emoji": "🔴", "short_name": "MR Rally"},       # 3.2%
    {"name": "Tron",             "color_emoji": "⚙️", "short_name": "Tron"},           # ~3%
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
