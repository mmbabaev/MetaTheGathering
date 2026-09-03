"""Pure business/UI logic for the manual tournament-creation wizard."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from bot.handlers.base import HandlerResult
from bot.keyboards import (
    CB_CREATE_WIZARD_ANNOUNCE_TIME,
    CB_CREATE_WIZARD_EVENT_TIME,
    Keyboards,
)
from bot.messages import NOT_ADMIN
from core.clubs import ClubIdentity, club_identities
from services.tournament_creation import InvalidCreationPlan, TournamentCreationPlanService
from services.user import UserService

ANNOUNCE_DAYS = 8
EVENT_DAYS = 15
ANNOUNCE_TIMES = [f"{hour:02d}:{minute:02d}" for hour in range(8, 24) for minute in (0, 30)]
EVENT_TIMES = [f"{hour:02d}:{minute:02d}" for hour in range(8, 24) for minute in (0, 30)]
WEEKDAY_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
WIZARD_EXPIRED = "Сценарий создания устарел. Запустите /create_tournament ещё раз."


class CreateTournamentWizardHandler:
    def __init__(
        self,
        plans: TournamentCreationPlanService,
        users: UserService,
        keyboards: Keyboards,
    ) -> None:
        self.plans = plans
        self.users = users
        self.keyboards = keyboards

    def handle_start(self, tg_id: int) -> HandlerResult:
        if not self.users.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        clubs = [
            (index, f"{identity.title_prefix}{identity.name}")
            for index, identity in enumerate(club_identities())
            if identity.chat_id
        ]
        return HandlerResult(
            "🏆 Создание турнира\n\n1/4. Выберите клуб:",
            keyboard=self.keyboards.create_tournament_club_keyboard(clubs),
        )

    def handle_club(self, tg_id: int, draft: dict, club_index: int, now: datetime | None = None) -> HandlerResult:
        if not self.users.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        identities = club_identities()
        if not (0 <= club_index < len(identities)) or not identities[club_index].chat_id:
            return HandlerResult("Клуб не найден.", is_alert=True)
        identity = identities[club_index]
        draft.clear()
        draft.update({"club_name": identity.name, "step": "announce_date"})
        return self._announce_date_result(identity, now)

    def handle_announce_now(self, tg_id: int, draft: dict, now: datetime | None = None) -> HandlerResult:
        identity = self._authorized_identity(tg_id, draft, expected_step="announce_date")
        if isinstance(identity, HandlerResult):
            return identity
        draft.update({"announce_now": True, "step": "event_date"})
        draft.pop("announce_date", None)
        draft.pop("announce_time", None)
        return self._event_date_result(identity, draft, now)

    def handle_announce_date(
        self, tg_id: int, draft: dict, raw_date: str, now: datetime | None = None
    ) -> HandlerResult:
        identity = self._authorized_identity(tg_id, draft, expected_step="announce_date")
        if isinstance(identity, HandlerResult):
            return identity
        chosen = self._parse_allowed_date(raw_date, identity, now, ANNOUNCE_DAYS)
        if chosen is None:
            return HandlerResult("Эта дата больше недоступна.", is_alert=True)
        draft.update({"announce_now": False, "announce_date": chosen.isoformat(), "step": "announce_time"})
        return self._announce_time_result(identity, chosen)

    def handle_announce_time(
        self, tg_id: int, draft: dict, raw_time: str, now: datetime | None = None
    ) -> HandlerResult:
        identity = self._authorized_identity(tg_id, draft, expected_step="announce_time")
        if isinstance(identity, HandlerResult):
            return identity
        chosen = self._parse_time(raw_time)
        if chosen not in ANNOUNCE_TIMES:
            return HandlerResult("Время не найдено.", is_alert=True)
        draft.update({"announce_time": chosen, "step": "event_date"})
        return self._event_date_result(identity, draft, now)

    def handle_event_date(self, tg_id: int, draft: dict, raw_date: str, now: datetime | None = None) -> HandlerResult:
        identity = self._authorized_identity(tg_id, draft, expected_step="event_date")
        if isinstance(identity, HandlerResult):
            return identity
        chosen = self._parse_allowed_date(raw_date, identity, now, EVENT_DAYS)
        if chosen is None:
            return HandlerResult("Эта дата больше недоступна.", is_alert=True)
        announce_date = date.fromisoformat(draft["announce_date"]) if not draft.get("announce_now") else None
        if announce_date is not None and chosen < announce_date:
            return HandlerResult("Турнир не может быть раньше публикации регистрации.", is_alert=True)
        draft.update({"event_date": chosen.isoformat(), "step": "event_time"})
        return self._event_time_result(identity, chosen)

    def handle_event_time(self, tg_id: int, draft: dict, raw_time: str, now: datetime | None = None) -> HandlerResult:
        identity = self._authorized_identity(tg_id, draft, expected_step="event_time")
        if isinstance(identity, HandlerResult):
            return identity
        chosen = self._parse_time(raw_time)
        if chosen not in EVENT_TIMES:
            return HandlerResult("Время не найдено.", is_alert=True)
        draft.update({"event_time": chosen, "step": "confirm"})
        error = self._validate_datetimes(identity, draft, now)
        if error:
            draft["step"] = "event_time"
            return HandlerResult(
                error, keyboard=self._event_time_result(identity, date.fromisoformat(draft["event_date"])).keyboard
            )
        return self._confirmation_result(identity, draft)

    def handle_back(self, tg_id: int, draft: dict, target: str, now: datetime | None = None) -> HandlerResult:
        if target == "club":
            draft.clear()
            return self.handle_start(tg_id)
        identity = self._authorized_identity(tg_id, draft)
        if isinstance(identity, HandlerResult):
            return identity
        if target == "ad":
            draft["step"] = "announce_date"
            return self._announce_date_result(identity, now)
        if target == "at" and draft.get("announce_date"):
            draft["step"] = "announce_time"
            return self._announce_time_result(identity, date.fromisoformat(draft["announce_date"]))
        if target == "ed":
            draft["step"] = "event_date"
            return self._event_date_result(identity, draft, now)
        if target == "et" and draft.get("event_date"):
            draft["step"] = "event_time"
            return self._event_time_result(identity, date.fromisoformat(draft["event_date"]))
        return HandlerResult(WIZARD_EXPIRED, is_alert=True)

    def handle_confirm(self, tg_id: int, draft: dict, now: datetime | None = None) -> HandlerResult:
        identity = self._authorized_identity(tg_id, draft, expected_step="confirm")
        if isinstance(identity, HandlerResult):
            return identity
        error = self._validate_datetimes(identity, draft, now)
        if error:
            return HandlerResult(error, is_alert=True)
        announce_at, event_at = self._utc_datetimes(identity, draft, now)
        try:
            plan = self.plans.create_plan(
                club_name=identity.name,
                created_by_tg_id=tg_id,
                announce_at=announce_at,
                event_at=event_at,
            )
        except InvalidCreationPlan as exc:
            return HandlerResult(str(exc), is_alert=True)
        draft.clear()
        local_announce = announce_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(identity.timezone))
        local_event = event_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(identity.timezone))
        when = (
            "сейчас"
            if announce_at <= self._now_utc_naive(now) + timedelta(minutes=1)
            else local_announce.strftime("%d.%m.%Y в %H:%M")
        )
        return HandlerResult(
            f"✅ Создание турнира запланировано.\n\n"
            f"Клуб: {identity.name}\n"
            f"Публикация: {when}\n"
            f"Турнир: {local_event.strftime('%d.%m.%Y в %H:%M')}",
            creation_plan_id=plan.id,
        )

    def _announce_date_result(self, identity: ClubIdentity, now: datetime | None) -> HandlerResult:
        dates = self._date_options(identity, now, ANNOUNCE_DAYS)
        return HandlerResult(
            f"{self._creation_icon(identity)} {identity.title_prefix}{identity.name}\n\n"
            "2/4. Когда создать турнир и отправить объявление в чат?",
            keyboard=self.keyboards.create_tournament_announce_date_keyboard(dates),
        )

    def _announce_time_result(self, identity: ClubIdentity, chosen: date) -> HandlerResult:
        return HandlerResult(
            f"{self._creation_icon(identity)} {identity.name}\n"
            f"Публикация: {self._date_label(chosen)}\n\nВыберите время публикации:",
            keyboard=self.keyboards.create_tournament_time_keyboard(
                ANNOUNCE_TIMES,
                callback_prefix=CB_CREATE_WIZARD_ANNOUNCE_TIME,
                back_target="ad",
            ),
        )

    def _event_date_result(self, identity: ClubIdentity, draft: dict, now: datetime | None) -> HandlerResult:
        back = "ad" if draft.get("announce_now") else "at"
        return HandlerResult(
            f"{self._creation_icon(identity)} {identity.name}\n\n3/4. В какой день пройдёт турнир?",
            keyboard=self.keyboards.create_tournament_date_keyboard(
                self._date_options(identity, now, EVENT_DAYS), back_target=back
            ),
        )

    def _event_time_result(self, identity: ClubIdentity, chosen: date) -> HandlerResult:
        return HandlerResult(
            f"{self._creation_icon(identity)} {identity.name}\n"
            f"Дата турнира: {self._date_label(chosen)}\n\n4/4. Во сколько начало?",
            keyboard=self.keyboards.create_tournament_time_keyboard(
                EVENT_TIMES,
                callback_prefix=CB_CREATE_WIZARD_EVENT_TIME,
                back_target="ed",
            ),
        )

    def _confirmation_result(self, identity: ClubIdentity, draft: dict) -> HandlerResult:
        publication = (
            "сразу после подтверждения"
            if draft.get("announce_now")
            else f"{self._date_label(date.fromisoformat(draft['announce_date']))} в {draft['announce_time']}"
        )
        event_date = date.fromisoformat(draft["event_date"])
        text = (
            "Проверьте создание турнира:\n\n"
            f"Клуб: {identity.title_prefix}{identity.name}\n"
            f"Объявление в чат: {publication}\n"
            f"Чат для объявления: {identity.chat_url or f'Telegram ID {identity.chat_id}'}\n"
            f"Турнир: {self._date_label(event_date)} в {draft['event_time']}\n"
            f"Часовой пояс: {identity.timezone}"
        )
        return HandlerResult(text, keyboard=self.keyboards.create_tournament_confirm_keyboard())

    def _authorized_identity(
        self, tg_id: int, draft: dict, expected_step: str | None = None
    ) -> ClubIdentity | HandlerResult:
        if not self.users.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        if expected_step is not None and draft.get("step") != expected_step:
            return HandlerResult(WIZARD_EXPIRED, is_alert=True)
        name = draft.get("club_name")
        identity = next((row for row in club_identities() if row.name == name and row.chat_id), None)
        return identity or HandlerResult(WIZARD_EXPIRED, is_alert=True)

    def _date_options(self, identity: ClubIdentity, now: datetime | None, days: int) -> list[tuple[str, str]]:
        today = self._now_local(identity, now).date()
        return [
            ((today + timedelta(days=offset)).strftime("%Y%m%d"), self._date_label(today + timedelta(days=offset)))
            for offset in range(days)
        ]

    def _parse_allowed_date(self, raw: str, identity: ClubIdentity, now: datetime | None, days: int) -> date | None:
        try:
            chosen = datetime.strptime(raw, "%Y%m%d").date()
        except ValueError:
            return None
        today = self._now_local(identity, now).date()
        return chosen if today <= chosen < today + timedelta(days=days) else None

    def _utc_datetimes(self, identity: ClubIdentity, draft: dict, now: datetime | None) -> tuple[datetime, datetime]:
        tz = ZoneInfo(identity.timezone)
        now_utc = self._now_utc_naive(now)
        if draft.get("announce_now"):
            announce_at = now_utc
        else:
            announce_local = datetime.combine(
                date.fromisoformat(draft["announce_date"]), time.fromisoformat(draft["announce_time"]), tz
            )
            announce_at = announce_local.astimezone(timezone.utc).replace(tzinfo=None)
        event_local = datetime.combine(
            date.fromisoformat(draft["event_date"]), time.fromisoformat(draft["event_time"]), tz
        )
        event_at = event_local.astimezone(timezone.utc).replace(tzinfo=None)
        return announce_at, event_at

    def _validate_datetimes(self, identity: ClubIdentity, draft: dict, now: datetime | None) -> str | None:
        try:
            announce_at, event_at = self._utc_datetimes(identity, draft, now)
        except (KeyError, ValueError):
            return WIZARD_EXPIRED
        now_utc = self._now_utc_naive(now)
        if announce_at < now_utc - timedelta(minutes=1):
            return "Время публикации уже прошло. Выберите другое время."
        if event_at <= now_utc:
            return "Время турнира уже прошло. Выберите другое время."
        if event_at <= announce_at:
            return "Турнир должен начаться после публикации регистрации."
        return None

    @staticmethod
    def _parse_time(raw: str) -> str:
        if len(raw) != 4 or not raw.isascii() or not raw.isdigit():
            return ""
        return f"{raw[:2]}:{raw[2:]}"

    @staticmethod
    def _date_label(value: date) -> str:
        return f"{WEEKDAY_SHORT[value.weekday()]}, {value.strftime('%d.%m.%Y')}"

    @staticmethod
    def _creation_icon(identity: ClubIdentity) -> str:
        return "🎮" if identity.is_online else "🏆"

    @staticmethod
    def _now_utc_naive(now: datetime | None) -> datetime:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            return current
        return current.astimezone(timezone.utc).replace(tzinfo=None)

    def _now_local(self, identity: ClubIdentity, now: datetime | None) -> datetime:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(ZoneInfo(identity.timezone))
