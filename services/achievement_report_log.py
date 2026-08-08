"""Структурированный журнал owner-отчётов ачивок после турнира."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from services.achievements import AppliedResult

LOG_VERSION = 2


def write_achievement_report_log(
    result: AppliedResult,
    messages: list[str],
    directory: str | Path,
    *,
    created_at: datetime | None = None,
) -> Path:
    """Атомарно записать один JSON-файл отчёта и вернуть его путь."""
    timestamp = created_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    log_dir = Path(directory)
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp.strftime("%Y%m%dT%H%M%S.%fZ")
    destination = log_dir / f"tournament-{result.tournament_id}-{stamp}.json"
    temporary = destination.with_suffix(".json.tmp")
    payload = {
        "version": LOG_VERSION,
        "created_at": timestamp.isoformat(),
        "tournament": {
            "id": result.tournament_id,
            "title": result.title,
            "club": result.club,
        },
        "summary": {
            "processing_run_id": result.processing_run_id,
            "status": result.status,
            "granted": len(result.granted),
            "progress_changes": len(result.progress_changes),
            "skipped": len(result.skipped),
            "messages": len(messages),
            "rule_errors": len(result.rule_errors),
        },
        "messages": messages,
        "granted": [
            {
                "user_id": item.user_id,
                "player": item.player,
                "code": item.definition.code,
                "level": item.definition.level,
                "title": item.definition.title_with_level,
                "evidence": item.evidence,
                "progress_value": item.progress_value,
            }
            for item in result.granted
        ],
        "progress_changes": [
            {
                "user_id": item.user_id,
                "player": item.player,
                "code": item.definition.code,
                "next_level": item.definition.level,
                "title": item.definition.title_with_level,
                "previous": item.previous,
                "value": item.value,
                "delta": item.delta,
                "threshold": item.threshold,
                "evidence": item.evidence,
            }
            for item in result.progress_changes
        ],
        "skipped": [
            {
                "user_id": item.user_id,
                "player": item.name,
                "reason": item.reason,
            }
            for item in result.skipped
        ],
        "rule_errors": [
            {
                "code": error.code,
                "error_type": error.error_type,
            }
            for error in result.rule_errors
        ],
    }
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
