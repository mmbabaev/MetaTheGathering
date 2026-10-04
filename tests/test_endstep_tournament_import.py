from pathlib import Path
from unittest.mock import Mock

from core import models
from services.endstep_tournament_import import EndstepTournamentImporter
from services.scryfall_cards import ScryfallCardResolver


def _write_exports(tmp_path: Path, *, player: str = "Alice") -> dict[str, str]:
    standings = tmp_path / "standings.csv"
    standings.write_text(
        "Place,Player,Status,Match points,Wins,Losses,Draws,OMW%,GW%,OGW%\n"
        f"1,{player},active,9,3,0,0,66.67,75,60\n"
        "2,Bob,active,6,2,1,0,50,60,55\n",
        encoding="utf-8",
    )
    pairings = tmp_path / "pairings.csv"
    pairings.write_text(
        "Round,Stage,Table,Player 1,Player 2,Games (P1-P2-draws),Result,Winner\n"
        f"1,Swiss,1,{player},Bob,2-0-0,Finished,{player}\n"
        "2,Swiss,1,Bob,Alice,2-0-0,No-show,Bob\n"
        "3,Swiss,2,Alice,,,Bye,\n",
        encoding="utf-8",
    )
    decklists = tmp_path / "decklists.csv"
    decklists.write_text(
        "Place,Player,Section,Quantity,Card\n"
        f"1,{player},Main,4,Lightning Bolt\n"
        f'1,{player},Main,1,"Card With, Comma"\n'
        f"1,{player},Sideboard,2,Hydroblast\n"
        "2,Bob,Main,60,Island\n",
        encoding="utf-8",
    )
    return {
        "standings_path": str(standings),
        "pairings_path": str(pairings),
        "decklists_path": str(decklists),
    }


def test_imports_real_csv_shapes_and_matches_endstep_user(db, user_svc, tmp_path):
    alice = user_svc.get_or_create(tg_id=1001, username="alice", first_name="Alice")
    alice.endstep_username = "Alice"
    db.commit()
    paths = _write_exports(tmp_path)

    summary = EndstepTournamentImporter(db).import_csvs(
        external_key="endstep:event-1",
        slug="event-1",
        title="Pauper Event #1",
        **paths,
    )

    assert (summary.standings, summary.pairings, summary.deck_cards, summary.matched_users) == (2, 3, 4, 1)
    tournament = db.get(models.EndstepTournament, summary.tournament_id)
    assert tournament is not None
    assert tournament.standings[0].user_id == alice.id
    assert next(card for card in tournament.deck_cards if card.card_name == "Card With, Comma")


def test_reimport_replaces_the_previous_snapshot(db, tmp_path):
    paths = _write_exports(tmp_path)
    importer = EndstepTournamentImporter(db)
    first = importer.import_csvs(
        external_key="endstep:event-1",
        slug="event-1",
        title="Old title",
        **paths,
    )

    updated = _write_exports(tmp_path, player="Carol")
    second = importer.import_csvs(
        external_key="endstep:event-1",
        slug="event-1",
        title="New title",
        **updated,
    )

    assert second.tournament_id == first.tournament_id
    tournament = db.get(models.EndstepTournament, first.tournament_id)
    assert tournament.title == "New title"
    assert [row.player_name for row in tournament.standings] == ["Carol", "Bob"]


def test_scryfall_resolver_caches_metadata_and_copies_urls_to_rows(db, tmp_path):
    paths = _write_exports(tmp_path)
    summary = EndstepTournamentImporter(db).import_csvs(
        external_key="endstep:event-1",
        slug="event-1",
        title="Pauper Event #1",
        **paths,
    )
    session = Mock()

    def get_card(*_args, params, **_kwargs):
        name = params["exact"]
        response = Mock(status_code=200)
        response.json.return_value = {
            "id": f"card-id-{name}",
            "name": name,
            "image_uris": {"normal": f"https://cards.scryfall.io/normal/{name}.jpg"},
        }
        return response

    session.get.side_effect = get_card

    resolver = ScryfallCardResolver(db, session=session, min_interval_seconds=0)
    assert resolver.resolve_tournament(summary.tournament_id) == 4

    card = db.query(models.EndstepDeckCard).filter_by(card_name="Lightning Bolt").one()
    assert card.image_uri.endswith("Lightning Bolt.jpg")
    assert db.query(models.ScryfallCard).count() == 4
    assert session.get.call_count == 4
