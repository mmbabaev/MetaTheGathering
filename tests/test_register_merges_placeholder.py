"""Регистрация подтягивает импортный placeholder-дубль (не только шаг ввода имени).

Инцидент: возвращающийся игрок (@Dikaheda, имя уже сохранено) записался в турнир, где
импорт AetherHub уже завёл placeholder «Жижикин Ярослав». Раньше слияние срабатывало только
при вводе имени, поэтому в списке оставались два участника — реальный с колодой и пустой
placeholder. Теперь слияние происходит и при регистрации.
"""

import pytest
from sqlalchemy import select

from bot.handlers.player import PlayerHandler
from core import models
from core.schemas import TournamentCreate

REAL_TG_ID = 172_967_530


@pytest.fixture
def player_handler(svc, user_svc, arch_svc, keyboards, aetherhub_svc, features):
    return PlayerHandler(svc, user_svc, arch_svc, keyboards, aetherhub_svc, features)


@pytest.fixture
def tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Pauper", chat_id=100))


def _placeholder_participant(db, user_svc, svc, tournament_id, first_name, last_name):
    """Как после импорта AetherHub: placeholder-юзер (tg_id<0) + участник без колоды."""
    placeholder, created = user_svc.get_or_create_by_name(first_name, last_name)
    db.commit()
    assert created and placeholder.tg_id < 0
    svc.register_participant(tournament_id=tournament_id, user_id=placeholder.id, archetype_id=None)
    return placeholder


class TestRegisterMergesPlaceholder:
    def test_returning_user_absorbs_placeholder_on_register(
        self, db, player_handler, user_svc, svc, arch_svc, tournament
    ):
        # импорт завёл placeholder «Жижикин Ярослав» без колоды
        placeholder = _placeholder_participant(db, user_svc, svc, tournament.id, "Ярослав", "Жижикин")
        # возвращающийся реальный игрок с уже сохранённым именем (шаг ввода имени НЕ проходит)
        user_svc.get_or_create(tg_id=REAL_TG_ID, username="Dikaheda", first_name="Ярослав", last_name="Жижикин")
        burn = arch_svc.get_or_create_by_name("Red Madness")

        player_handler.handle_archetype(
            tg_id=REAL_TG_ID,
            username="Dikaheda",
            first_name="Ярослав",
            last_name="Жижикин",
            tournament_id=tournament.id,
            archetype_id=burn.id,
        )

        # placeholder-юзер слит и удалён
        assert db.execute(select(models.User).where(models.User.id == placeholder.id)).scalar_one_or_none() is None
        # ровно один участник — реальный, с колодой
        parts = (
            db.execute(select(models.Participant).where(models.Participant.tournament_id == tournament.id))
            .scalars()
            .all()
        )
        assert len(parts) == 1
        assert parts[0].user.tg_id == REAL_TG_ID
        assert parts[0].archetype.name == "Red Madness"

    def test_custom_archetype_registration_also_merges(self, db, player_handler, user_svc, svc, tournament):
        placeholder = _placeholder_participant(db, user_svc, svc, tournament.id, "Ярослав", "Жижикин")
        user_svc.get_or_create(tg_id=REAL_TG_ID, username="Dikaheda", first_name="Ярослав", last_name="Жижикин")

        player_handler.handle_custom_archetype_text(
            tg_id=REAL_TG_ID,
            username="Dikaheda",
            first_name="Ярослав",
            last_name="Жижикин",
            tournament_id=tournament.id,
            name="Homebrew Gates",
        )

        assert db.execute(select(models.User).where(models.User.id == placeholder.id)).scalar_one_or_none() is None
        parts = (
            db.execute(select(models.Participant).where(models.Participant.tournament_id == tournament.id))
            .scalars()
            .all()
        )
        assert len(parts) == 1
        assert parts[0].user.tg_id == REAL_TG_ID

    def test_no_placeholder_registration_is_noop_merge(self, db, player_handler, user_svc, svc, arch_svc, tournament):
        """Нет placeholder — обычная регистрация работает как раньше, без побочек."""
        burn = arch_svc.get_or_create_by_name("Burn")
        player_handler.handle_archetype(
            tg_id=REAL_TG_ID,
            username="newbie",
            first_name="Иван",
            last_name="Петров",
            tournament_id=tournament.id,
            archetype_id=burn.id,
        )
        parts = (
            db.execute(select(models.Participant).where(models.Participant.tournament_id == tournament.id))
            .scalars()
            .all()
        )
        assert len(parts) == 1
        assert parts[0].archetype.name == "Burn"
