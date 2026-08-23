from dataclasses import dataclass
from datetime import date
from urllib.parse import urlencode

from bot.handlers.base import HandlerResult
from bot.keyboards import cellar_cancel_keyboard, cellar_catalog_keyboard, cellar_dates_keyboard, cellar_deck_keyboard
from bot.messages import (
    CELLAR_CANCELLED,
    CELLAR_DATES,
    CELLAR_RESERVED,
    CELLAR_UNAVAILABLE,
    CELLAR_USER_NOT_FOUND,
    format_cellar_cancel_prompt,
    format_cellar_catalog,
    format_cellar_deck,
)
from core import models
from core.config import settings
from services.cellar import (
    CellarReservationError,
    CellarService,
    can_view_cellar_overview,
    format_coordinator_overview,
    next_cellar_dates,
)
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.user import UserService
from services.web_auth import create_magic_token


@dataclass(frozen=True)
class CellarActionResult:
    result: HandlerResult
    reservation: models.CellarDeckReservation | None = None
    cancelled: bool = False


class CellarHandler:
    def __init__(self, db, user_svc: UserService, feature_flags: FeatureFlagService) -> None:
        self.db = db
        self.user_svc = user_svc
        self.feature_flags = feature_flags
        self.cellar = CellarService(db)

    def handle_open(
        self,
        *,
        tg_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        today: date | None = None,
    ) -> HandlerResult:
        if not self._enabled():
            return HandlerResult(CELLAR_UNAVAILABLE)

        user = self.user_svc.get_or_create(
            tg_id=tg_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        dates = next_cellar_dates(today)
        if not self.cellar.catalog(dates[0]):
            self.cellar.ensure_bootstrap_catalog()
        token = create_magic_token(self.db, user)
        query = urlencode({"token": token, "next": "/cellar"})
        web_url = f"{settings.WEB_BASE_URL.rstrip('/')}/auth/verify?{query}"
        text = CELLAR_DATES
        if can_view_cellar_overview(tg_id, username):
            reservations_by_date = [(event_date, self.cellar.active_reservations(event_date)) for event_date in dates]
            text = f"{text}\n\n{format_coordinator_overview(reservations_by_date)}"
        return HandlerResult(text, keyboard=cellar_dates_keyboard(dates, web_url))

    def handle_date(self, *, tg_id: int, event_date: date, page: int = 0, today: date | None = None) -> HandlerResult:
        guard = self._guard_callback(tg_id, event_date=event_date, today=today)
        if guard is not None:
            return guard
        user = self.user_svc.get_by_tg_id(tg_id)
        decks = self.cellar.catalog_for_user(event_date, user.id)
        return HandlerResult(
            format_cellar_catalog(event_date, decks, user.id),
            keyboard=cellar_catalog_keyboard(decks, event_date=event_date, user_id=user.id, page=page),
        )

    def handle_deck(
        self,
        *,
        tg_id: int,
        event_date: date,
        deck_id: int,
        page: int = 0,
        today: date | None = None,
    ) -> HandlerResult:
        guard = self._guard_callback(tg_id, event_date=event_date, today=today)
        if guard is not None:
            return guard
        user = self.user_svc.get_by_tg_id(tg_id)
        decks = self.cellar.catalog_for_user(event_date, user.id)
        deck = next((row for row in decks if row.id == deck_id), None)
        if deck is None:
            return HandlerResult("Колода не найдена.", is_alert=True)
        reservation = self.cellar.reservation_for(deck, event_date)
        my_reservation = next(
            (
                active
                for candidate in decks
                if (active := self.cellar.reservation_for(candidate, event_date)) is not None
                and active.user_id == user.id
            ),
            None,
        )
        can_reserve = deck.available and reservation is None and my_reservation is None
        own_reservation_id = reservation.id if reservation is not None and reservation.user_id == user.id else None
        return HandlerResult(
            format_cellar_deck(deck, reservation, user.id, my_reservation is not None and own_reservation_id is None),
            keyboard=cellar_deck_keyboard(
                deck_id=deck.id,
                event_date=event_date,
                page=page,
                decklist_url=deck.decklist_url,
                can_reserve=can_reserve,
                own_reservation_id=own_reservation_id,
            ),
        )

    def handle_reserve(
        self,
        *,
        tg_id: int,
        event_date: date,
        deck_id: int,
        page: int = 0,
        today: date | None = None,
    ) -> CellarActionResult:
        guard = self._guard_callback(tg_id, event_date=event_date, today=today)
        if guard is not None:
            return CellarActionResult(guard)
        user = self.user_svc.get_by_tg_id(tg_id)
        try:
            outcome = self.cellar.reserve(
                deck_id=deck_id,
                user_id=user.id,
                event_date=event_date,
                today=today,
            )
        except CellarReservationError as exc:
            return CellarActionResult(HandlerResult(str(exc), is_alert=True))
        result = self.handle_date(tg_id=tg_id, event_date=event_date, page=0, today=today)
        result.answer_text = CELLAR_RESERVED if outcome.created else "Эта колода уже забронирована вами."
        return CellarActionResult(result, reservation=outcome.reservation if outcome.created else None)

    def handle_cancel_prompt(self, *, tg_id: int, reservation_id: int, page: int = 0) -> HandlerResult:
        guard = self._guard_callback(tg_id)
        if guard is not None:
            return guard
        user = self.user_svc.get_by_tg_id(tg_id)
        reservation = self.db.get(models.CellarDeckReservation, reservation_id)
        if reservation is None or reservation.user_id != user.id or reservation.cancelled_at is not None:
            return HandlerResult("Активная бронь не найдена.", is_alert=True)
        return HandlerResult(
            format_cellar_cancel_prompt(reservation),
            keyboard=cellar_cancel_keyboard(
                reservation.id,
                reservation.event_date,
                reservation.deck_id,
                page,
            ),
        )

    def handle_cancel(
        self,
        *,
        tg_id: int,
        reservation_id: int,
        page: int = 0,
        today: date | None = None,
    ) -> CellarActionResult:
        guard = self._guard_callback(tg_id)
        if guard is not None:
            return CellarActionResult(guard)
        user = self.user_svc.get_by_tg_id(tg_id)
        try:
            reservation = self.cellar.cancel(reservation_id=reservation_id, user_id=user.id)
        except CellarReservationError as exc:
            return CellarActionResult(HandlerResult(str(exc), is_alert=True))
        result = self.handle_date(
            tg_id=tg_id,
            event_date=reservation.event_date,
            page=page,
            today=today,
        )
        result.answer_text = CELLAR_CANCELLED
        return CellarActionResult(result, reservation=reservation, cancelled=True)

    def _enabled(self) -> bool:
        return self.feature_flags.is_enabled(FeatureFlags.CELLAR_DECKS)

    def _guard_callback(
        self,
        tg_id: int,
        *,
        event_date: date | None = None,
        today: date | None = None,
    ) -> HandlerResult | None:
        if not self._enabled():
            return HandlerResult(CELLAR_UNAVAILABLE, is_alert=True)
        if self.user_svc.get_by_tg_id(tg_id) is None:
            return HandlerResult(CELLAR_USER_NOT_FOUND, is_alert=True)
        if event_date is not None and event_date not in next_cellar_dates(today):
            return HandlerResult("Эта дата больше недоступна для бронирования.", is_alert=True)
        return None
