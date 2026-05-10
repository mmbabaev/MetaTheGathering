"""E2E regression tests: create → import → export flow."""

from core.schemas import TournamentCreate
from services.aetherhub_import_service import AetherhubImportService
from services.export import ExportService
from services.tournament import TournamentService
from tests.e2e.conftest import CHAT_ID


def test_create_tournament(svc):
    t = svc.create_tournament(TournamentCreate(title="Test", chat_id=CHAT_ID))
    assert t.id is not None
    assert t.title == "Test"
    assert t.status.value == "registration"


def test_delete_last(db, svc):
    t1 = svc.create_tournament(TournamentCreate(title="First", chat_id=CHAT_ID))
    svc.close_tournament(t1.id)
    t2 = svc.create_tournament(TournamentCreate(title="Second", chat_id=CHAT_ID))
    svc.close_tournament(t2.id)

    last = svc.list_tournaments_for_chat(CHAT_ID, limit=1)
    assert last[0].title == "Second"

    svc.delete_tournament(last[0].id)
    remaining = svc.list_tournaments_for_chat(CHAT_ID, limit=10)
    assert len(remaining) == 1
    assert remaining[0].title == "First"


def test_import_aetherhub(db, tournament, aetherhub_data):
    result = AetherhubImportService(db).import_tournament(tournament.id, aetherhub_data)

    assert result.registered == 4
    assert result.already_registered == 0
    assert result.pairings_saved == 8  # 4 записи × 2 раунда

    participants = TournamentService(db).list_participants_for_tournament(tournament.id)
    assert len(participants) == 4

    from sqlalchemy import select

    from core.models import Participant, User

    rows = db.execute(
        select(Participant, User)
        .join(User, User.id == Participant.user_id)
        .where(Participant.tournament_id == tournament.id)
    ).all()
    places = {u.first_name: p.final_place for p, u in rows}
    assert places["Иван"] == 1
    assert places["Сидор"] == 2


def test_import_idempotent(db, tournament, aetherhub_data):
    svc = AetherhubImportService(db)
    svc.import_tournament(tournament.id, aetherhub_data)
    result2 = svc.import_tournament(tournament.id, aetherhub_data)

    assert result2.registered == 0
    assert result2.already_registered == 4


def test_export_excel(db, tournament, aetherhub_data, tmp_path):
    AetherhubImportService(db).import_tournament(tournament.id, aetherhub_data)
    data, filename = ExportService(db).export_participants_excel(tournament.id)

    assert len(data) > 0
    assert filename.endswith(".xlsx")
    out = tmp_path / filename
    out.write_bytes(data)
    assert out.exists()


def test_full_flow(db, svc, aetherhub_data, tmp_path):
    """Полный флоу: создать → импорт → экспорт → удалить."""
    t = svc.create_tournament(TournamentCreate(title="Pauper Friday #99", chat_id=CHAT_ID))

    result = AetherhubImportService(db).import_tournament(t.id, aetherhub_data)
    assert result.registered == 4

    data, filename = ExportService(db).export_participants_excel(t.id)
    assert len(data) > 0
    (tmp_path / filename).write_bytes(data)

    svc.close_tournament(t.id)
    last = svc.list_tournaments_for_chat(CHAT_ID, limit=1)
    assert last[0].id == t.id
    svc.delete_tournament(last[0].id)
    assert svc.list_tournaments_for_chat(CHAT_ID) == []
