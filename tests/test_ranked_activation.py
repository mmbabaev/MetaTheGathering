from datetime import datetime, timedelta

from core import models
from core.schemas import TournamentCreate
from services.ranked import Glicko2Rating, update_glicko2
from services.ranked_activation import (
    RANKED_ACTIVATION_CELLAR,
    RANKED_ACTIVATION_SELF_BOT,
    RankedPublicStateService,
    activate_participant,
)
from services.ranked_round_info import RankedRoundInfoService
from services.tournament import TournamentService
from services.user import UserService


def _tournament(db, index: int, *, closed: bool = True):
    tournament = TournamentService(db).create_tournament(
        TournamentCreate(title=f"Ranked {index}", chat_id=10_000 + index, club="Edinorog")
    )
    row = db.get(models.Tournament, tournament.id)
    row.started_at = datetime(2026, 9, 20) + timedelta(days=index)
    if closed:
        row.status = models.TournamentStatus.CLOSED
    db.commit()
    return row


def _participant(db, tournament, user, source=None):
    participant = models.Participant(tournament_id=tournament.id, user_id=user.id)
    activate_participant(participant, source, activated_at=tournament.started_at)
    db.add(participant)
    db.commit()
    return participant


def test_activation_is_durable_and_self_bot_upgrades_cellar(db):
    participant = models.Participant(tournament_id=1, user_id=1)
    first = datetime(2026, 9, 20, 12)

    activate_participant(participant, RANKED_ACTIVATION_CELLAR, activated_at=first)
    activate_participant(participant, RANKED_ACTIVATION_SELF_BOT, activated_at=first + timedelta(hours=1))

    assert participant.ranked_activated_at == first
    assert participant.ranked_activation_source == RANKED_ACTIVATION_SELF_BOT


def test_tournament_service_records_imported_players_later_self_action(db):
    tournament = _tournament(db, 0, closed=False)
    user = UserService(db).get_or_create(tg_id=7001, first_name="Кирилл", last_name="Андреев")
    participant = TournamentService(db).register_participant(tournament_id=tournament.id, user_id=user.id)

    updated = TournamentService(db).set_participant_archetype(
        participant_id=participant.id,
        archetype_id=None,
        ranked_activation_source=RANKED_ACTIVATION_SELF_BOT,
    )

    assert updated.ranked_activated_at is not None
    assert updated.ranked_activation_source == RANKED_ACTIVATION_SELF_BOT


def test_two_misses_deactivate_and_each_reactivation_starts_new_penalty_cycle(db):
    user = UserService(db).get_or_create(tg_id=7002, first_name="Игрок")
    tournaments = [_tournament(db, index) for index in range(7)]
    _participant(db, tournaments[0], user, RANKED_ACTIVATION_SELF_BOT)
    _participant(db, tournaments[1], user)
    _participant(db, tournaments[2], user)
    _participant(db, tournaments[3], user)  # already inactive: no repeated penalty
    _participant(db, tournaments[4], user, RANKED_ACTIVATION_CELLAR)
    _participant(db, tournaments[5], user)
    _participant(db, tournaments[6], user)

    state = RankedPublicStateService(db).calculate(tuple(t.id for t in tournaments))[user.id]

    assert state.active is False
    assert state.missed_tournaments == 0
    assert state.penalty == 100
    assert state.penalty_cycles == 2


def test_current_tournament_self_action_reactivates_without_removing_penalty(db):
    user = UserService(db).get_or_create(tg_id=7003, first_name="Игрок")
    first, second, third = [_tournament(db, index) for index in range(3)]
    current = _tournament(db, 3, closed=False)
    _participant(db, first, user, RANKED_ACTIVATION_SELF_BOT)
    _participant(db, second, user)
    _participant(db, third, user)
    _participant(db, current, user, RANKED_ACTIVATION_CELLAR)

    state = RankedPublicStateService(db).calculate(
        (first.id, second.id, third.id),
        activation_tournament_ids=(current.id,),
    )[user.id]

    assert state.active is True
    assert state.missed_tournaments == 0
    assert state.penalty == 50


def test_round_info_hides_inactive_opponent_and_forecasts_public_opponent(db):
    current = _tournament(db, 10, closed=False)
    users = UserService(db)
    own = users.get_or_create(tg_id=7010, first_name="Свой")
    opponent = users.get_or_create(tg_id=7011, first_name="Оппонент")
    _participant(db, current, own, RANKED_ACTIVATION_SELF_BOT)
    opponent_participant = _participant(db, current, opponent)
    service = RankedRoundInfoService(
        db,
        season_start=datetime(2026, 9, 20),
        now=datetime(2026, 10, 5),
    )

    hidden = service.for_pairing(current.id, own.id, opponent.id)
    assert hidden is not None
    assert hidden.opponent_hidden is True
    assert hidden.opponent_score is None
    assert hidden.win_delta is None

    activate_participant(opponent_participant, RANKED_ACTIVATION_SELF_BOT)
    db.commit()
    refreshed = RankedRoundInfoService(
        db,
        season_start=datetime(2026, 9, 20),
        now=datetime(2026, 10, 5),
    ).for_pairing(current.id, own.id, opponent.id)

    assert refreshed is not None
    assert refreshed.opponent_hidden is False
    assert refreshed.opponent_score == 800
    assert all(delta is not None for delta in (refreshed.win_delta, refreshed.draw_delta, refreshed.loss_delta))


def test_round_forecast_reports_public_delta_with_participation_bonus():
    own = Glicko2Rating(rating=1500, deviation=50, volatility=0.06)
    opponent = Glicko2Rating(rating=1500, deviation=50, volatility=0.06)
    hidden_win_delta = update_glicko2(own, [(opponent, 1.0)]).ranked_score - own.ranked_score
    hidden_draw_delta = update_glicko2(own, [(opponent, 0.5)]).ranked_score - own.ranked_score
    hidden_loss_delta = update_glicko2(own, [(opponent, 0.0)]).ranked_score - own.ranked_score

    public_win_delta = RankedRoundInfoService._forecast_delta(own, opponent, 0, 0, 1.0)
    public_draw_delta = RankedRoundInfoService._forecast_delta(own, opponent, 0, 0, 0.5)
    public_loss_delta = RankedRoundInfoService._forecast_delta(own, opponent, 0, 0, 0.0)

    assert (hidden_win_delta, hidden_draw_delta, hidden_loss_delta) == (6, -1, -8)
    assert (public_win_delta, public_draw_delta, public_loss_delta) == (7, 0, -7)
