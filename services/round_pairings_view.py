"""Shared formatter for public and club-chat round pairing views."""

from __future__ import annotations

from collections import Counter
from html import escape

from core.models import RoundMatchStatus
from services.names import format_participant_name


def _round_match_names(matches: list) -> tuple[dict[tuple[int, int], str], dict[tuple[int, int], str]]:
    """Return primary Telegram labels and full ``Фамилия Имя`` labels."""
    compact: dict[tuple[int, int], str] = {}
    full: dict[tuple[int, int], str] = {}
    for match in matches:
        for position, (source_name, user) in enumerate(
            ((match.player1_name, match.player1_user), (match.player2_name, match.player2_user)), start=1
        ):
            if source_name is None:
                continue
            key = (match.id, position)
            if user is not None:
                full[key] = format_participant_name(user.first_name, user.last_name) or source_name
                username = (user.username or "").strip().lstrip("@")
                compact[key] = f"@{username}" if username else user.last_name or user.first_name or source_name
            else:
                compact[key] = source_name
                full[key] = source_name
    counts = Counter(value.casefold() for value in compact.values())
    primary = {key: (full[key] if counts[value.casefold()] > 1 else value) for key, value in compact.items()}
    return primary, full


def format_round_pairings(title: str, status: str, round_number: int, matches: list) -> str:
    """Round status with Telegram handles, real names, scores and explicit states."""
    names, full_names = _round_match_names(matches)
    playable = [match for match in matches if match.player2_name is not None]
    completed = sum(
        match.status in {RoundMatchStatus.CONFIRMED, RoundMatchStatus.ADMIN, RoundMatchStatus.IMPORTED}
        for match in playable
    )
    lines = [
        f"🎮 {escape(title)} · {escape(status)}",
        f"<b>Раунд {round_number} · результаты {completed}/{len(playable)}</b>",
        "",
    ]
    for index, match in enumerate(matches, start=1):
        table = match.table_number if match.table_number is not None else index
        left = escape(names[(match.id, 1)])
        full_left = escape(full_names[(match.id, 1)])
        if match.player2_name is None:
            lines.append(f"{table}. {left} — BYE")
            if full_left != left:
                lines.append(f"   {full_left} — BYE")
            lines.append("   Статус: ✅ без игры")
            continue
        right = escape(names[(match.id, 2)])
        full_right = escape(full_names[(match.id, 2)])
        lines.append(f"{table}. {left} — {right}")
        if (full_left, full_right) != (left, right):
            lines.append(f"   {full_left} — {full_right}")
        if match.player1_wins is None or match.player2_wins is None:
            lines.append("   Счёт: — · Статус: 🎮 играют")
            continue
        status_text = {
            RoundMatchStatus.PENDING: "⏳ ожидает подтверждения",
            RoundMatchStatus.CONFIRMED: "✅ подтверждён",
            RoundMatchStatus.ADMIN: "✅ введён администратором",
            RoundMatchStatus.IMPORTED: "✅ импортирован",
        }.get(match.status, "🎮 играют")
        lines.append(f"   Счёт: <b>{match.player1_wins}–{match.player2_wins}</b> · Статус: {status_text}")
    return "\n".join(lines)
