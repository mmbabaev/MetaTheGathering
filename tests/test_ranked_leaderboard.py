from datetime import datetime, timedelta
from unittest.mock import MagicMock

from bot.handlers.leaderboard import LEADERBOARD_PAGE_SIZE, RankedLeaderboardHandler, leaderboard_menu
from bot.keyboards import (
    CB_LEADERBOARD_ENDSTEP,
    CB_LEADERBOARD_MENU,
    CB_LEADERBOARD_MOSCOW,
    CB_LEADERBOARD_SOCIAL,
    CB_RANKED_ME,
    CB_RANKED_PAGE,
    CB_RANKED_RULES,
)
from bot.messages import RANKED_RULES_TEXT
from core import models
from core.schemas import TournamentCreate
from services.feature_flags import FeatureFlagService
from services.ranked import Glicko2Rating, RankedPreseasonService, public_ranked_score
from services.ranked_activation import RANKED_ACTIVATION_SELF_BOT, activate_participant
from services.ranked_leaderboard import (
    RankedLeaderboard,
    RankedLeaderboardRow,
    RankedLeaderboardService,
)
from services.tournament import TournamentService
from services.user import UserService


def _callbacks(result):
    return [button.callback_data for row in result.keyboard.inline_keyboard for button in row]


def test_leaderboard_menu_offers_moscow_endstep_and_social():
    result = leaderboard_menu()

    assert result.text == ("🏆 Pauper Ranked\n\nВыберите лидерборд:\n\nEndstep RU пока доступен только владельцу бота.")
    assert _callbacks(result) == [CB_LEADERBOARD_MOSCOW, CB_LEADERBOARD_ENDSTEP, CB_LEADERBOARD_SOCIAL]


def _ranked_tournament(db, *, title: str, started_at: datetime, closed: bool):
    created = TournamentService(db).create_tournament(
        TournamentCreate(title=title, chat_id=10_000 + int(started_at.timestamp()), club="Goldfish")
    )
    tournament = db.get(models.Tournament, created.id)
    tournament.started_at = started_at
    if closed:
        tournament.status = models.TournamentStatus.CLOSED
    db.commit()
    return tournament


def _participant(db, tournament, user, *, activated_at=None):
    participant = models.Participant(tournament_id=tournament.id, user_id=user.id)
    if activated_at is not None:
        activate_participant(participant, RANKED_ACTIVATION_SELF_BOT, activated_at=activated_at)
    db.add(participant)
    db.commit()
    return participant


def _pair(db, tournament, player, opponent, score=(2, 0)):
    player_name = f"{player.last_name} {player.first_name}"
    opponent_name = f"{opponent.last_name} {opponent.first_name}"
    db.add_all(
        [
            models.RoundPairing(
                tournament_id=tournament.id,
                round_number=1,
                player_name=player_name,
                opponent_name=opponent_name,
                player_wins=score[0],
                opponent_wins=score[1],
            ),
            models.RoundPairing(
                tournament_id=tournament.id,
                round_number=1,
                player_name=opponent_name,
                opponent_name=player_name,
                player_wins=score[1],
                opponent_wins=score[0],
            ),
        ]
    )
    db.commit()


def test_future_tournament_self_registration_waits_for_completed_close(db):
    now = datetime(2026, 9, 10, 12)
    tournament = _ranked_tournament(
        db,
        title="Next Friday",
        started_at=now + timedelta(days=2),
        closed=False,
    )
    users = UserService(db)
    player = users.get_or_create(tg_id=8101, first_name="Михаил", last_name="Бабаев")
    opponent = users.get_or_create(tg_id=8102, first_name="Иван", last_name="Соперников")
    _participant(db, tournament, player, activated_at=now - timedelta(minutes=1))
    _participant(db, tournament, opponent)
    _pair(db, tournament, player, opponent)

    before_close = RankedLeaderboardService(db, now=now).calculate()

    assert before_close.rows == ()

    tournament.status = models.TournamentStatus.CLOSED
    db.commit()
    after_close = RankedLeaderboardService(db, now=now + timedelta(days=3)).calculate()

    assert any(row.user_id == player.id for row in after_close.rows)


def test_player_who_withdraws_before_close_is_not_published(db):
    now = datetime(2026, 9, 10, 12)
    tournament = _ranked_tournament(db, title="Next Friday", started_at=now + timedelta(days=2), closed=False)
    users = UserService(db)
    withdrawn = users.get_or_create(tg_id=8110, first_name="Вышел", last_name="Заранее")
    player = users.get_or_create(tg_id=8111, first_name="Остался", last_name="Первый")
    opponent = users.get_or_create(tg_id=8112, first_name="Остался", last_name="Второй")
    _participant(db, tournament, withdrawn, activated_at=now)
    _participant(db, tournament, player)
    _participant(db, tournament, opponent)
    TournamentService(db).unregister_participant(tournament.id, withdrawn.id)
    _pair(db, tournament, player, opponent)
    tournament.status = models.TournamentStatus.CLOSED
    db.commit()

    leaderboard = RankedLeaderboardService(db, now=now + timedelta(days=3)).calculate()

    assert all(row.user_id != withdrawn.id for row in leaderboard.rows)


def test_each_miss_penalizes_player_without_hiding_them(db):
    start = datetime(2026, 9, 1)
    users = UserService(db)
    player = users.get_or_create(tg_id=8102, first_name="Иван", last_name="Игроков")
    opponent = users.get_or_create(tg_id=8103, first_name="Олег", last_name="Соперников")
    closed = [
        _ranked_tournament(db, title=f"T{index}", started_at=start + timedelta(days=index), closed=True)
        for index in range(3)
    ]
    for index, tournament in enumerate(closed):
        _participant(db, tournament, player, activated_at=tournament.started_at if index == 0 else None)
        _participant(db, tournament, opponent)
        _pair(db, tournament, player, opponent)

    leaderboard = RankedLeaderboardService(db, now=start + timedelta(days=4)).calculate()
    player_row = next(row for row in leaderboard.rows if row.user_id == player.id)
    entry = next(
        entry
        for entry in RankedPreseasonService(db)
        .calculate(start=datetime(2026, 6, 20), end=start + timedelta(days=4, minutes=3))
        .entries
        if entry.user_id == player.id
    )
    expected = public_ranked_score(
        Glicko2Rating(entry.rating, entry.deviation, entry.volatility),
        matches=entry.matches,
        penalty=20,
    )
    assert player_row.score == expected


def test_public_score_adds_one_point_per_match_without_changing_glicko():
    rating = Glicko2Rating(rating=1500, deviation=100, volatility=0.06)

    score = public_ranked_score(rating, matches=4, penalty=10)

    assert score == 1294
    assert rating == Glicko2Rating(rating=1500, deviation=100, volatility=0.06)


def _snapshot(size: int, *, id_offset: int = 0) -> RankedLeaderboard:
    return RankedLeaderboard(
        generated_at=datetime(2026, 9, 10),
        rows=tuple(
            RankedLeaderboardRow(
                position=index,
                user_id=index + id_offset,
                name=f"Игрок {index:02d}",
                score=1701 - index,
            )
            for index in range(1, size + 1)
        ),
    )


def _handler(db, snapshot: RankedLeaderboard):
    ranked = MagicMock()
    ranked.calculate.return_value = snapshot
    return RankedLeaderboardHandler(ranked, UserService(db), FeatureFlagService(db))


def test_leaderboard_pages_contain_ten_players_and_navigation(db):
    handler = _handler(db, _snapshot(21))

    first = handler.handle_page(0)
    second = handler.handle_page(1)
    last = handler.handle_page(2)

    assert "1 — Игрок 01 — 1700" in first.text
    assert "10 — Игрок 10 — 1691" in first.text
    assert "11 — Игрок 11" not in first.text
    assert f"{CB_RANKED_PAGE}:1" in _callbacks(first)
    assert f"{CB_RANKED_PAGE}:0" in _callbacks(second)
    assert f"{CB_RANKED_PAGE}:2" in _callbacks(second)
    assert f"{CB_RANKED_PAGE}:1" in _callbacks(last)
    assert CB_RANKED_ME in _callbacks(last)
    assert f"{CB_RANKED_RULES}:2" in _callbacks(last)
    assert CB_LEADERBOARD_MENU in _callbacks(last)
    assert LEADERBOARD_PAGE_SIZE == 10


def test_initial_public_leaderboard_can_be_empty(db):
    result = _handler(db, _snapshot(0)).handle_page()

    assert "Публичный рейтинг пока пуст" in result.text
    assert CB_RANKED_ME in _callbacks(result)
    assert f"{CB_RANKED_RULES}:0" in _callbacks(result)


def test_where_am_i_opens_page_containing_player(db):
    user = models.User(id=17, tg_id=8117, first_name="Игрок", last_name="17")
    db.add(user)
    db.commit()
    handler = _handler(db, _snapshot(25))

    result = handler.handle_me(user.tg_id)

    assert "Страница 2/3" in result.text
    assert "👉 17 — Игрок 17 — 1684" in result.text
    assert CB_RANKED_ME not in _callbacks(result)


def test_where_am_i_explains_when_player_is_not_public(db):
    user = UserService(db).get_or_create(tg_id=8199, first_name="Скрытый")

    result = _handler(db, _snapshot(3, id_offset=100)).handle_me(user.tg_id)

    assert "пока нет в публичном рейтинге" in result.text
    assert f"{CB_RANKED_PAGE}:0" in _callbacks(result)


def test_rules_include_formula_and_back_button(db):
    result = _handler(db, _snapshot(1)).handle_rules(3)

    assert result.text == RANKED_RULES_TEXT
    assert "Score = round(R − 2 × RD + матчи)" in result.text
    assert "Glicko-2" in result.text
    assert len(result.text) < 4096
    assert _callbacks(result) == [f"{CB_RANKED_PAGE}:3"]
