"""Regression coverage for HobbyGames39 tournament 101147 (15 August 2026)."""

from datetime import date
from unittest.mock import MagicMock

from sqlalchemy import select

from bot.handlers.aetherhub import AetherhubHandler
from core import models
from core.schemas import TournamentCreate
from services.aetherhub_import_service import AetherhubImportService, expected_swiss_rounds
from services.aetherhub_service import AetherhubService

PROFILE_URL = "https://aetherhub.com/User/HobbyGames39/"
TOURNAMENT_URL = "https://aetherhub.com/Tourney/RoundTourney/101147"
EVENT_DATE = date(2026, 8, 15)

PLAYERS = ["Иван Ф.", "Илья т", "Даня Кабан", "Евгений", "Виолетта Т", "Холоденко Данила", "Бадыжь", "Кузин Алексей"]
STANDINGS = ["Илья т", "Евгений", "Бадыжь", "Кузин Алексей", "Холоденко Данила", "Даня Кабан", "Виолетта Т", "Иван Ф."]
STANDING_POINTS = [9, 6, 6, 6, 3, 3, 3, 0]
ROUNDS = {
    1: [
        (1, "Иван Ф.", "Илья т", 0, 2),
        (2, "Даня Кабан", "Евгений", 1, 2),
        (3, "Виолетта Т", "Холоденко Данила", 1, 2),
        (4, "Бадыжь", "Кузин Алексей", 2, 0),
    ],
    2: [
        (1, "Евгений", "Бадыжь", 2, 1),
        (2, "Холоденко Данила", "Илья т", 0, 2),
        (3, "Кузин Алексей", "Даня Кабан", 2, 1),
        (4, "Виолетта Т", "Иван Ф.", 2, 1),
    ],
    3: [
        (1, "Илья т", "Евгений", 2, 1),
        (2, "Бадыжь", "Холоденко Данила", 2, 0),
        (3, "Виолетта Т", "Кузин Алексей", 1, 2),
        (4, "Даня Кабан", "Иван Ф.", 2, 1),
    ],
}


def _profile_html(*, pauper_age: str = "2 days ago") -> str:
    return f"""
    <div class="w-100 pl-2">
      <h5><a href="/Tourney/RoundTourney/101167"><b>Модерн</b></a></h5>
      Constructed Tourney <br><small class="text-muted">a day ago</small>
    </div>
    <div class="w-100 pl-2">
      <h5><a href="/Tourney/RoundTourney/101147"><b>Паупер, чуваки</b></a></h5>
      Constructed Tourney <br><small class="text-muted">{pauper_age}</small>
    </div>
    <div class="w-100 pl-2">
      <h5><a href="/Tourney/RoundTourney/101097"><b>Дуэльный паупер командир</b></a></h5>
      Constructed Tourney <br><small class="text-muted">4 days ago</small>
    </div>
    """


def _main_html() -> str:
    standings_rows = "".join(
        f"<tr><td>{place}</td><td>{name}</td><td>{points}</td></tr>"
        for place, (name, points) in enumerate(zip(STANDINGS, STANDING_POINTS, strict=True), start=1)
    )
    round_links = "".join(
        f'<a href="/Tourney/RoundTourney/101147?p={round_number}">{round_number}</a>' for round_number in ROUNDS
    )
    return f"""
    <div id="tab_pairings"></div>
    {round_links}
    <div id="tab_results">
      <table><thead><tr><th>Rank</th><th>Name</th><th>Points</th></tr></thead>
      <tbody>{standings_rows}</tbody></table>
    </div>
    """


def _round_html(round_number: int) -> str:
    rows = "".join(
        f"""
        <tr><td>{table}</td><td>{player} (0 Points)</td><td>{opponent} (0 Points)</td>
        <td>{player_wins} - {opponent_wins}</td></tr>
        """
        for table, player, opponent, player_wins, opponent_wins in ROUNDS[round_number]
    )
    return f"""
    <table id="matchList"><thead><tr><th>Table</th><th>Player 1</th><th>Player 2</th>
    <th>Match Results</th></tr></thead><tbody>{rows}</tbody></table>
    """


def _service(*, profile_age: str = "2 days ago") -> AetherhubService:
    html_by_url = {
        PROFILE_URL: _profile_html(pauper_age=profile_age),
        TOURNAMENT_URL: _main_html(),
        **{f"{TOURNAMENT_URL}?p={round_number}": _round_html(round_number) for round_number in ROUNDS},
    }
    scraper = MagicMock()

    def get(url, **_kwargs):
        response = MagicMock()
        response.text = html_by_url[url]
        return response

    scraper.get.side_effect = get
    return AetherhubService(scraper=scraper)


def test_profile_finds_real_cyrillic_pauper_title():
    service = _service()

    links = service.fetch_club_tournaments(PROFILE_URL, today=date(2026, 8, 17))
    tournament = next(link for link in links if link.url == TOURNAMENT_URL)

    assert tournament.name == "Паупер, чуваки"
    assert tournament.date == EVENT_DATE
    assert tournament.is_pauper is True
    event_day_service = _service(profile_age="2 hours ago")
    assert event_day_service.find_todays_pauper_tournament(PROFILE_URL, today=EVENT_DATE) == TOURNAMENT_URL


def test_real_tournament_parses_eight_players_three_rounds_and_scores():
    data = _service().fetch_tournament(TOURNAMENT_URL)

    assert data.players == PLAYERS
    assert data.standings == STANDINGS
    assert [round_data.number for round_data in data.rounds] == [1, 2, 3]
    assert [len(round_data.pairings) for round_data in data.rounds] == [8, 8, 8]
    assert all(
        pairing.player_wins is not None and pairing.opponent_wins is not None
        for round_data in data.rounds
        for pairing in round_data.pairings
    )


def test_real_three_round_tournament_import_is_complete(db, svc):
    tournament = svc.create_tournament(
        TournamentCreate(title="🎲 Hobby Games Pauper 15.08.2026", chat_id=-1002787710855, club="Hobby Games")
    )
    data = _service().fetch_tournament(TOURNAMENT_URL)
    import_service = AetherhubImportService(db)

    result = AetherhubHandler(_service(), import_service, svc).handle_confirm_import(
        tournament.id, TOURNAMENT_URL, data
    )

    assert "Участники: получено 8" in result.text
    assert "Раунды: 3" in result.text
    assert "Парингов получено: 24" in result.text
    assert "Стендинги: финальные (8 мест, 3 из 3 раундов)" in result.text
    assert "Счёт матчей: опубликован полностью" in result.text
    assert expected_swiss_rounds(8) == 3
    assert import_service.is_tournament_complete(tournament.id) is True
    assert import_service.get_round_numbers(tournament.id) == [1, 2, 3]
    places = (
        db.execute(
            select(models.Participant.final_place)
            .where(models.Participant.tournament_id == tournament.id)
            .order_by(models.Participant.final_place)
        )
        .scalars()
        .all()
    )
    assert places == list(range(1, 9))
