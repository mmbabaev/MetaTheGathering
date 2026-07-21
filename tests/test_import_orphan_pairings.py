"""Reimport removes orphan pairings when AetherHub re-pairs a round.

Регрессия: AetherHub перегенерировал пары раунда (игрока перепарили). Upsert по имени
добавлял новую пару, но старая строка (игрок, которого больше нет) оставалась без счёта и
держала is_tournament_complete=False — «стендинги ещё не готовы».
"""

from core.schemas import TournamentCreate
from services.aetherhub_import_service import AetherhubImportService
from services.aetherhub_models import AetherhubPairing, AetherhubRound, AetherhubTournamentData


def _round1(pairs):
    return AetherhubTournamentData(
        url="https://aetherhub.com/Tourney/RoundTourney/1",
        players=[p.player for p in pairs],
        rounds=[AetherhubRound(number=1, pairings=pairs)],
    )


def test_reimport_removes_orphan_when_repaired(db, svc):
    t = svc.create_tournament(TournamentCreate(title="T", chat_id=1))
    imp = AetherhubImportService(db)

    # первый импорт: Бабаев vs «Акимов Егор», ещё без счёта
    imp.import_tournament(
        t.id,
        _round1(
            [
                AetherhubPairing(player="Бабаев Михаил", opponent="Акимов Егор", table_number=9),
                AetherhubPairing(player="Акимов Егор", opponent="Бабаев Михаил", table_number=9),
            ]
        ),
    )
    assert imp.is_tournament_complete(t.id) is False

    # AetherHub перепарил: Бабаев vs «Акимов Матвей» со счётом; «Акимов Егор» больше нет
    imp.import_tournament(
        t.id,
        _round1(
            [
                AetherhubPairing(
                    player="Бабаев Михаил", opponent="Акимов Матвей", table_number=9, player_wins=2, opponent_wins=1
                ),
                AetherhubPairing(
                    player="Акимов Матвей", opponent="Бабаев Михаил", table_number=9, player_wins=1, opponent_wins=2
                ),
            ]
        ),
    )

    names = {p.player_name for p in imp.get_pairings(t.id, 1)}
    assert "Акимов Егор" not in names  # сирота удалена
    assert names == {"Бабаев Михаил", "Акимов Матвей"}
    assert imp.is_tournament_complete(t.id) is True  # матчей без счёта не осталось


def test_empty_round_does_not_wipe_existing(db, svc):
    """Пустой раунд в свежих данных не должен стирать уже сохранённые пары."""
    t = svc.create_tournament(TournamentCreate(title="T", chat_id=1))
    imp = AetherhubImportService(db)
    imp.import_tournament(
        t.id,
        _round1(
            [
                AetherhubPairing(player="A", opponent="B", table_number=1, player_wins=2, opponent_wins=0),
                AetherhubPairing(player="B", opponent="A", table_number=1, player_wins=0, opponent_wins=2),
            ]
        ),
    )
    # повторный импорт с пустым раундом 1
    imp.import_tournament(
        t.id,
        AetherhubTournamentData(url="u", players=["A", "B"], rounds=[AetherhubRound(number=1, pairings=[])]),
    )
    assert {p.player_name for p in imp.get_pairings(t.id, 1)} == {"A", "B"}
