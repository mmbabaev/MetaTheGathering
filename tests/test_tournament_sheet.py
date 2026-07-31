from datetime import date, datetime

from openpyxl import Workbook

from services.tournament_sheet import extract_sheet_tournaments


def _workbook(tmp_path):
    workbook = Workbook()
    standings = workbook.active
    standings.title = "Pauper"
    standings.append([" Место", "Участник", "Очки", "Колода", "Клуб", "Турниры"])
    standings.append([1, "Alice", 6, "Deck A", "Goldfish", datetime(2024, 1, 1)])
    standings.append([2, "Bob", 3, "Deck B", "Goldfish", datetime(2024, 1, 1)])
    standings.append([3, "Carol", 0, "Deck C", "Goldfish", datetime(2024, 1, 1)])
    standings.append([4, "Dave", 0, "Deck D", "Goldfish", datetime(2024, 1, 1)])
    history = workbook.create_sheet("Match History")
    history.append(
        ["Дата", "Игрок", " Колода Игрока", "Оппонент", "Колода Оппонента", "Счет Игрока", "Счет Оппонента", "Клуб"]
    )
    matches = [
        ("Alice", "Bob", 2, 0),
        ("Carol", "Dave", 2, 1),
        ("Alice", "Carol", 2, 0),
        ("Bob", "Dave", 2, 1),
    ]
    for player1, player2, result1, result2 in matches:
        history.append([datetime(2024, 1, 1), player1, "", player2, "", result1, result2, "Goldfish"])
        history.append([datetime(2024, 1, 1), player2, "", player1, "", result2, result1, "Goldfish"])
    path = tmp_path / "history.xlsx"
    workbook.save(path)
    return path


def test_extracts_standings_deduplicates_matches_and_infers_rounds(tmp_path):
    tournaments, issues = extract_sheet_tournaments(_workbook(tmp_path), {("Goldfish", date(2024, 1, 1))})

    assert issues == []
    assert len(tournaments) == 1
    tournament = tournaments[0]
    assert tournament.club == "Goldfish"
    assert [row.player for row in tournament.standings] == ["Alice", "Bob", "Carol", "Dave"]
    assert [len(round_.pairings) for round_ in tournament.rounds] == [2, 2]
    assert tournament.rounds[0].pairings[0].model_dump() == {
        "player1": "Alice",
        "player2": "Bob",
        "result1": 2,
        "result2": 0,
    }


def test_reports_target_absent_from_workbook(tmp_path):
    tournaments, issues = extract_sheet_tournaments(_workbook(tmp_path), {("Единорог", date(2024, 2, 1))})

    assert tournaments == []
    assert issues == ["2024-02-01 единорог: нет standings или pairings в таблице"]
