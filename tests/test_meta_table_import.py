"""Tests for MetaTableImportService and parse_meta_table."""

import pytest

from bot.features import FeatureService
from bot.handlers.admin import AdminHandler
from bot.keyboards import Keyboards
from bot.messages import META_IMPORT_PROMPT, NOT_ADMIN
from core import models
from core.models import Participant, RoundPairing
from core.schemas import TournamentCreate
from services import errors
from services.archetype import ArchetypeService
from services.feature_flags import FeatureFlagService
from services.meta_table_import import MetaTableImportService, parse_meta_table
from services.tournament import TournamentService
from services.user import UserService

CHAT_ID = 500
IMPORTER_TG_ID = 9999


@pytest.fixture
def svc(db):
    return TournamentService(db)


@pytest.fixture
def user_svc(db):
    return UserService(db)


@pytest.fixture
def arch_svc(db):
    return ArchetypeService(db)


@pytest.fixture
def import_svc(db):
    return MetaTableImportService(db)


@pytest.fixture
def tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Meta Import Test", chat_id=CHAT_ID))


# ── parse_meta_table ──────────────────────────────────────────────────────────


class TestParseMetaTable:
    def test_players_section(self):
        text = "## Игроки\nИванов Иван | Burn\nПетров Пётр | Elves\n"
        players, pairings = parse_meta_table(text)
        assert len(players) == 2
        assert players[0] == ("Иванов Иван", "Burn")
        assert players[1] == ("Петров Пётр", "Elves")
        assert pairings == {}

    def test_unknown_deck_is_none(self):
        text = "## Игроки\nИванов Иван | ?\n"
        players, _ = parse_meta_table(text)
        assert players[0] == ("Иванов Иван", None)

    def test_pairings_section(self):
        text = "## Раунд 1\nИванов Иван 2-1 Петров Пётр\nСидоров Сидор 0-2 Кузнецов Константин\n"
        _, pairings = parse_meta_table(text)
        assert 1 in pairings
        assert ("Иванов Иван", "Петров Пётр") in pairings[1]
        assert ("Сидоров Сидор", "Кузнецов Константин") in pairings[1]

    def test_bye_pairing(self):
        text = "## Раунд 1\nИванов Иван BYE\n"
        _, pairings = parse_meta_table(text)
        assert ("Иванов Иван", "BYE") in pairings[1]

    def test_multiple_rounds(self):
        text = "## Раунд 1\nА А 2-0 Б Б\n## Раунд 2\nА А 1-2 В В\n"
        _, pairings = parse_meta_table(text)
        assert len(pairings) == 2
        assert 1 in pairings and 2 in pairings

    def test_comments_skipped(self):
        text = "## Игроки\n# Не распознано: 1\nИванов Иван | Burn\n"
        players, _ = parse_meta_table(text)
        assert len(players) == 1

    def test_full_table(self):
        text = (
            "## Игроки\n"
            "Юрьев Ярослав | Spy\n"
            "Ладария Даур | Caw Blades\n"
            "# Не распознано: 0\n"
            "## Раунд 1\n"
            "Юрьев Ярослав 0-2 Ладария Даур\n"
        )
        players, pairings = parse_meta_table(text)
        assert len(players) == 2
        assert len(pairings[1]) == 1

    def test_players_without_header(self):
        """Простая таблица «Имя | Колода» без заголовка «## Игроки» тоже парсится."""
        text = "Юрковский Илья | Mono U Terror\nГасанлы Фарид | UW Weenie\n"
        players, pairings = parse_meta_table(text)
        assert players == [("Юрковский Илья", "Mono U Terror"), ("Гасанлы Фарид", "UW Weenie")]
        assert pairings == {}

    def test_header_less_players_then_rounds(self):
        """Игроки без заголовка + раунды: строки с «|» — игроки, со счётом — пары."""
        text = "А А | Burn\nБ Б | Elves\n## Раунд 1\nА А 2-0 Б Б\n"
        players, pairings = parse_meta_table(text)
        assert len(players) == 2
        assert pairings[1] == [("А А", "Б Б")]


# ── MetaTableImportService.import_from_table ──────────────────────────────────


class TestMetaTableImportService:
    TABLE = "## Игроки\nИванов Иван | Burn\nПетров Пётр | Elves\n## Раунд 1\nИванов Иван 2-1 Петров Пётр\n"

    def test_registers_new_players(self, import_svc, svc, user_svc, tournament):
        result = import_svc.import_from_table(tournament.id, self.TABLE, IMPORTER_TG_ID)
        assert result.registered == 2

    def test_imports_header_less_table(self, import_svc, tournament, db):
        """Таблица без «## Игроки» регистрирует игроков с колодами (реальный кейс из чата)."""
        table = "Юрковский Илья | Mono U Terror\nГасанлы Фарид | UW Weenie\n"
        result = import_svc.import_from_table(tournament.id, table, IMPORTER_TG_ID)
        assert result.registered == 2
        decks = {
            p.archetype.name for p in db.query(Participant).filter_by(tournament_id=tournament.id).all() if p.archetype
        }
        assert decks == {"Mono U Terror", "UW Weenie"}

    def test_sets_deck_added_by(self, import_svc, svc, user_svc, tournament, db):
        import_svc.import_from_table(tournament.id, self.TABLE, IMPORTER_TG_ID)
        participants = db.query(Participant).filter_by(tournament_id=tournament.id).all()
        for p in participants:
            assert p.deck_added_by_tg_id == IMPORTER_TG_ID

    def test_saves_pairings(self, import_svc, tournament, db):
        import_svc.import_from_table(tournament.id, self.TABLE, IMPORTER_TG_ID)
        pairings = db.query(RoundPairing).filter_by(tournament_id=tournament.id, round_number=1).all()
        names = {p.player_name for p in pairings}
        assert "Иванов Иван" in names
        assert "Петров Пётр" in names

    def test_skips_existing_deck(self, import_svc, svc, user_svc, arch_svc, tournament):
        burn = arch_svc.get_or_create_by_name("Burn")
        user = user_svc.get_or_create(tg_id=8001, username=None, first_name="Иван", last_name="Иванов")
        svc.register_participant(tournament_id=tournament.id, user_id=user.id, archetype_id=burn.id)
        table = "## Игроки\nИванов Иван | Elves\n"
        result = import_svc.import_from_table(tournament.id, table, IMPORTER_TG_ID)
        assert result.deck_skipped == 1
        assert result.deck_updated == 0

    def test_updates_deck_when_missing(self, import_svc, svc, user_svc, tournament):
        user = user_svc.get_or_create(tg_id=8002, username=None, first_name="Пётр", last_name="Петров")
        svc.register_participant(tournament_id=tournament.id, user_id=user.id)
        table = "## Игроки\nПетров Пётр | Elves\n"
        result = import_svc.import_from_table(tournament.id, table, IMPORTER_TG_ID)
        assert result.deck_updated == 1
        assert result.registered == 0

    def test_unknown_deck_tracked(self, import_svc, tournament):
        table = "## Игроки\nСидоров Сидор | ?\n"
        result = import_svc.import_from_table(tournament.id, table, IMPORTER_TG_ID)
        assert "Сидоров Сидор" in result.unknown_decks

    def test_tournament_not_found_raises(self, import_svc):
        with pytest.raises(errors.TournamentNotFound):
            import_svc.import_from_table(99999, "## Игроки\nА А | Burn\n", IMPORTER_TG_ID)

    def test_idempotent_pairings(self, import_svc, tournament, db):
        import_svc.import_from_table(tournament.id, self.TABLE, IMPORTER_TG_ID)
        import_svc.import_from_table(tournament.id, self.TABLE, IMPORTER_TG_ID)
        count = db.query(RoundPairing).filter_by(tournament_id=tournament.id, round_number=1).count()
        assert count == 2  # один за каждого игрока в паре, без дублей

    def test_finds_existing_user_by_name(self, import_svc, svc, user_svc, tournament):
        user_svc.get_or_create(tg_id=8003, username="hero", first_name="Анна", last_name="Сидорова")
        table = "## Игроки\nСидорова Анна | Burn\n"
        result = import_svc.import_from_table(tournament.id, table, IMPORTER_TG_ID)
        # Player found by name → registered (not created as placeholder with new account)
        assert result.registered == 1
        user = user_svc.get_by_tg_id(8003)
        p = svc.get_participant(tournament.id, user.id)
        assert p is not None


# ── AdminHandler.handle_meta_import_start / handle_meta_import_table ──────────


def _make_admin_handler(db) -> AdminHandler:
    svc = TournamentService(db)
    user_svc = UserService(db)
    arch_svc = ArchetypeService(db)
    return AdminHandler(svc, user_svc, arch_svc, Keyboards(), FeatureService(FeatureFlagService(db)))


def _make_admin_user(db) -> None:
    UserService(db).get_or_create(tg_id=IMPORTER_TG_ID, username="adm", first_name="Admin")
    db.query(models.User).filter_by(tg_id=IMPORTER_TG_ID).update({"is_admin": True})
    db.commit()


class TestHandleMetaImport:
    def test_start_non_privileged_blocked(self, db, tournament):
        h = _make_admin_handler(db)
        nobody = UserService(db).get_or_create(tg_id=7777, username=None, first_name="Nobody")
        result = h.handle_meta_import_start(tg_id=nobody.tg_id, tournament_id=tournament.id)
        assert result.is_alert
        assert result.text == NOT_ADMIN

    def test_start_privileged_returns_prompt(self, db, tournament):
        _make_admin_user(db)
        h = _make_admin_handler(db)
        result = h.handle_meta_import_start(tg_id=IMPORTER_TG_ID, tournament_id=tournament.id)
        assert not result.is_alert
        assert META_IMPORT_PROMPT in result.text

    def test_table_import_returns_status(self, db, tournament):
        _make_admin_user(db)
        h = _make_admin_handler(db)
        table = "## Игроки\nИванов Иван | Burn\nПетров Пётр | Elves\n"
        result = h.handle_meta_import_table(tg_id=IMPORTER_TG_ID, tournament_id=tournament.id, text=table)
        assert not result.is_alert
        assert "Иванов" in result.text or "2" in result.text or "Добавлено" in result.text
