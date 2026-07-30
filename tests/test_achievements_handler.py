"""Команда /achievements: гейт теневого режима, своя и чужая полка."""

from datetime import timedelta

import pytest

from bot.features import FeatureService
from bot.handlers.achievements import AchievementsHandler
from bot.messages import ACHIEVEMENTS_PLAYER_NOT_FOUND, ACHIEVEMENTS_UNAVAILABLE
from core import models
from core.schemas import TournamentCreate
from services.achievements import AchievementService
from services.feature_flags import FeatureFlags
from services.tournament import TournamentService
from services.user import UserService


@pytest.fixture
def handler(db, ff_svc):
    return AchievementsHandler(AchievementService(db), UserService(db), FeatureService(ff_svc))


@pytest.fixture
def admin(user_svc):
    user = user_svc.get_or_create(tg_id=7001, first_name="Админ", last_name="Главный")
    user.is_admin = True
    return user


@pytest.fixture
def player(user_svc):
    return user_svc.get_or_create(tg_id=7002, first_name="Алиса", last_name="Иванова")


def _played(db, user, archetype):
    created = TournamentService(db).create_tournament(TournamentCreate(title="Pauper 1", chat_id=100))
    t = db.get(models.Tournament, created.id)
    t.club = "Goldfish"
    t.started_at = models.utc_now() - timedelta(days=1)
    TournamentService(db).register_participant(
        tournament_id=t.id, user_id=user.id, archetype_id=archetype.id, deck_added_by_tg_id=user.tg_id
    )
    db.add(
        models.RoundPairing(
            tournament_id=t.id,
            round_number=1,
            player_name="Иванова Алиса",
            opponent_name="Opp1",
            player_wins=2,
            opponent_wins=0,
        )
    )
    db.commit()
    AchievementService(db).process_tournament(t.id)
    return t


def test_player_sees_nothing_while_ui_is_hidden(handler, player):
    result = handler.handle_achievements(tg_id=player.tg_id)

    assert result.text == ACHIEVEMENTS_UNAVAILABLE


def test_player_sees_shelf_once_public_ui_is_on(handler, ff_svc, db, player, archetype_burn):
    _played(db, player, archetype_burn)
    ff_svc.toggle(FeatureFlags.ACHIEVEMENTS_PUBLIC_UI)

    result = handler.handle_achievements(tg_id=player.tg_id)

    assert "Твои ачивки" in result.text
    assert "Дебют" in result.text


def test_admin_sees_own_shelf_in_shadow_mode(handler, admin):
    result = handler.handle_achievements(tg_id=admin.tg_id)

    assert "Твои ачивки" in result.text
    assert "Закрыто" in result.text  # ничего не открыто — только подсказки


def test_admin_can_look_up_another_player(handler, db, admin, player, archetype_burn):
    _played(db, player, archetype_burn)

    result = handler.handle_achievements(tg_id=admin.tg_id, query="Иванова Алиса")

    assert "Ачивки: Иванова Алиса" in result.text
    assert "Дебют" in result.text


def test_unknown_player_reports_clearly(handler, admin):
    result = handler.handle_achievements(tg_id=admin.tg_id, query="Кто-то Неизвестный")

    assert result.text == ACHIEVEMENTS_PLAYER_NOT_FOUND.format(query="Кто-то Неизвестный")
