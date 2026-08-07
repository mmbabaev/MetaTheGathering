"""Структурированный файловый журнал owner-отчётов ачивок."""

import json
from datetime import datetime, timezone

from services.achievement_report_log import write_achievement_report_log
from services.achievements.context import SkippedPlayer
from services.achievements.definitions import Codes, get
from services.achievements.service import AppliedResult, GrantedAchievement, ProgressChange


def test_log_contains_every_section_needed_for_database_audit(tmp_path):
    granted_definition = get(Codes.DEBUT, 1)
    progress_definition = get(Codes.UNDEFEATED, 2)
    assert granted_definition is not None
    assert progress_definition is not None
    result = AppliedResult(
        tournament_id=65,
        title="Edinorog Pauper",
        club="Edinorog",
        granted=[
            GrantedAchievement(
                user_id=11,
                player="Игрок Один",
                definition=granted_definition,
                evidence="первая своя колода",
                progress_value=None,
            )
        ],
        progress_changes=[
            ProgressChange(
                user_id=12,
                player="Игрок Два",
                definition=progress_definition,
                value=2,
                previous=1,
                threshold=3,
                evidence="два турнира без поражений",
            )
        ],
        skipped=[SkippedPlayer(user_id=13, name="Игрок Три", reason="колоду записал не он")],
    )
    created_at = datetime(2026, 8, 7, 12, 34, 56, 123456, tzinfo=timezone.utc)

    path = write_achievement_report_log(
        result,
        ["сообщение владельцу"],
        tmp_path / "logs" / "achievements",
        created_at=created_at,
    )

    assert path.name == "tournament-65-20260807T123456.123456Z.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["tournament"] == {"id": 65, "title": "Edinorog Pauper", "club": "Edinorog"}
    assert payload["messages"] == ["сообщение владельцу"]
    assert payload["granted"][0] == {
        "user_id": 11,
        "player": "Игрок Один",
        "code": Codes.DEBUT,
        "level": 1,
        "title": granted_definition.title_with_level,
        "evidence": "первая своя колода",
        "progress_value": None,
    }
    assert payload["progress_changes"][0] == {
        "user_id": 12,
        "player": "Игрок Два",
        "code": Codes.UNDEFEATED,
        "next_level": 2,
        "title": progress_definition.title_with_level,
        "previous": 1,
        "value": 2,
        "delta": 1,
        "threshold": 3,
        "evidence": "два турнира без поражений",
    }
    assert payload["skipped"] == [
        {"user_id": 13, "player": "Игрок Три", "reason": "колоду записал не он"}
    ]
