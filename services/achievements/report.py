"""Агрегированный отчёт по ачивкам за турнир — одно сообщение на всех игроков.

В теневом режиме получатель один — владелец (docs/achievements.md §6.2), поэтому отчёт
собирается как единый текст: что выдано, у кого сдвинулся прогресс (с причинами из
истории) и кто не попал в зачёт. Если текст не влезает в лимит Telegram, режем его по
секциям на несколько сообщений, а не обрезаем молча.
"""

from __future__ import annotations

from services.achievements.service import AppliedResult

TG_MESSAGE_LIMIT = 4096
_SAFE_LIMIT = 3900  # запас на склейку строк и заголовок продолжения
_SKIPPED_LIMIT = 10  # сколько «не в зачёт» показываем поимённо


def build_report(result: AppliedResult) -> list[str]:
    """Текст отчёта, уже разбитый на сообщения. Пустой список — сообщать нечего."""
    if result.is_empty:
        return []
    return _split(_lines(result))


def _lines(result: AppliedResult) -> list[str]:
    club = f" ({result.club})" if result.club else ""
    head = [
        f"🏅 Ачивки · {result.title}{club}",
        _counters(result),
    ]

    if result.granted:
        head.append("")
        head.append("НОВЫЕ АЧИВКИ")
        for item in result.granted:
            head.append(f"{item.definition.icon} {item.player} — {item.definition.title_with_level}")
            if item.evidence:
                head.append(f"   {item.evidence}")

    if result.progress_changes:
        head.append("")
        head.append("ПРОГРЕСС")
        for change in result.progress_changes:
            delta = f" (+{change.delta})" if change.delta > 0 else f" ({change.delta})"
            head.append(
                f"{change.definition.icon} {change.player} — {change.definition.title_with_level}: "
                f"{change.value}/{change.threshold}{delta}"
            )
            if change.evidence:
                head.append(f"   {change.evidence}")

    if result.skipped:
        head.append("")
        head.append("НЕ В ЗАЧЁТ")
        for skipped in result.skipped[:_SKIPPED_LIMIT]:
            head.append(f"{skipped.name} — {skipped.reason}")
        if len(result.skipped) > _SKIPPED_LIMIT:
            head.append(f"…и ещё {len(result.skipped) - _SKIPPED_LIMIT}")

    return head


def _counters(result: AppliedResult) -> str:
    parts = [f"Выдано {len(result.granted)}", f"прогресс у {len(result.progress_changes)}"]
    if result.skipped:
        parts.append(f"не в зачёт {len(result.skipped)}")
    return " · ".join(parts)


def _split(lines: list[str]) -> list[str]:
    """Склеить строки в сообщения, не разрывая строку пополам."""
    messages: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        addition = len(line) + 1
        if size + addition > _SAFE_LIMIT and current:
            messages.append("\n".join(current).strip())
            current, size = [], 0
        current.append(line)
        size += addition
    if current:
        messages.append("\n".join(current).strip())
    return [m for m in messages if m]
