"""
Режим «притвориться пользователем» для администраторов.

Состояние хранится в памяти — сбрасывается при перезапуске бота.
Это нормально: функция нужна только для отладки интерфейса.
"""

_pretending: set[int] = set()


def is_pretending(tg_id: int) -> bool:
    return tg_id in _pretending


def toggle_pretend(tg_id: int) -> bool:
    """Переключает режим. Возвращает новое состояние (True = притворяется)."""
    if tg_id in _pretending:
        _pretending.discard(tg_id)
        return False
    _pretending.add(tg_id)
    return True
