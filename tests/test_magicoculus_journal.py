from sqlalchemy.exc import IntegrityError

from core import models
from core.schemas import TournamentCreate


def test_one_journal_row_per_source_tournament(db, svc):
    tournament = svc.create_tournament(TournamentCreate(title="Pauper", chat_id=1))
    db.add(
        models.MagicOculusImport(
            tournament_id=tournament.id,
            aetherhub_url="https://aetherhub.com/Tourney/RoundTourney/1",
        )
    )
    db.commit()

    db.add(
        models.MagicOculusImport(
            tournament_id=tournament.id,
            aetherhub_url="https://aetherhub.com/Tourney/RoundTourney/2",
        )
    )

    try:
        db.commit()
        assert False, "duplicate source tournament must fail"
    except IntegrityError:
        db.rollback()


def test_aetherhub_url_cannot_be_imported_twice(db, svc):
    first = svc.create_tournament(TournamentCreate(title="First", chat_id=1))
    second = svc.create_tournament(TournamentCreate(title="Second", chat_id=2))
    url = "https://aetherhub.com/Tourney/RoundTourney/1"
    db.add(models.MagicOculusImport(tournament_id=first.id, aetherhub_url=url))
    db.commit()
    db.add(models.MagicOculusImport(tournament_id=second.id, aetherhub_url=url))

    try:
        db.commit()
        assert False, "duplicate AetherHub URL must fail"
    except IntegrityError:
        db.rollback()
