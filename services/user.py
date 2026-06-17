# Сервис управления пользователями

from typing import Optional

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from core import models
from core.config import settings


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
        """Найти пользователя по tg_id или создать нового. Обновляет username/имя при изменении."""
        user = self.get_by_tg_id(tg_id)
        if user:
            changed = False
            if username is not None and user.username != username:
                user.username = username
                changed = True
            if first_name is not None and not user.first_name:
                user.first_name = first_name
                changed = True
            if last_name is not None and not user.last_name:
                user.last_name = last_name
                changed = True
            if changed:
                self.db.commit()
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
        stmt = select(models.User).where(models.User.username.ilike(username))
        return self.db.execute(stmt).scalar_one_or_none()

    def find_by_name(self, query: str) -> Optional[models.User]:
        """Найти пользователя по имени/фамилии (через _find_user_flexible)."""
        parts = query.strip().split(None, 1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else None
        return self._find_user_flexible(first, last)

    def _find_user_flexible(self, first_name: str, last_name: Optional[str]) -> Optional[models.User]:
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
                select(models.UserDeckHistory.id).where(models.UserDeckHistory.user_id == user.id).limit(1)
            ).scalar_one_or_none()
            if has_history:
                return user

        # Иначе — предпочитаем реального пользователя (положительный tg_id)
        real = [u for u in candidates if u.tg_id > 0]
        return real[0] if real else candidates[0]

    def get_or_create_placeholder(self, *, username: str) -> tuple["models.User", bool]:
        """Найти пользователя по username или создать placeholder с отрицательным tg_id."""
        user = self.get_by_username(username)
        if user:
            return user, False

        min_val = self.db.execute(select(func.min(models.User.tg_id))).scalar()
        placeholder_tg_id = (min_val - 1) if (min_val is not None and min_val < 0) else -1

        user = models.User(tg_id=placeholder_tg_id, username=username)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user, True

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

    def merge_placeholder_by_name(self, real_tg_id: int, first_name: str, last_name: Optional[str]) -> bool:
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
            row[0]
            for row in self.db.execute(
                select(models.Participant.tournament_id).where(models.Participant.user_id == real_user.id)
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

        # If the user entered their name in reversed order, adopt the placeholder's canonical form
        if placeholder.first_name and placeholder.last_name:
            rev_fn = _normalize_name(placeholder.first_name) == _normalize_name(real_user.last_name or "")
            rev_ln = _normalize_name(placeholder.last_name) == _normalize_name(real_user.first_name or "")
            if rev_fn and rev_ln:
                real_user.first_name = placeholder.first_name
                real_user.last_name = placeholder.last_name

        self.db.delete(placeholder)
        self.db.commit()
        return True

    def merge_users_by_id(self, source_id: int, target_id: int, adopt_name: bool = True) -> bool:
        """Перенести Participant и UserDeckHistory от source к target, затем удалить source.

        Если в одном турнире участвуют оба — поля участия СЛИВАЮТСЯ: недостающие у
        target (``final_place``, ``archetype_id``) добираются из участия source, и
        только потом строка source удаляется. Так не теряются разные половины данных
        (у одного дубля колода, у другого место).

        adopt_name=True — скопировать имя source в target (полезно когда source
        содержит каноничную форму имени, например из AetherHub).

        Перенос делается core-level запросами (``UPDATE ... SET user_id``), строки
        source НЕ загружаются как ORM-сущности — иначе каскад связи ``User.participants``
        при ``delete(source)`` затёр бы уже перенесённые участия. Голоса source
        (placeholder'ы не голосуют) каскадно удаляются вместе с ним.

        Возвращает True если слияние выполнено.
        """
        source = self.get_by_id(source_id)
        target = self.get_by_id(target_id)
        if not source or not target or source.id == target.id:
            return False

        # UserDeckHistory: убрать строки source, конфликтующие с target по unique
        # (user_id, archetype_id), затем перенести остальные.
        target_archetypes = {
            row[0]
            for row in self.db.execute(
                select(models.UserDeckHistory.archetype_id).where(models.UserDeckHistory.user_id == target.id)
            ).all()
        }
        if target_archetypes:
            self.db.execute(
                sa_delete(models.UserDeckHistory).where(
                    models.UserDeckHistory.user_id == source.id,
                    models.UserDeckHistory.archetype_id.in_(target_archetypes),
                )
            )
        self.db.execute(
            sa_update(models.UserDeckHistory)
            .where(models.UserDeckHistory.user_id == source.id)
            .values(user_id=target.id)
        )

        # Participants: для общих турниров слить недостающие поля в участие target,
        # затем удалить участие source. Source читаем как КОЛОНКИ (не сущности).
        target_parts = {
            p.tournament_id: p
            for p in self.db.execute(
                select(models.Participant).where(models.Participant.user_id == target.id)
            ).scalars()
        }
        source_rows = self.db.execute(
            select(
                models.Participant.id,
                models.Participant.tournament_id,
                models.Participant.final_place,
                models.Participant.archetype_id,
            ).where(models.Participant.user_id == source.id)
        ).all()
        drop_ids = []
        for part_id, tournament_id, final_place, archetype_id in source_rows:
            tp = target_parts.get(tournament_id)
            if tp is None:
                continue  # перенесётся UPDATE'ом ниже
            if tp.final_place is None and final_place is not None:
                tp.final_place = final_place
            if tp.archetype_id is None and archetype_id is not None:
                tp.archetype_id = archetype_id
            drop_ids.append(part_id)
        if drop_ids:
            self.db.execute(sa_delete(models.Participant).where(models.Participant.id.in_(drop_ids)))
        self.db.execute(
            sa_update(models.Participant).where(models.Participant.user_id == source.id).values(user_id=target.id)
        )

        if adopt_name and source.first_name:
            target.first_name = source.first_name
            target.last_name = source.last_name

        self.db.delete(source)
        self.db.commit()
        return True

    def is_admin(self, tg_id: int) -> bool:
        if tg_id in settings.admin_ids:
            return True
        user = self.get_by_tg_id(tg_id)
        return user is not None and (user.is_admin or user.is_superadmin)

    def is_scorekeeper(self, tg_id: int) -> bool:
        user = self.get_by_tg_id(tg_id)
        return user is not None and bool(user.is_scorekeeper)

    def is_privileged(self, tg_id: int) -> bool:
        """Admin or scorekeeper — can add/edit decks and export."""
        return self.is_admin(tg_id) or self.is_scorekeeper(tg_id)

    def toggle_scorekeeper(self, tg_id: int) -> Optional[bool]:
        """Toggle is_scorekeeper for user by tg_id. Returns new value, or None if user not found."""
        user = self.get_by_tg_id(tg_id)
        if user is None:
            return None
        user.is_scorekeeper = not user.is_scorekeeper
        self.db.commit()
        return bool(user.is_scorekeeper)

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

    def toggle_hide_deck_emoji(self, tg_id: int) -> bool:
        """Инвертирует hide_deck_emoji. Возвращает новое значение флага."""
        user = self.get_by_tg_id(tg_id)
        if not user:
            return False
        user.hide_deck_emoji = not user.hide_deck_emoji
        self.db.commit()
        return user.hide_deck_emoji

    def toggle_notify_opponent_rounds(self, tg_id: int) -> bool:
        """Инвертирует notify_opponent_rounds. Возвращает новое значение флага."""
        user = self.get_by_tg_id(tg_id)
        if not user:
            return False
        user.notify_opponent_rounds = not user.notify_opponent_rounds
        self.db.commit()
        return user.notify_opponent_rounds

    def wants_opponent_notifications(self, tg_id: int) -> bool:
        """True, если пользователь включил уведомления об оппоненте в настройках."""
        user = self.get_by_tg_id(tg_id)
        return bool(user and user.notify_opponent_rounds)

    def toggle_status_by_pairings(self, tg_id: int) -> bool:
        """Инвертирует status_by_pairings. Возвращает новое значение флага."""
        user = self.get_by_tg_id(tg_id)
        if not user:
            return False
        user.status_by_pairings = not user.status_by_pairings
        self.db.commit()
        return user.status_by_pairings

    def wants_status_by_pairings(self, tg_id: int) -> bool:
        """True, если пользователь выбрал отображение статуса попарно по парингам."""
        user = self.get_by_tg_id(tg_id)
        return bool(user and user.status_by_pairings)
