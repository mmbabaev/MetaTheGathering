from datetime import datetime, timedelta

import pytest

from bot.handlers.ranked import RankedPreseasonHandler
from bot.messages import NOT_ADMIN
from core import models
from core.schemas import TournamentCreate
from services.ranked import Glicko2Rating, RankedMatch, RankedPreseasonService, update_glicko2
from services.tournament import TournamentService
from services.user import UserService


def _closed_tournament(db, *, title: str, played_at: datetime, chat_id: int, url: str | None = None):
    created = TournamentService(db).create_tournament(TournamentCreate(title=title, chat_id=chat_id, club="Edinorog"))
    tournament = db.get(models.Tournament, created.id)
    tournament.started_at = played_at
    tournament.status = models.TournamentStatus.CLOSED
    tournament.aetherhub_url = url
    db.commit()
    return tournament


def _pair(db, tournament_id: int, round_number: int, player, opponent, score=(2, 0)):
    player_name = f"{player.last_name} {player.first_name}"
    opponent_name = f"{opponent.last_name} {opponent.first_name}"
    db.add_all(
        [
            models.RoundPairing(
                tournament_id=tournament_id,
                round_number=round_number,
                player_name=player_name,
                opponent_name=opponent_name,
                player_wins=score[0],
                opponent_wins=score[1],
            ),
            models.RoundPairing(
                tournament_id=tournament_id,
                round_number=round_number,
                player_name=opponent_name,
                opponent_name=player_name,
                player_wins=score[1],
                opponent_wins=score[0],
            ),
        ]
    )


def _participant(db, tournament_id: int, user):
    db.add(models.Participant(tournament_id=tournament_id, user_id=user.id))


def test_glicko2_matches_published_worked_example():
    result = update_glicko2(
        Glicko2Rating(rating=1500, deviation=200, volatility=0.06),
        [
            (Glicko2Rating(rating=1400, deviation=30), 1.0),
            (Glicko2Rating(rating=1550, deviation=100), 0.0),
            (Glicko2Rating(rating=1700, deviation=300), 0.0),
        ],
        tau=0.5,
    )

    assert result.rating == pytest.approx(1464.06, abs=0.01)
    assert result.deviation == pytest.approx(151.52, abs=0.01)
    assert result.volatility == pytest.approx(0.059996, abs=0.000001)


def test_preseason_deduplicates_reciprocal_rows_and_ranks_winner(db):
    users = UserService(db)
    alice = users.get_or_create(tg_id=1001, first_name="Алиса", last_name="Иванова")
    bob = users.get_or_create(tg_id=1002, first_name="Борис", last_name="Петров")
    start = datetime(2026, 6, 20)
    for tournament_index in range(3):
        tournament = _closed_tournament(
            db,
            title=f"T{tournament_index}",
            played_at=start + timedelta(days=8 * tournament_index),
            chat_id=100 + tournament_index,
            url=f"https://aetherhub.com/Tourney/RoundTourney/{1000 + tournament_index}",
        )
        _participant(db, tournament.id, alice)
        _participant(db, tournament.id, bob)
        for round_number in range(1, 5):
            _pair(db, tournament.id, round_number, alice, bob)
    db.commit()

    snapshot = RankedPreseasonService(db).calculate(start=start, end=datetime(2026, 9, 20))

    assert snapshot.quality.matches_included == 12
    assert snapshot.quality.unresolved_matches == 0
    assert snapshot.top()[0].user_id == alice.id
    assert snapshot.top()[0].matches == 12
    assert snapshot.top()[0].tournaments == 3
    assert snapshot.top()[0].calibrated


def test_preseason_applies_empty_week_to_inactive_players(db):
    states, _records = RankedPreseasonService._calculate_periods(
        [
            RankedMatch(1, datetime(2026, 6, 20), 1, 1, 3, 1.0),
            RankedMatch(2, datetime(2026, 7, 4), 1, 2, 3, 1.0),
        ],
        start=datetime(2026, 6, 20),
        period_days=7,
    )

    after_first_match = update_glicko2(
        Glicko2Rating(),
        [(Glicko2Rating(), 1.0)],
    )
    after_empty_week = update_glicko2(after_first_match, [])
    after_second_inactive_week = update_glicko2(after_empty_week, [])
    assert states[1].deviation > after_first_match.deviation
    assert states[1].deviation == pytest.approx(after_second_inactive_week.deviation)


def test_preseason_resolves_reversed_name_with_initial(db):
    users = UserService(db)
    alexey = users.get_or_create(tg_id=2001, first_name="Алексей А.", last_name="Боронко")
    maria = users.get_or_create(tg_id=2002, first_name="Мария", last_name="Сорокотяга")
    tournament = _closed_tournament(db, title="Initial", played_at=datetime(2026, 7, 23), chat_id=201)
    _participant(db, tournament.id, alexey)
    _participant(db, tournament.id, maria)
    db.add_all(
        [
            models.RoundPairing(
                tournament_id=tournament.id,
                round_number=1,
                player_name="Боронко Алексей А.",
                opponent_name="Сорокотяга Мария",
                player_wins=2,
                opponent_wins=1,
            ),
            models.RoundPairing(
                tournament_id=tournament.id,
                round_number=1,
                player_name="Сорокотяга Мария",
                opponent_name="Боронко Алексей А.",
                player_wins=1,
                opponent_wins=2,
            ),
        ]
    )
    db.commit()

    snapshot = RankedPreseasonService(db).calculate(
        start=datetime(2026, 6, 20),
        end=datetime(2026, 9, 20),
        min_matches=1,
        min_tournaments=1,
    )

    assert snapshot.quality.unresolved_matches == 0
    assert {entry.user_id for entry in snapshot.entries} == {alexey.id, maria.id}


def test_preseason_resolves_burbaev_one_letter_typo(db):
    users = UserService(db)
    burbaev = users.get_or_create(tg_id=3001, first_name="Константин", last_name="Бурбаев")
    opponent = users.get_or_create(tg_id=3002, first_name="Никита", last_name="Мясников")
    tournament = _closed_tournament(db, title="Typo", played_at=datetime(2026, 8, 14), chat_id=301)
    _participant(db, tournament.id, burbaev)
    _participant(db, tournament.id, opponent)
    db.add_all(
        [
            models.RoundPairing(
                tournament_id=tournament.id,
                round_number=1,
                player_name="Бурбаев Констанин",
                opponent_name="Мясников Никита",
                player_wins=2,
                opponent_wins=0,
            ),
            models.RoundPairing(
                tournament_id=tournament.id,
                round_number=1,
                player_name="Мясников Никита",
                opponent_name="Бурбаев Констанин",
                player_wins=0,
                opponent_wins=2,
            ),
        ]
    )
    db.commit()

    snapshot = RankedPreseasonService(db).calculate(
        start=datetime(2026, 6, 20),
        end=datetime(2026, 9, 20),
        min_matches=1,
        min_tournaments=1,
    )

    assert snapshot.quality.unresolved_matches == 0
    assert snapshot.top()[0].user_id == burbaev.id


def test_preseason_formats_legacy_swapped_user_fields_as_surname_first(db):
    user = models.User(tg_id=3003, first_name="Лактанов", last_name="Глеб")

    assert RankedPreseasonService._display_name(user) == "Лактанов Глеб"


def test_preseason_excludes_duplicate_aetherhub_tournament(db):
    users = UserService(db)
    alice = users.get_or_create(tg_id=4001, first_name="Алиса", last_name="Иванова")
    bob = users.get_or_create(tg_id=4002, first_name="Борис", last_name="Петров")
    url = "https://aetherhub.com/Tourney/RoundTourney/9999"
    for index in range(2):
        tournament = _closed_tournament(
            db,
            title=f"Duplicate {index}",
            played_at=datetime(2026, 7, 2 + index),
            chat_id=401 + index,
            url=url if index == 0 else f"{url}?utm_source=bot",
        )
        _participant(db, tournament.id, alice)
        _participant(db, tournament.id, bob)
        _pair(db, tournament.id, 1, alice, bob)
    db.commit()

    snapshot = RankedPreseasonService(db).calculate(
        start=datetime(2026, 6, 20),
        end=datetime(2026, 9, 20),
        min_matches=1,
        min_tournaments=1,
    )

    assert snapshot.quality.tournaments_included == 1
    assert snapshot.quality.excluded_duplicate_source == 1
    assert snapshot.quality.matches_included == 1


def test_admin_handler_is_private_and_formats_top(db):
    users = UserService(db)
    admin = users.get_or_create(tg_id=5001, first_name="Админ")
    admin.is_admin = True
    outsider = users.get_or_create(tg_id=5002, first_name="Неадмин")
    alice = users.get_or_create(tg_id=5003, first_name="Алиса", last_name="Иванова")
    bob = users.get_or_create(tg_id=5004, first_name="Борис", last_name="Петров")
    db.commit()
    start = datetime(2026, 6, 20)
    for tournament_index in range(3):
        tournament = _closed_tournament(
            db,
            title=f"Handler {tournament_index}",
            played_at=start + timedelta(days=8 * tournament_index),
            chat_id=501 + tournament_index,
        )
        _participant(db, tournament.id, alice)
        _participant(db, tournament.id, bob)
        for round_number in range(1, 5):
            _pair(db, tournament.id, round_number, alice, bob)
    db.commit()
    handler = RankedPreseasonHandler(RankedPreseasonService(db), users)

    assert handler.handle(outsider.tg_id).text == NOT_ADMIN
    result = handler.handle(admin.tg_id)
    assert "Moscow Pauper Ranked" in result.text
    assert "Иванова Алиса" in result.text
    assert "Рейтинг видит только администратор" in result.text
