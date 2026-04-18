"""
Режим «притвориться другим пользователем» для администраторов.

Хранится в памяти — сбрасывается при перезапуске. Только для отладки.
"""


class ImpersonationState:
    def __init__(self) -> None:
        self._data: dict[int, int] = {}  # admin_tg_id → target_tg_id

    def set(self, admin_tg_id: int, target_tg_id: int) -> None:
        self._data[admin_tg_id] = target_tg_id

    def clear(self, admin_tg_id: int) -> None:
        self._data.pop(admin_tg_id, None)

    def get_acting_tg_id(self, tg_id: int) -> int:
        """Вернуть tg_id от имени которого действует пользователь."""
        return self._data.get(tg_id, tg_id)

    def is_impersonating(self, tg_id: int) -> bool:
        return tg_id in self._data

    def get_target(self, admin_tg_id: int) -> int | None:
        return self._data.get(admin_tg_id)
