# Сервис управления пользователями

from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from core import models


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

    def get_or_create_by_name(
        self,
        first_name: str,
        last_name: Optional[str] = None,
    ) -> tuple[models.User, bool]:
        """Найти пользователя по имени или создать с placeholder tg_id.

        Возвращает (user, was_created).
        Использует flush() без commit() — вызывающий код должен сделать commit.
        """
        first_name = first_name.strip()
        last_name = last_name.strip() if last_name else None

        stmt = select(models.User).where(models.User.first_name == first_name)
        if last_name:
            stmt = stmt.where(models.User.last_name == last_name)
        else:
            stmt = stmt.where(models.User.last_name.is_(None))
        user = self.db.execute(stmt).scalar_one_or_none()
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
