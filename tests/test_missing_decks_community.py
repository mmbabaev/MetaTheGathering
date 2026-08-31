"""Community deck entry opened by the meta-police reminder (#254)."""

import pytest

from bot.handlers.player import PlayerHandler
from bot.keyboards import CB_FILL_MISSING_PICK, CB_FILL_MISSING_SET
from bot.messages import META_POLICE_DECK_ALREADY_FILLED, META_POLICE_FILL_UNAVAILABLE
from core import models
from services.feature_flags import FeatureFlags


@pytest.fixture
def player_handler(svc, user_svc, arch_svc, keyboards, aetherhub_svc, features):
    return PlayerHandler(svc, user_svc, arch_svc, keyboards, aetherhub_svc, features)


def _activate(db, tournament_id: int) -> None:
    tournament = db.get(models.Tournament, tournament_id)
    tournament.missing_decks_reminder_1d_sent_at = models.utc_now()
    db.commit()


def _callbacks(result) -> list[str]:
    return [button.callback_data for row in result.keyboard.inline_keyboard for button in row if button.callback_data]


def test_flow_is_unavailable_before_meta_police(player_handler, tournament, user_alice):
    result = player_handler.handle_fill_missing_deeplink(tournament.id, user_alice.tg_id)

    assert result.text == META_POLICE_FILL_UNAVAILABLE
    assert result.keyboard is None


def test_flow_is_feature_gated(player_handler, db, ff_svc, tournament, user_alice):
    _activate(db, tournament.id)
    ff_svc.toggle(FeatureFlags.RECORD_OPPONENTS)

    result = player_handler.handle_fill_missing_deeplink(tournament.id, user_alice.tg_id)

    assert result.text == META_POLICE_FILL_UNAVAILABLE


def test_direct_set_is_feature_gated(player_handler, db, ff_svc, svc, user_svc, tournament, user_alice, archetype_burn):
    target = user_svc.get_or_create(tg_id=2002, first_name="Глеб")
    participant = svc.register_participant(tournament_id=tournament.id, user_id=target.id)
    _activate(db, tournament.id)
    ff_svc.toggle(FeatureFlags.RECORD_OPPONENTS)

    result = player_handler.handle_set_missing_deck(
        user_alice.tg_id,
        participant.id,
        archetype_burn.id,
    )

    assert result.is_alert
    assert result.text == META_POLICE_FILL_UNAVAILABLE
    assert svc.get_participant(tournament.id, target.id).archetype_id is None


def test_missing_participant_is_sent_to_own_deck_first(player_handler, db, svc, tournament, user_alice, archetype_burn):
    svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
    _activate(db, tournament.id)

    result = player_handler.handle_fill_missing_deeplink(tournament.id, user_alice.tg_id)

    assert result.text == "Выберите свою колоду:"
    assert any(
        callback == f"{CB_FILL_MISSING_SET}:{svc.get_participant(tournament.id, user_alice.id).id}:{archetype_burn.id}"
        for callback in _callbacks(result)
    )


def test_filled_participant_sees_only_unfilled_players(
    player_handler, db, svc, user_svc, tournament, user_alice, archetype_burn
):
    missing = user_svc.get_or_create(tg_id=2002, first_name="Глеб", last_name="Лактанов")
    svc.register_participant(
        tournament_id=tournament.id,
        user_id=user_alice.id,
        archetype_id=archetype_burn.id,
        deck_added_by_tg_id=user_alice.tg_id,
    )
    missing_participant = svc.register_participant(tournament_id=tournament.id, user_id=missing.id)
    _activate(db, tournament.id)

    result = player_handler.handle_fill_missing_deeplink(tournament.id, user_alice.tg_id)

    assert "Выберите игрока" in result.text
    callbacks = _callbacks(result)
    assert callbacks == [f"{CB_FILL_MISSING_PICK}:{missing_participant.id}"]
    assert "Лактанов Глеб" in result.keyboard.inline_keyboard[0][0].text


def test_flow_highlights_current_players_unfilled_opponents(
    player_handler, db, svc, user_svc, tournament, user_alice, archetype_burn
):
    bob = user_svc.get_or_create(tg_id=2002, first_name="Боб")
    carol = user_svc.get_or_create(tg_id=2003, first_name="Кэрол")
    svc.register_participant(
        tournament_id=tournament.id,
        user_id=user_alice.id,
        archetype_id=archetype_burn.id,
        deck_added_by_tg_id=user_alice.tg_id,
    )
    svc.register_participant(tournament_id=tournament.id, user_id=bob.id)
    svc.register_participant(tournament_id=tournament.id, user_id=carol.id)
    db.add_all(
        [
            models.RoundPairing(
                tournament_id=tournament.id,
                round_number=2,
                player_name="Alice",
                opponent_name="Боб",
            ),
            models.RoundPairing(
                tournament_id=tournament.id,
                round_number=4,
                player_name="Alice",
                opponent_name="Кэрол",
            ),
        ]
    )
    db.commit()
    _activate(db, tournament.id)

    result = player_handler.handle_fill_missing_deeplink(tournament.id, user_alice.tg_id)

    assert "Твои незаполненные оппоненты:" in result.text
    assert "• Боб — раунд 2" in result.text
    assert "• Кэрол — раунд 4" in result.text


def test_nonparticipant_can_help_fill_missing_player(player_handler, db, svc, user_svc, tournament, user_alice):
    missing = user_svc.get_or_create(tg_id=2002, first_name="Глеб")
    participant = svc.register_participant(tournament_id=tournament.id, user_id=missing.id)
    _activate(db, tournament.id)

    result = player_handler.handle_fill_missing_deeplink(tournament.id, user_alice.tg_id)

    assert _callbacks(result) == [f"{CB_FILL_MISSING_PICK}:{participant.id}"]


def test_recording_other_player_persists_filler_and_keeps_helping(
    player_handler, db, svc, user_svc, tournament, user_alice, archetype_burn
):
    first = user_svc.get_or_create(tg_id=2002, first_name="Глеб")
    second = user_svc.get_or_create(tg_id=2003, first_name="Борис")
    first_participant = svc.register_participant(tournament_id=tournament.id, user_id=first.id)
    second_participant = svc.register_participant(tournament_id=tournament.id, user_id=second.id)
    _activate(db, tournament.id)

    result = player_handler.handle_set_missing_deck(
        user_alice.tg_id,
        first_participant.id,
        archetype_burn.id,
    )

    saved = svc.get_participant(tournament.id, first.id)
    assert saved.archetype_id == archetype_burn.id
    assert saved.deck_added_by_tg_id == user_alice.tg_id
    assert "Глеб записан как Burn" in result.text
    assert _callbacks(result) == [f"{CB_FILL_MISSING_PICK}:{second_participant.id}"]


def test_stale_callback_never_overwrites_filled_deck(
    player_handler, db, svc, user_svc, arch_svc, tournament, user_alice, archetype_burn
):
    target = user_svc.get_or_create(tg_id=2002, first_name="Глеб")
    participant = svc.register_participant(tournament_id=tournament.id, user_id=target.id)
    _activate(db, tournament.id)
    affinity = arch_svc.get_or_create_by_name("Affinity")
    svc.set_participant_archetype(
        participant_id=participant.id,
        archetype_id=affinity.id,
        deck_added_by_tg_id=target.tg_id,
    )

    result = player_handler.handle_set_missing_deck(
        user_alice.tg_id,
        participant.id,
        archetype_burn.id,
    )

    saved = svc.get_participant(tournament.id, target.id)
    assert result.is_alert
    assert result.text == META_POLICE_DECK_ALREADY_FILLED
    assert saved.archetype_id == affinity.id
    assert saved.deck_added_by_tg_id == target.tg_id


def test_custom_deck_is_recorded_with_filler(player_handler, db, svc, user_svc, tournament, user_alice):
    target = user_svc.get_or_create(tg_id=2002, first_name="Глеб")
    participant = svc.register_participant(tournament_id=tournament.id, user_id=target.id)
    _activate(db, tournament.id)

    result = player_handler.handle_set_missing_custom_deck(
        user_alice.tg_id,
        participant.id,
        "Turbo Fog",
    )

    saved = svc.get_participant(tournament.id, target.id)
    assert not result.is_alert
    assert saved.archetype.name == "Turbo Fog"
    assert saved.deck_added_by_tg_id == user_alice.tg_id


def test_closed_tournament_cannot_be_modified(
    player_handler, db, svc, user_svc, tournament, user_alice, archetype_burn
):
    target = user_svc.get_or_create(tg_id=2002, first_name="Глеб")
    participant = svc.register_participant(tournament_id=tournament.id, user_id=target.id)
    _activate(db, tournament.id)
    svc.close_tournament(tournament.id)

    result = player_handler.handle_set_missing_deck(
        user_alice.tg_id,
        participant.id,
        archetype_burn.id,
    )

    assert result.is_alert
    assert result.text == META_POLICE_FILL_UNAVAILABLE
    assert svc.get_participant(tournament.id, target.id).archetype_id is None
