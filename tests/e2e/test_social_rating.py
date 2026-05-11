"""E2E test: social rating — full flow create → register with deck_added_by → rating."""

import pytest

from bot.handlers.rating import RatingHandler
from core.schemas import TournamentCreate
from services.archetype import ArchetypeService
from services.rating import RatingService
from services.tournament import TournamentService
from services.user import UserService
from tests.e2e.conftest import CHAT_ID


def test_social_rating_full_flow(db, svc):
    """
    Полный флоу:
    1. Три игрока записываются сами (deck_added_by = себе)
    2. Админ добавляет колоды ещё двум игрокам
    3. Рейтинг показывает правильный топ
    """
    user_svc = UserService(db)
    arch_svc = ArchetypeService(db)
    burn = arch_svc.get_or_create_by_name("Burn")
    elves = arch_svc.get_or_create_by_name("Elves")

    t = svc.create_tournament(TournamentCreate(title="Pauper Rating #1", chat_id=CHAT_ID))

    admin = user_svc.get_or_create(tg_id=7001, username="admin_r", first_name="Adminов", last_name="Рейтинг")

    # Игрок A сам записался (1 колода себе)
    player_a = user_svc.get_or_create(tg_id=7002, username="player_a", first_name="Алексей")
    svc.register_participant(
        tournament_id=t.id, user_id=player_a.id, archetype_id=burn.id, deck_added_by_tg_id=player_a.tg_id
    )

    # Игрок B сам записался (1 колода себе)
    player_b = user_svc.get_or_create(tg_id=7003, username="player_b", first_name="Борис")
    svc.register_participant(
        tournament_id=t.id, user_id=player_b.id, archetype_id=elves.id, deck_added_by_tg_id=player_b.tg_id
    )

    # Игрок C сам записался (1 колода себе)
    player_c = user_svc.get_or_create(tg_id=7004, username=None, first_name="Вера")
    svc.register_participant(
        tournament_id=t.id, user_id=player_c.id, archetype_id=burn.id, deck_added_by_tg_id=player_c.tg_id
    )

    # Админ добавил колоды двум игрокам (2 колоды на админа)
    t2 = svc.create_tournament(TournamentCreate(title="Pauper Rating #2", chat_id=CHAT_ID + 1))
    player_d = user_svc.get_or_create(tg_id=7005, username=None, first_name="Денис")
    player_e = user_svc.get_or_create(tg_id=7006, username=None, first_name="Елена")
    svc.register_participant(
        tournament_id=t2.id, user_id=player_d.id, archetype_id=burn.id, deck_added_by_tg_id=admin.tg_id
    )
    svc.register_participant(
        tournament_id=t2.id, user_id=player_e.id, archetype_id=elves.id, deck_added_by_tg_id=admin.tg_id
    )

    # Проверяем подсчёт
    rating_svc = RatingService(db)
    assert rating_svc.count_decks_added_by(admin.tg_id) == 2
    assert rating_svc.count_decks_added_by(player_a.tg_id) == 1
    assert rating_svc.count_decks_added_by(player_b.tg_id) == 1

    # Топ: админ первый (2), остальные по 1
    top = rating_svc.top_deck_contributors(limit=10)
    assert top[0][0].tg_id == admin.tg_id
    assert top[0][1] == 2

    # Хендлер выдаёт правильный текст
    handler = RatingHandler(svc, user_svc)
    result = handler.handle_social_rating(tg_id=player_a.tg_id)
    assert "🥇" in result.text
    assert "Adminов" in result.text or "Рейтинг" in result.text
    assert "2 колоды" in result.text
