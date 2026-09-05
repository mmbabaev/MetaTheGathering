# Telegram-обёртки для /start и /help

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.deeplink import (
    is_cellar_payload,
    parse_deck_payload,
    parse_fill_missing_payload,
    parse_registration_payload,
    parse_round_payload,
)
from bot.messages import HELP_TEXT, HELP_TEXT_ADMIN
from core.database import SessionLocal
from core.event_log import event_logger
from services.user import UserService

logger = logging.getLogger(__name__)


async def announce_completion_if_ready(bot, db, tournament_id: int | None) -> None:
    """Best-effort проверка «сбор метагейма завершён» после записи колоды.

    Условие внутри идемпотентно и само проверяет все гарды, поэтому зовём после любой
    записи колоды — анонс уходит сразу, как заполнена последняя недостающая колода, не
    дожидаясь следующего импорта AetherHub. Ошибку глушим: действие игрока уже выполнено.
    Ленивый импорт scheduler — он импортит bot.telegram (иначе циклический импорт).
    """
    if tournament_id is None:
        return
    from bot.scheduler import maybe_announce_meta_gather_completed  # noqa: PLC0415

    try:
        await maybe_announce_meta_gather_completed(bot, db, tournament_id)
    except Exception:
        logger.exception("announce_completion_if_ready failed for #%s", tournament_id)


async def parse_callback_ints(query, count: int) -> tuple[int, ...] | None:
    """Парсит callback_data вида 'PREFIX:int1:int2...'. Возвращает кортеж int или None при ошибке."""
    if not query or not query.data:
        return None
    try:
        parts = query.data.split(":", count)
        return tuple(int(p) for p in parts[1 : count + 1])
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.")
        return None


def log_event(event: str, user, **params) -> None:
    event_logger.log(
        event,
        tg_id=user.id if user else None,
        username=user.username if user else None,
        **params,
    )


_log = log_event  # backward-compat alias within this module


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_user:
        return
    user = update.effective_user

    # Диплинк `?start=deck_<id>` — сразу в запись колоды на турнир (issue #136).
    payload = (context.args or [None])[0]
    if payload and is_cellar_payload(payload):
        await _start_cellar_deeplink(update, context)
        return
    tournament_id = parse_deck_payload(payload) if payload else None
    if tournament_id is not None:
        await _start_deck_deeplink(update, context, user, tournament_id)
        return
    tournament_id = parse_registration_payload(payload) if payload else None
    if tournament_id is not None:
        await _start_registration_deeplink(update, context, user, tournament_id)
        return
    tournament_id = parse_round_payload(payload) if payload else None
    if tournament_id is not None:
        await _start_round_deeplink(update, context, user, tournament_id)
        return
    tournament_id = parse_fill_missing_payload(payload) if payload else None
    if tournament_id is not None:
        await _start_fill_missing_deeplink(update, context, user, tournament_id)
        return

    _log("cmd_start", user)
    db = SessionLocal()
    try:
        db_user = UserService(db).get_by_tg_id(user.id)
    finally:
        db.close()

    if db_user and db_user.first_name:
        name_parts = [p for p in [db_user.first_name, db_user.last_name] if p]
        greeting = "Привет, {}! ".format(" ".join(name_parts))
    else:
        greeting = "Привет! "

    await update.effective_message.reply_text(
        greeting + "Используйте /tournaments чтобы увидеть активные турниры и записаться."
    )


async def _start_cellar_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route `?start=cellar` through the same private menu as `/cellar`."""

    from bot.telegram.cellar import cmd_cellar  # noqa: PLC0415 — cellar imports log_event from this module

    await cmd_cellar(update, context)


async def _start_deck_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE, user, tournament_id: int) -> None:
    """Обработка deck-диплинка: нет колоды → выбор архетипа, есть → карточка турнира."""
    # Локальный импорт: bot.telegram.player импортирует common — верхнеуровневый импорт замкнул бы цикл.
    from bot.telegram.player import _player_handler, _set_registration_pending  # noqa: PLC0415

    _log("cmd_start_deeplink", user, tournament_id=tournament_id)
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_deeplink_deck(tournament_id, tg_id=user.id)
        _set_registration_pending(context, result, tournament_id)
        await update.effective_message.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()


async def _start_registration_deeplink(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user, tournament_id: int
) -> None:
    """Обработка общей кнопки регистрации: записанным показывает карточку турнира."""
    from bot.telegram.player import _player_handler, _set_registration_pending  # noqa: PLC0415

    _log("cmd_start_registration_deeplink", user, tournament_id=tournament_id)
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_deeplink_registration(tournament_id, tg_id=user.id)
        _set_registration_pending(context, result, tournament_id)
        await update.effective_message.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()


async def _start_round_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE, user, tournament_id: int) -> None:
    """Open the user's current score flow, falling back to the tournament card."""
    from bot.handlers.round_results import RoundResultsHandler  # noqa: PLC0415
    from bot.telegram.player import _player_handler  # noqa: PLC0415
    from services.round_results import FINAL_STATUSES, RoundResultError, RoundResultsService  # noqa: PLC0415

    _log("cmd_start_round_deeplink", user, tournament_id=tournament_id)
    db = SessionLocal()
    try:
        try:
            match = RoundResultsService(db).current_match_for_user(tournament_id, user.id)
        except RoundResultError:
            match = None
        if match is not None and match.player2_name is not None and match.status not in FINAL_STATUSES:
            result = RoundResultsHandler(db).handle_open(tournament_id, user.id)
        else:
            result = _player_handler(db).handle_tournament_select(tournament_id, tg_id=user.id)
        await update.effective_message.reply_text(
            result.text,
            reply_markup=result.keyboard,
            parse_mode=result.parse_mode,
        )
    finally:
        db.close()


async def _start_fill_missing_deeplink(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user, tournament_id: int
) -> None:
    """Открывает защищённый community-flow из сообщения мета-полиции."""
    from bot.telegram.player import _player_handler  # noqa: PLC0415

    _log("meta_police_open", user, tournament_id=tournament_id)
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_fill_missing_deeplink(tournament_id, tg_id=user.id)
        await update.effective_message.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_user:
        return
    user = update.effective_user
    _log("cmd_help", user)
    db = SessionLocal()
    try:
        is_admin = UserService(db).is_admin(user.id)
    finally:
        db.close()
    text = HELP_TEXT + "\n\n" + HELP_TEXT_ADMIN if is_admin else HELP_TEXT
    await update.effective_message.reply_text(text)
