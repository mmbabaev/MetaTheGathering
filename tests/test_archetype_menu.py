"""Тесты для нового меню выбора архетипа:
- TournamentService.list_top_archetypes
- TournamentService.list_user_recent_archetypes
- build_archetype_list (чистая функция)
- PlayerHandler.handle_register (интеграция)
- PlayerHandler.handle_archetype_more (интеграция)
- AdminHandler.handle_admin_pick_arch (интеграция)
- AdminHandler.handle_admin_arch_more (интеграция)
"""

import pytest
from core.schemas import TournamentCreate
from services.tournament import TournamentService, ArchetypeItem
from services.user import UserService
from bot.handlers.player import PlayerHandler, build_archetype_list, ARCHETYPE_COLLAPSED_COUNT
from bot.handlers.admin import AdminHandler

CHAT_ID = 200
ADMIN_TG_ID = 9999
PLAYER_TG_ID = 1111


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def active_tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Weekly", chat_id=CHAT_ID, slug="w"))


@pytest.fixture
def admin_user(svc, user_svc):
    u = user_svc.get_or_create(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin")
    from core import models
    from sqlalchemy import select
    obj = svc.db.execute(select(models.User).where(models.User.tg_id == ADMIN_TG_ID)).scalar_one()
    obj.is_admin = True
    svc.db.commit()
    return u


@pytest.fixture
def player_handler(svc, user_svc):
    return PlayerHandler(svc, user_svc)


@pytest.fixture
def admin_handler(svc, user_svc):
    return AdminHandler(svc, user_svc)


# ---------------------------------------------------------------------------
# 1. list_top_archetypes
# ---------------------------------------------------------------------------

class TestListTopArchetypes:
    def test_empty_db_returns_empty(self, svc):
        assert svc.list_top_archetypes() == []

    def test_returns_archetypes_ordered_by_usage_count_desc(self, svc, user_svc):
        """Архетип с большим числом участников должен быть первым."""
        burn = svc.get_or_create_archetype_by_name("Burn")
        elves = svc.get_or_create_archetype_by_name("Elves")

        t1 = svc.create_tournament(TournamentCreate(title="T1", chat_id=CHAT_ID + 1))
        t2 = svc.create_tournament(TournamentCreate(title="T2", chat_id=CHAT_ID + 2))
        t3 = svc.create_tournament(TournamentCreate(title="T3", chat_id=CHAT_ID + 3))

        # Elves сыгран 3 раза, Burn — 1 раз
        for tg in [101, 102, 103]:
            u = user_svc.get_or_create(tg_id=tg, username=None, first_name=f"P{tg}")
            svc.register_participant(
                tournament_id=[t1, t2, t3][[101, 102, 103].index(tg)].id,
                user_id=u.id,
                archetype_id=elves.id,
            )
        u_burn = user_svc.get_or_create(tg_id=200, username=None, first_name="BurnP")
        svc.register_participant(tournament_id=t1.id, user_id=u_burn.id, archetype_id=burn.id)

        result = svc.list_top_archetypes()
        assert result[0].name == "Elves"
        assert result[1].name == "Burn"

    def test_tie_resolved_alphabetically(self, svc, user_svc):
        """При одинаковом числе использований — сортировка по алфавиту."""
        burn = svc.get_or_create_archetype_by_name("Burn")
        affinity = svc.get_or_create_archetype_by_name("Affinity")

        t1 = svc.create_tournament(TournamentCreate(title="T1", chat_id=CHAT_ID + 10))
        u1 = user_svc.get_or_create(tg_id=301, username=None, first_name="P1")
        u2 = user_svc.get_or_create(tg_id=302, username=None, first_name="P2")
        svc.register_participant(tournament_id=t1.id, user_id=u1.id, archetype_id=burn.id)
        svc.register_participant(tournament_id=t1.id, user_id=u2.id, archetype_id=affinity.id)

        result = svc.list_top_archetypes()
        assert result[0].name == "Affinity"   # 'A' < 'B'
        assert result[1].name == "Burn"

    def test_never_used_archetype_is_included_after_used_ones(self, svc, user_svc):
        """Архетипы без использования тоже попадают в топ (после использованных)."""
        burn = svc.get_or_create_archetype_by_name("Burn")
        unused = svc.get_or_create_archetype_by_name("Zzz Unused")

        t1 = svc.create_tournament(TournamentCreate(title="T1", chat_id=CHAT_ID + 20))
        u = user_svc.get_or_create(tg_id=401, username=None, first_name="P")
        svc.register_participant(tournament_id=t1.id, user_id=u.id, archetype_id=burn.id)

        result = svc.list_top_archetypes()
        names = [a.name for a in result]
        assert "Burn" in names
        assert "Zzz Unused" in names
        assert names.index("Burn") < names.index("Zzz Unused")

    def test_respects_n_limit(self, svc):
        for i in range(15):
            svc.get_or_create_archetype_by_name(f"Arch{i:02d}")
        result = svc.list_top_archetypes(n=5)
        assert len(result) == 5

    def test_returns_archetype_item_instances(self, svc):
        svc.get_or_create_archetype_by_name("Burn")
        result = svc.list_top_archetypes()
        assert all(isinstance(a, ArchetypeItem) for a in result)

    def test_custom_archetype_excluded_from_top(self, svc, user_svc):
        """Кастомный архетип (is_custom=True) не появляется в глобальном топе."""
        public = svc.get_or_create_archetype_by_name("Public Deck", is_custom=False)
        custom = svc.get_or_create_archetype_by_name("My Weird Deck", is_custom=True)

        top = svc.list_top_archetypes()
        names = [a.name for a in top]
        assert "Public Deck" in names
        assert "My Weird Deck" not in names

    def test_custom_archetype_stays_in_user_history(self, svc, user_svc):
        """Кастомный архетип остаётся в истории пользователя, который его использовал."""
        custom = svc.get_or_create_archetype_by_name("My Weird Deck", is_custom=True)
        u = user_svc.get_or_create(tg_id=PLAYER_TG_ID, username=None, first_name="Player")
        t = svc.create_tournament(TournamentCreate(title="T", chat_id=CHAT_ID + 5))
        svc.register_participant(tournament_id=t.id, user_id=u.id, archetype_id=custom.id)

        history = svc.list_user_recent_archetypes(PLAYER_TG_ID)
        assert any(a.name == "My Weird Deck" for a in history)


# ---------------------------------------------------------------------------
# 2. list_user_recent_archetypes
# ---------------------------------------------------------------------------

class TestListUserRecentArchetypes:
    def test_unknown_user_returns_empty(self, svc):
        assert svc.list_user_recent_archetypes(tg_id=99999) == []

    def test_user_with_no_participation_returns_empty(self, svc, user_svc):
        user_svc.get_or_create(tg_id=PLAYER_TG_ID, username=None, first_name="Player")
        assert svc.list_user_recent_archetypes(PLAYER_TG_ID) == []

    def test_returns_recent_archetype_first(self, svc, user_svc):
        burn = svc.get_or_create_archetype_by_name("Burn")
        t = svc.create_tournament(TournamentCreate(title="T", chat_id=CHAT_ID + 30))
        u = user_svc.get_or_create(tg_id=PLAYER_TG_ID, username=None, first_name="Player")
        svc.register_participant(tournament_id=t.id, user_id=u.id, archetype_id=burn.id)

        result = svc.list_user_recent_archetypes(PLAYER_TG_ID)
        assert len(result) == 1
        assert result[0].name == "Burn"

    def test_most_recent_comes_first(self, svc, user_svc, db):
        """Из нескольких колод — самая последняя первая."""
        import core.models as m
        from datetime import timedelta
        from core.models import utc_now

        burn = svc.get_or_create_archetype_by_name("Burn")
        elves = svc.get_or_create_archetype_by_name("Elves")
        u = user_svc.get_or_create(tg_id=PLAYER_TG_ID, username=None, first_name="Player")

        t1 = svc.create_tournament(TournamentCreate(title="T1", chat_id=CHAT_ID + 31))
        t2 = svc.create_tournament(TournamentCreate(title="T2", chat_id=CHAT_ID + 32))
        svc.register_participant(tournament_id=t1.id, user_id=u.id, archetype_id=burn.id)

        # Вручную добавляем участника в t2 с более поздней датой
        p2 = m.Participant(
            tournament_id=t2.id, user_id=u.id, archetype_id=elves.id,
            added_by_admin=False, confirmed=False, upvotes_count=0, downvotes_count=0,
            created_at=utc_now() + timedelta(seconds=5),
            updated_at=utc_now(),
        )
        db.add(p2)
        db.commit()

        result = svc.list_user_recent_archetypes(PLAYER_TG_ID)
        assert result[0].name == "Elves"
        assert result[1].name == "Burn"

    def test_deduplicates_same_archetype(self, svc, user_svc):
        burn = svc.get_or_create_archetype_by_name("Burn")
        u = user_svc.get_or_create(tg_id=PLAYER_TG_ID, username=None, first_name="Player")

        t1 = svc.create_tournament(TournamentCreate(title="T1", chat_id=CHAT_ID + 40))
        t2 = svc.create_tournament(TournamentCreate(title="T2", chat_id=CHAT_ID + 41))
        svc.register_participant(tournament_id=t1.id, user_id=u.id, archetype_id=burn.id)
        svc.register_participant(tournament_id=t2.id, user_id=u.id, archetype_id=burn.id)

        result = svc.list_user_recent_archetypes(PLAYER_TG_ID)
        assert [a.name for a in result].count("Burn") == 1

    def test_returns_archetype_item_instances(self, svc, user_svc):
        burn = svc.get_or_create_archetype_by_name("Burn")
        u = user_svc.get_or_create(tg_id=PLAYER_TG_ID, username=None, first_name="Player")
        t = svc.create_tournament(TournamentCreate(title="T", chat_id=CHAT_ID + 42))
        svc.register_participant(tournament_id=t.id, user_id=u.id, archetype_id=burn.id)

        result = svc.list_user_recent_archetypes(PLAYER_TG_ID)
        assert all(isinstance(a, ArchetypeItem) for a in result)


# ---------------------------------------------------------------------------
# 3. build_archetype_list (чистая функция)
# ---------------------------------------------------------------------------

def _a(id: int, name: str) -> ArchetypeItem:
    return ArchetypeItem(id=id, name=name)


class TestBuildArchetypeList:
    # --- нет истории ---

    def test_no_history_returns_top_no_more(self):
        top = [_a(1, "Burn"), _a(2, "Elves")]
        result, has_more = build_archetype_list(recent=[], top=top)
        assert [a.name for a in result] == ["Burn", "Elves"]
        assert has_more is False

    def test_no_history_empty_top_returns_empty(self):
        result, has_more = build_archetype_list(recent=[], top=[])
        assert result == []
        assert has_more is False

    # --- есть история, не развёрнуто ---

    def test_history_collapsed_shows_first_n_with_more(self):
        recent = [_a(i, f"D{i}") for i in range(1, 6)]  # 5 колод
        result, has_more = build_archetype_list(recent=recent, top=[], expanded=False)
        assert len(result) == ARCHETYPE_COLLAPSED_COUNT
        assert [a.name for a in result] == ["D1", "D2", "D3"]
        assert has_more is True

    def test_history_collapsed_single_item_still_has_more(self):
        """Даже одна колода в истории — кнопка «ещё» есть (для показа топа)."""
        recent = [_a(1, "Burn")]
        _, has_more = build_archetype_list(recent=recent, top=[_a(2, "Elves")], expanded=False)
        assert has_more is True

    def test_history_collapsed_preserves_order(self):
        recent = [_a(3, "Zzz"), _a(1, "Aaa"), _a(2, "Mmm")]
        result, _ = build_archetype_list(recent=recent, top=[], expanded=False)
        assert [a.name for a in result] == ["Zzz", "Aaa", "Mmm"]

    # --- есть история, развёрнуто ---

    def test_history_expanded_shows_all_recent_plus_top(self):
        recent = [_a(1, "Burn"), _a(2, "Elves")]
        top = [_a(3, "Goblins"), _a(4, "Faeries")]
        result, has_more = build_archetype_list(recent=recent, top=top, expanded=True)
        names = [a.name for a in result]
        assert names == ["Burn", "Elves", "Goblins", "Faeries"]
        assert has_more is False

    def test_history_expanded_deduplicates_top(self):
        """Если колода из истории есть в топе — убираем её из топа."""
        recent = [_a(1, "Burn"), _a(2, "Elves")]
        top = [_a(1, "Burn"), _a(3, "Goblins")]  # Burn — дубль
        result, _ = build_archetype_list(recent=recent, top=top, expanded=True)
        names = [a.name for a in result]
        assert names == ["Burn", "Elves", "Goblins"]
        assert names.count("Burn") == 1

    def test_history_expanded_all_top_duplicated(self):
        """Если весь топ уже в истории — после истории пустой довесок."""
        recent = [_a(1, "Burn"), _a(2, "Elves")]
        top = [_a(1, "Burn"), _a(2, "Elves")]
        result, has_more = build_archetype_list(recent=recent, top=top, expanded=True)
        assert [a.name for a in result] == ["Burn", "Elves"]
        assert has_more is False

    def test_history_expanded_empty_top(self):
        recent = [_a(1, "Burn")]
        result, has_more = build_archetype_list(recent=recent, top=[], expanded=True)
        assert [a.name for a in result] == ["Burn"]
        assert has_more is False

    def test_returns_copies_not_same_list(self):
        """Возвращает новый список, не изменяет входной."""
        recent = [_a(1, "Burn")]
        top = [_a(2, "Elves")]
        result, _ = build_archetype_list(recent=recent, top=top)
        result.append(_a(99, "Extra"))
        assert len(recent) == 1
        assert len(top) == 1


# ---------------------------------------------------------------------------
# 4. PlayerHandler.handle_register (интеграция)
# ---------------------------------------------------------------------------

class TestHandleRegisterArchetypeMenu:
    def test_new_player_no_history_sees_top(self, svc, user_svc, player_handler, active_tournament):
        """Новый игрок (нет истории) видит топ-архетипы."""
        popular = svc.get_or_create_archetype_by_name("Popular")
        t_other = svc.create_tournament(TournamentCreate(title="Other", chat_id=CHAT_ID + 50))
        for tg in [501, 502, 503]:
            u = user_svc.get_or_create(tg_id=tg, username=None, first_name=f"P{tg}")
            svc.register_participant(tournament_id=t_other.id, user_id=u.id, archetype_id=popular.id)

        # Наш новый игрок — имя уже есть, история — нет
        user_svc.get_or_create(tg_id=PLAYER_TG_ID, username=None, first_name="NewPlayer")
        result = player_handler.handle_register(active_tournament.id, tg_id=PLAYER_TG_ID)

        btn_names = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert "Popular" in btn_names

    def test_new_player_no_more_button(self, svc, user_svc, player_handler, active_tournament):
        """Без истории кнопки «... ещё» нет."""
        svc.get_or_create_archetype_by_name("Burn")
        user_svc.get_or_create(tg_id=PLAYER_TG_ID, username=None, first_name="NewPlayer")
        result = player_handler.handle_register(active_tournament.id, tg_id=PLAYER_TG_ID)

        from bot.keyboards import CB_ARCHETYPE_MORE
        btn_callbacks = [
            b.callback_data
            for row in result.keyboard.inline_keyboard for b in row
        ]
        assert not any(cb.startswith(CB_ARCHETYPE_MORE) for cb in btn_callbacks)

    def test_player_with_history_shows_collapsed(self, svc, user_svc, player_handler, active_tournament):
        """Игрок с историей видит ARCHETYPE_COLLAPSED_COUNT колод + «... ещё»."""
        archs = [svc.get_or_create_archetype_by_name(f"Deck{i}") for i in range(1, 6)]
        u = user_svc.get_or_create(tg_id=PLAYER_TG_ID, username=None, first_name="Player")
        for i, arch in enumerate(archs):
            t = svc.create_tournament(TournamentCreate(title=f"T{i}", chat_id=CHAT_ID + 51 + i))
            svc.register_participant(tournament_id=t.id, user_id=u.id, archetype_id=arch.id)

        result = player_handler.handle_register(active_tournament.id, tg_id=PLAYER_TG_ID)

        from bot.keyboards import CB_ARCHETYPE, CB_ARCHETYPE_MORE
        arch_btns = [
            b for row in result.keyboard.inline_keyboard for b in row
            if b.callback_data.startswith(CB_ARCHETYPE + ":")
        ]
        more_btns = [
            b for row in result.keyboard.inline_keyboard for b in row
            if b.callback_data.startswith(CB_ARCHETYPE_MORE)
        ]
        assert len(arch_btns) == ARCHETYPE_COLLAPSED_COUNT
        assert len(more_btns) == 1

    def test_player_with_history_always_has_custom_button(self, svc, user_svc, player_handler, active_tournament):
        burn = svc.get_or_create_archetype_by_name("Burn")
        u = user_svc.get_or_create(tg_id=PLAYER_TG_ID, username=None, first_name="Player")
        t = svc.create_tournament(TournamentCreate(title="T", chat_id=CHAT_ID + 60))
        svc.register_participant(tournament_id=t.id, user_id=u.id, archetype_id=burn.id)

        result = player_handler.handle_register(active_tournament.id, tg_id=PLAYER_TG_ID)

        from bot.keyboards import CB_CUSTOM_ARCHETYPE
        btns = [b for row in result.keyboard.inline_keyboard for b in row]
        assert any(b.callback_data.startswith(CB_CUSTOM_ARCHETYPE) for b in btns)


# ---------------------------------------------------------------------------
# 5. PlayerHandler.handle_archetype_more (интеграция)
# ---------------------------------------------------------------------------

class TestHandleArchetypeMore:
    @pytest.fixture
    def player_with_history(self, svc, user_svc, active_tournament):
        archs = [svc.get_or_create_archetype_by_name(f"Deck{i}") for i in range(1, 6)]
        u = user_svc.get_or_create(tg_id=PLAYER_TG_ID, username=None, first_name="Player")
        for i, arch in enumerate(archs):
            t = svc.create_tournament(TournamentCreate(title=f"HT{i}", chat_id=CHAT_ID + 70 + i))
            svc.register_participant(tournament_id=t.id, user_id=u.id, archetype_id=arch.id)
        return u

    def test_expanded_shows_more_archetypes_than_collapsed(
        self, player_handler, active_tournament, player_with_history
    ):
        collapsed = player_handler.handle_register(active_tournament.id, tg_id=PLAYER_TG_ID)
        expanded = player_handler.handle_archetype_more(active_tournament.id, tg_id=PLAYER_TG_ID)

        from bot.keyboards import CB_ARCHETYPE
        def arch_btn_count(result):
            return sum(
                1 for row in result.keyboard.inline_keyboard for b in row
                if b.callback_data.startswith(CB_ARCHETYPE + ":")
            )

        assert arch_btn_count(expanded) > arch_btn_count(collapsed)

    def test_expanded_has_no_more_button(self, player_handler, active_tournament, player_with_history):
        result = player_handler.handle_archetype_more(active_tournament.id, tg_id=PLAYER_TG_ID)

        from bot.keyboards import CB_ARCHETYPE_MORE
        btns = [b for row in result.keyboard.inline_keyboard for b in row]
        assert not any(b.callback_data.startswith(CB_ARCHETYPE_MORE) for b in btns)

    def test_expanded_deduplicates_history_and_top(self, svc, user_svc, player_handler, active_tournament):
        """Колоды из истории не дублируются в топ-части развёрнутого списка."""
        burn = svc.get_or_create_archetype_by_name("Burn")

        # Игрок играл Burn
        u = user_svc.get_or_create(tg_id=PLAYER_TG_ID, username=None, first_name="Player")
        t = svc.create_tournament(TournamentCreate(title="TT", chat_id=CHAT_ID + 80))
        svc.register_participant(tournament_id=t.id, user_id=u.id, archetype_id=burn.id)

        result = player_handler.handle_archetype_more(active_tournament.id, tg_id=PLAYER_TG_ID)

        btns = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert btns.count("Burn") == 1


# ---------------------------------------------------------------------------
# 6. AdminHandler.handle_admin_pick_arch (интеграция)
# ---------------------------------------------------------------------------

class TestAdminPickArchMenu:
    @pytest.fixture
    def bulk_participant(self, svc, user_svc, active_tournament):
        """Участник без истории, добавленный через bulk_add."""
        player = user_svc.get_or_create_by_name("Bulk", "Guy")[0]
        svc.bulk_add_participants(active_tournament.id, [(player.id, "Bulk Guy")])
        return svc.get_participant(active_tournament.id, player.id)

    def test_player_no_history_sees_top(
        self, admin_handler, svc, user_svc, admin_user, active_tournament, bulk_participant
    ):
        popular = svc.get_or_create_archetype_by_name("Popular")
        t_other = svc.create_tournament(TournamentCreate(title="TO", chat_id=CHAT_ID + 90))
        for tg in [901, 902]:
            u = user_svc.get_or_create(tg_id=tg, username=None, first_name=f"P{tg}")
            svc.register_participant(tournament_id=t_other.id, user_id=u.id, archetype_id=popular.id)

        result = admin_handler.handle_admin_pick_arch(ADMIN_TG_ID, bulk_participant.id)
        btn_names = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert "Popular" in btn_names

    def test_player_no_history_no_more_button(
        self, admin_handler, svc, admin_user, active_tournament, bulk_participant
    ):
        svc.get_or_create_archetype_by_name("Burn")
        result = admin_handler.handle_admin_pick_arch(ADMIN_TG_ID, bulk_participant.id)

        from bot.keyboards import CB_ADMIN_ARCH_MORE
        btns = [b for row in result.keyboard.inline_keyboard for b in row]
        assert not any(b.callback_data.startswith(CB_ADMIN_ARCH_MORE) for b in btns)

    def test_player_with_history_shows_collapsed_and_more(
        self, admin_handler, svc, user_svc, admin_user, active_tournament
    ):
        """Участник с историей: ARCHETYPE_COLLAPSED_COUNT кнопок + «... ещё»."""
        archs = [svc.get_or_create_archetype_by_name(f"Deck{i}") for i in range(1, 6)]
        p_user = user_svc.get_or_create(tg_id=2222, username=None, first_name="Player")
        for i, arch in enumerate(archs):
            t = svc.create_tournament(TournamentCreate(title=f"PH{i}", chat_id=CHAT_ID + 91 + i))
            svc.register_participant(tournament_id=t.id, user_id=p_user.id, archetype_id=arch.id)
        svc.bulk_add_participants(active_tournament.id, [(p_user.id, "Player")])
        participant = svc.get_participant(active_tournament.id, p_user.id)

        result = admin_handler.handle_admin_pick_arch(ADMIN_TG_ID, participant.id)

        from bot.keyboards import CB_ADMIN_SET_ARCH, CB_ADMIN_ARCH_MORE
        arch_btns = [
            b for row in result.keyboard.inline_keyboard for b in row
            if b.callback_data.startswith(CB_ADMIN_SET_ARCH)
        ]
        more_btns = [
            b for row in result.keyboard.inline_keyboard for b in row
            if b.callback_data.startswith(CB_ADMIN_ARCH_MORE)
        ]
        assert len(arch_btns) == ARCHETYPE_COLLAPSED_COUNT
        assert len(more_btns) == 1


# ---------------------------------------------------------------------------
# 7. AdminHandler.handle_admin_arch_more (интеграция)
# ---------------------------------------------------------------------------

class TestAdminArchMore:
    @pytest.fixture
    def participant_with_history(self, svc, user_svc, active_tournament):
        archs = [svc.get_or_create_archetype_by_name(f"Deck{i}") for i in range(1, 6)]
        p_user = user_svc.get_or_create(tg_id=3333, username=None, first_name="Player")
        for i, arch in enumerate(archs):
            t = svc.create_tournament(TournamentCreate(title=f"AM{i}", chat_id=CHAT_ID + 101 + i))
            svc.register_participant(tournament_id=t.id, user_id=p_user.id, archetype_id=arch.id)
        svc.bulk_add_participants(active_tournament.id, [(p_user.id, "Player")])
        return svc.get_participant(active_tournament.id, p_user.id)

    def test_expanded_shows_more_archetypes_than_collapsed(
        self, admin_handler, admin_user, active_tournament, participant_with_history
    ):
        from bot.keyboards import CB_ADMIN_SET_ARCH
        def arch_btn_count(result):
            return sum(
                1 for row in result.keyboard.inline_keyboard for b in row
                if b.callback_data.startswith(CB_ADMIN_SET_ARCH)
            )

        collapsed = admin_handler.handle_admin_pick_arch(ADMIN_TG_ID, participant_with_history.id)
        expanded = admin_handler.handle_admin_arch_more(ADMIN_TG_ID, participant_with_history.id)
        assert arch_btn_count(expanded) > arch_btn_count(collapsed)

    def test_expanded_no_more_button(
        self, admin_handler, admin_user, active_tournament, participant_with_history
    ):
        from bot.keyboards import CB_ADMIN_ARCH_MORE
        result = admin_handler.handle_admin_arch_more(ADMIN_TG_ID, participant_with_history.id)
        btns = [b for row in result.keyboard.inline_keyboard for b in row]
        assert not any(b.callback_data.startswith(CB_ADMIN_ARCH_MORE) for b in btns)

    def test_non_admin_returns_not_admin(self, admin_handler, active_tournament, participant_with_history):
        from bot.messages import NOT_ADMIN
        result = admin_handler.handle_admin_arch_more(tg_id=42, participant_id=participant_with_history.id)
        assert result.text == NOT_ADMIN
