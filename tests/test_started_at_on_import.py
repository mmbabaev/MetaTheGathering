"""started_at проставляется при первом импорте раунда (≈ старт игры).

Нужно для гарда минимальной длительности турнира в анонсе «сбор завершён».
"""

from core import models
from core.schemas import TournamentCreate
from services.aetherhub_import_service import AetherhubImportService
from services.aetherhub_models import AetherhubPairing, AetherhubRound, AetherhubTournamentData
from services.tournament import TournamentService


def _data(number=1):
    return AetherhubTournamentData(
        url="http://x",
        players=["Alice", "Bob"],
        rounds=[
            AetherhubRound(
                number=number,
                pairings=[
                    AetherhubPairing(player="Alice", opponent="Bob", table_number=1, player_wins=2, opponent_wins=1),
                    AetherhubPairing(player="Bob", opponent="Alice", table_number=1, player_wins=1, opponent_wins=2),
                ],
            )
        ],
    )


def test_started_at_set_on_first_round_import(db):
    t = TournamentService(db).create_tournament(TournamentCreate(title="Pauper", chat_id=1))
    assert db.get(models.Tournament, t.id).started_at is None

    AetherhubImportService(db).import_tournament(t.id, _data())

    assert db.get(models.Tournament, t.id).started_at is not None


def test_started_at_not_overwritten_on_later_import(db):
    t = TournamentService(db).create_tournament(TournamentCreate(title="Pauper", chat_id=1))
    svc = AetherhubImportService(db)
    svc.import_tournament(t.id, _data(number=1))
    first = db.get(models.Tournament, t.id).started_at

    svc.import_tournament(t.id, _data(number=2))

    assert db.get(models.Tournament, t.id).started_at == first


def test_started_at_stays_none_without_rounds(db):
    t = TournamentService(db).create_tournament(TournamentCreate(title="Pauper", chat_id=1))

    AetherhubImportService(db).import_tournament(t.id, AetherhubTournamentData(url="http://x", players=[], rounds=[]))

    assert db.get(models.Tournament, t.id).started_at is None
