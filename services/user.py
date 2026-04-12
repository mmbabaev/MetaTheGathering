# Сервис управления пользователями

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models


class UserService:
    def __init__(self, db: Session) -> None:
        self.db = db

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
