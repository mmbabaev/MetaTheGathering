# Сервис управления пользователями

from typing import Optional

from sqlalchemy import select, func, update as sa_update, delete as sa_delete
from sqlalchemy.orm import Session

from core import models


def _normalize_name(s: str) -> str:
    """Нижний регистр + ё→е для сравнения имён."""
    return s.strip().lower().replace("ё", "е")


class UserService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: int) -> Optional[models.User]:
        """Вернуть пользователя по внутреннему id или None."""
        stmt = select(models.User).where(models.User.id == user_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_tg_id(self, tg_id: int) -> Optional[models.User]:
        """Вернуть пользователя по tg_id или None."""
        stmt = select(models.User).where(models.User.tg_id == tg_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_or_create(
        self,
        *,
        tg_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> models.User:
        """Найти пользователя по tg_id или создать нового."""
        user = self.get_by_tg_id(tg_id)
        if user:
            return user
        user = models.User(
            tg_id=tg_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_by_username(self, username: str) -> Optional[models.User]:
        """Найти пользователя по Telegram username (без @, без учёта регистра)."""
        stmt = select(models.User).where(
            models.User.username.ilike(username)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def find_by_name(self, query: str) -> Optional[models.User]:
        """Найти пользователя по имени/фамилии (через _find_user_flexible)."""
        parts = query.strip().split(None, 1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else None
        return self._find_user_flexible(first, last)

    def _find_user_flexible(
        self, first_name: str, last_name: Optional[str]
    ) -> Optional[models.User]:
        """Гибкий поиск пользователя по имени:
        — регистронезависимый
        — нормализует ё→е
        — пробует оба порядка (Имя Фамилия / Фамилия Имя)
        — при нескольких совпадениях предпочитает того, у кого есть история колод

        Работает на Python-уровне (fetches all users). Допустимо при небольшом
        числе пользователей (~500).
        """
        fn = _normalize_name(first_name)
        ln = _normalize_name(last_name) if last_name else None

        all_users = self.db.execute(select(models.User)).scalars().all()

        candidates: list[models.User] = []
        for user in all_users:
            ufn = _normalize_name(user.first_name or "")
            uln = _normalize_name(user.last_name or "")

            # Прямой порядок: first_name совпадает с first_name
            direct = (ufn == fn) and (uln == (ln or ""))
            # Обратный порядок: ввели «Имя Фамилия», а в БД «Фамилия Имя»
            swapped = ln is not None and (ufn == ln) and (uln == fn)

            if direct or swapped:
                candidates.append(user)

        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        # Несколько совпадений — предпочитаем того, у кого есть история колод
        for user in candidates:
            has_history = self.db.execute(
                select(models.UserDeckHistory.id)
                .where(models.UserDeckHistory.user_id == user.id)
                .limit(1)
            ).scalar_one_or_none()
            if has_history:
                return user

        # Иначе — предпочитаем реального пользователя (положительный tg_id)
        real = [u for u in candidates if u.tg_id > 0]
        return real[0] if real else candidates[0]

    def get_or_create_by_name(
        self,
        first_name: str,
        last_name: Optional[str] = None,
    ) -> tuple[models.User, bool]:
        """Найти пользователя по имени или создать с placeholder tg_id.

        Поиск: регистронезависимый + ё/е нормализация + оба порядка слов.
        При нескольких совпадениях предпочитает пользователя с историей колод.

        Возвращает (user, was_created).
        Использует flush() без commit() — вызывающий код должен сделать commit.
        """
        first_name = first_name.strip()
        last_name = last_name.strip() if last_name else None

        user = self._find_user_flexible(first_name, last_name)
        if user:
            return user, False

        min_val = self.db.execute(select(func.min(models.User.tg_id))).scalar()
        placeholder_tg_id = (min_val - 1) if (min_val is not None and min_val < 0) else -1

        user = models.User(
            tg_id=placeholder_tg_id,
            first_name=first_name,
            last_name=last_name,
        )
        self.db.add(user)
        self.db.flush()
        return user, True

    def merge_placeholder_by_name(
        self, real_tg_id: int, first_name: str, last_name: Optional[str]
    ) -> bool:
        """Привязывает реального пользователя к существующему placeholder-юзеру по имени.

        Когда реальный tg-пользователь впервые вводит своё имя, ищем placeholder
        (tg_id < 0) с таким же именем. Если находим — переносим ему UserDeckHistory
        и Participant-записи, placeholder удаляем.
        Возвращает True если слияние произошло.
        """
        real_user = self.get_by_tg_id(real_tg_id)
        if not real_user:
            return False

        placeholder = self._find_user_flexible(first_name, last_name)
        if not placeholder or placeholder.tg_id >= 0 or placeholder.id == real_user.id:
            return False

        # Переносим историю колод
        self.db.execute(
            sa_update(models.UserDeckHistory)
            .where(models.UserDeckHistory.user_id == placeholder.id)
            .values(user_id=real_user.id)
        )

        # Переносим участие в турнирах, пропуская конфликты (тот же турнир)
        already_in = {
            row[0] for row in self.db.execute(
                select(models.Participant.tournament_id)
                .where(models.Participant.user_id == real_user.id)
            ).all()
        }
        if already_in:
            self.db.execute(
                sa_delete(models.Participant).where(
                    models.Participant.user_id == placeholder.id,
                    models.Participant.tournament_id.in_(already_in),
                )
            )
        self.db.execute(
            sa_update(models.Participant)
            .where(models.Participant.user_id == placeholder.id)
            .values(user_id=real_user.id)
        )

        self.db.delete(placeholder)
        self.db.commit()
        return True

    def update_name(
        self,
        tg_id: int,
        first_name: str,
        last_name: Optional[str] = None,
    ) -> models.User:
        """Обновить имя пользователя. Создаёт запись если не существует."""
        user = self.get_by_tg_id(tg_id)
        if not user:
            user = models.User(tg_id=tg_id)
            self.db.add(user)
        user.first_name = first_name.strip()
        user.last_name = last_name.strip() if last_name else None
        self.db.commit()
        self.db.refresh(user)
        return user
