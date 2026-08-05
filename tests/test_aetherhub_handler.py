"""Tests for AetherhubHandler business logic."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from bot.handlers.aetherhub import AetherhubFetchResult, AetherhubHandler
from services.aetherhub_import_service import expected_swiss_rounds
from services.aetherhub_models import AetherhubTournamentData, ClubTournamentLink


def _make_tournament_data(url: str = "https://aetherhub.com/Tourney/RoundTourney/1") -> AetherhubTournamentData:
    return AetherhubTournamentData(url=url, players=["Alice", "Bob"], rounds=[])


def _handler(find_url: str | None = None, fetch_data: AetherhubTournamentData | None = None) -> AetherhubHandler:
    svc = MagicMock()
    svc.find_todays_pauper_tournament.return_value = find_url
    svc.fetch_tournament.return_value = fetch_data or _make_tournament_data()
    return AetherhubHandler(svc)


class TestHandleImportPrompt:
    def test_uses_stored_url_without_club_lookup(self):
        stored = "https://aetherhub.com/Tourney/RoundTourney/42"
        h = _handler(find_url="https://other.url")
        result = h.handle_import_prompt(stored_url=stored, club_aetherhub_url="https://club.url")
        h._aetherhub.find_todays_pauper_tournament.assert_not_called()
        h._aetherhub.fetch_tournament.assert_called_once_with(stored)
        assert result is not None

    def test_stored_url_header_is_update(self):
        stored = "https://aetherhub.com/Tourney/RoundTourney/42"
        h = _handler()
        result = h.handle_import_prompt(stored_url=stored, club_aetherhub_url=None)
        assert "Обновление" in result.preview_text

    def test_auto_finds_url_when_no_stored(self):
        found = "https://aetherhub.com/Tourney/RoundTourney/99"
        h = _handler(find_url=found)
        result = h.handle_import_prompt(stored_url=None, club_aetherhub_url="https://club.url")
        h._aetherhub.find_todays_pauper_tournament.assert_called_once_with("https://club.url")
        h._aetherhub.fetch_tournament.assert_called_once_with(found)
        assert result is not None

    def test_auto_find_header_is_import(self):
        h = _handler(find_url="https://aetherhub.com/Tourney/RoundTourney/99")
        result = h.handle_import_prompt(stored_url=None, club_aetherhub_url="https://club.url")
        assert "Импорт" in result.preview_text

    def test_returns_none_when_no_stored_and_not_found(self):
        h = _handler(find_url=None)
        result = h.handle_import_prompt(stored_url=None, club_aetherhub_url="https://club.url")
        assert result is None
        h._aetherhub.fetch_tournament.assert_not_called()

    def test_returns_none_when_no_stored_and_no_club_url(self):
        h = _handler()
        result = h.handle_import_prompt(stored_url=None, club_aetherhub_url=None)
        assert result is None
        h._aetherhub.find_todays_pauper_tournament.assert_not_called()
        h._aetherhub.fetch_tournament.assert_not_called()

    def test_result_url_matches_fetched_tournament(self):
        url = "https://aetherhub.com/Tourney/RoundTourney/55"
        h = _handler(fetch_data=_make_tournament_data(url=url))
        result = h.handle_import_prompt(stored_url=url, club_aetherhub_url=None)
        assert result.data.url == url

    def test_auto_find_empty_tournament_returns_none(self):
        """Автопоиск нашёл пустой турнир (0 игроков) → None, чтобы показать список клуба."""
        empty = AetherhubTournamentData(url="https://aetherhub.com/Tourney/RoundTourney/9", players=[], rounds=[])
        h = _handler(find_url="https://aetherhub.com/Tourney/RoundTourney/9", fetch_data=empty)
        assert h.handle_import_prompt(stored_url=None, club_aetherhub_url="https://club.url") is None

    def test_stored_url_empty_tournament_still_shows_preview(self):
        """Явно привязанный url показываем даже пустым (это осознанный ре-импорт)."""
        empty = AetherhubTournamentData(url="https://aetherhub.com/Tourney/RoundTourney/9", players=[], rounds=[])
        h = _handler(fetch_data=empty)
        result = h.handle_import_prompt(stored_url=empty.url, club_aetherhub_url=None)
        assert result is not None


class TestDescribeClubTournaments:
    def _handler_with_links(self, links) -> AetherhubHandler:
        svc = MagicMock()
        svc.fetch_club_tournaments.return_value = links
        return AetherhubHandler(svc)

    def test_lists_club_tournament_names(self):
        links = [
            ClubTournamentLink(name="17.07", url="u1", date=date(2026, 7, 17), is_pauper=True),
            ClubTournamentLink(name="Легаси 15.07.2026", url="u2", date=date(2026, 7, 15), is_pauper=False),
        ]
        text = self._handler_with_links(links).describe_club_tournaments("https://club.url")
        assert "найти не удалось" in text
        assert "17.07" in text  # имя + дата турнира
        assert "Легаси 15.07.2026" in text
        assert "15.07" in text  # дата второго турнира

    def test_no_links_message(self):
        text = self._handler_with_links([]).describe_club_tournaments("https://club.url")
        assert "турниров не видно" in text

    def test_fetch_error_returns_header(self):
        svc = MagicMock()
        svc.fetch_club_tournaments.side_effect = RuntimeError("boom")
        text = AetherhubHandler(svc).describe_club_tournaments("https://club.url")
        assert "найти не удалось" in text


class TestPreviewMessage:
    def test_preview_contains_header_counts_and_first5(self):
        data = AetherhubTournamentData(
            url="https://aetherhub.com/Tourney/RoundTourney/99049",
            players=["P1", "P2", "P3", "P4", "P5", "P6"],
            rounds=[],
        )
        h = _handler(fetch_data=data)
        result = h.handle_fetch_preview(data.url, header="📥 Импорт AetherHub")
        assert isinstance(result, AetherhubFetchResult)
        assert "📥 Импорт AetherHub" in result.preview_text
        assert "Игроков: 6" in result.preview_text
        assert "Первые 5 игроков:" in result.preview_text
        assert "• P1" in result.preview_text
        assert "• P5" in result.preview_text
        assert "…ещё 1" in result.preview_text

    def test_preview_does_not_show_points_label(self):
        """Preview should not contain Aetherhub points labels in player names."""
        data = AetherhubTournamentData(
            url="https://aetherhub.com/Tourney/RoundTourney/99049",
            players=["Валентин Задорожний", "Иван Юров"],
            rounds=[],
        )
        h = _handler(fetch_data=data)
        result = h.handle_fetch_preview(data.url, header="📥 Импорт AetherHub")
        assert "Points" not in result.preview_text


class TestConfirmImportMessage:
    def test_reports_fetched_and_changed_data(self):
        import_service = MagicMock()
        import_service.import_tournament.return_value = MagicMock(
            players_received=11,
            registered=0,
            already_registered=11,
            rounds_received=4,
            pairings_received=44,
            pairings_changed=0,
            standings_received=11,
            scores_complete=True,
            created_names=[],
            new_round_numbers=[],
        )
        handler = AetherhubHandler(MagicMock(), import_service, MagicMock())
        text = handler.handle_confirm_import(1, "https://example.invalid/tournament", _make_tournament_data()).text
        assert "Участники: получено 11" in text
        assert "Парингов получено: 44" in text
        assert "Добавлено или изменено: 0" in text
        assert "Стендинги: финальные (11 мест, 4 из 4 раундов)" in text
        assert "Счёт матчей: опубликован полностью" in text

    def test_final_standings_do_not_depend_on_match_scores(self):
        import_service = MagicMock()
        import_service.import_tournament.return_value = MagicMock(
            players_received=11,
            registered=0,
            already_registered=11,
            rounds_received=4,
            pairings_received=41,
            pairings_changed=0,
            standings_received=11,
            scores_complete=False,
            created_names=[],
            new_round_numbers=[],
        )
        handler = AetherhubHandler(MagicMock(), import_service, MagicMock())
        text = handler.handle_confirm_import(1, "https://example.invalid/tournament", _make_tournament_data()).text
        assert "Стендинги: финальные (11 мест, 4 из 4 раундов)" in text
        assert "Счёт матчей: не опубликован AetherHub (стендинги уже финальные)" in text

    def test_standings_are_intermediate_before_expected_round(self):
        import_service = MagicMock()
        import_service.import_tournament.return_value = MagicMock(
            players_received=11,
            registered=0,
            already_registered=11,
            rounds_received=3,
            pairings_received=33,
            pairings_changed=0,
            standings_received=11,
            scores_complete=False,
            created_names=[],
            new_round_numbers=[],
        )
        handler = AetherhubHandler(MagicMock(), import_service, MagicMock())
        text = handler.handle_confirm_import(1, "https://example.invalid/tournament", _make_tournament_data()).text
        assert "Стендинги: промежуточные (11 мест, 3 из 4 раундов)" in text
        assert "Счёт матчей: опубликован не полностью" in text

    def test_reports_missing_standings_and_incomplete_scores(self):
        import_service = MagicMock()
        import_service.import_tournament.return_value = MagicMock(
            players_received=2,
            registered=0,
            already_registered=2,
            rounds_received=1,
            pairings_received=2,
            pairings_changed=0,
            standings_received=0,
            scores_complete=False,
            created_names=[],
            new_round_numbers=[],
        )
        handler = AetherhubHandler(MagicMock(), import_service, MagicMock())
        text = handler.handle_confirm_import(1, "https://example.invalid/tournament", _make_tournament_data()).text
        assert "Стендинги: ещё не опубликованы" in text
        assert "Счёт матчей: опубликован не полностью" in text


@pytest.mark.parametrize(
    ("players", "rounds"),
    [(8, 3), (9, 4), (11, 4), (16, 4), (17, 4), (64, 4)],
)
def test_expected_swiss_rounds(players, rounds):
    assert expected_swiss_rounds(players) == rounds
