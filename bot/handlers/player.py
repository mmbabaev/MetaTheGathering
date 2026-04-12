# Регистрация, выбор колоды — чистая бизнес-логика

from sqlalchemy.orm import Session

from services.tournament import TournamentService
from services import errors
from services.utils import get_tournament
from bot.handlers.base import HandlerResult
from bot.keyboards import (
    tournament_list_keyboard,
    register_button,
    archetype_keyboard,
)
from bot.messages import (
    NO_ACTIVE_TOURNAMENTS,
    CHOOSE_ARCHETYPE,
    REGISTERED_AS,
    REGISTERED,
    ALREADY_REGISTERED,
    REGISTRATION_CLOSED,
    TOURNAMENT_NOT_FOUND,
    NAME_REQUIRED_FOR_REGISTRATION,
    format_tournament_card,
)


def handle_tournaments(db: Session) -> HandlerResult:
    svc = TournamentService(db)
    tournaments = svc.list_all_active_tournaments()
    if not tournaments:
        return HandlerResult(NO_ACTIVE_TOURNAMENTS)
    if len(tournaments) == 1:
        t = tournaments[0]
        text = format_tournament_card(t.title, t.status.label_ru, t.slug)
        return HandlerResult(text, keyboard=register_button(t.id))
    tour_list = [(t.id, t.title) for t in tournaments]
    return HandlerResult("Выберите турнир:", keyboard=tournament_list_keyboard(tour_list))


def handle_tournament_select(db: Session, tournament_id: int) -> HandlerResult:
    try:
        t = get_tournament(db, tournament_id)
    except errors.TournamentNotFound:
        return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
    text = format_tournament_card(t.title, t.status.label_ru, t.slug)
    return HandlerResult(text, keyboard=register_button(tournament_id))


def handle_register(db: Session, tournament_id: int, tg_id: int | None = None) -> HandlerResult:
    """Возвращает выбор архетипа. Если имя не задано — needs_name=True."""
    svc = TournamentService(db)
    if tg_id is not None:
        user = svc.get_user_by_tg_id(tg_id)
        if user is None or not user.first_name:
            return HandlerResult(NAME_REQUIRED_FOR_REGISTRATION, needs_name=True)
        archetypes = svc.list_archetypes_for_user(tg_id)
    else:
        archetypes = svc.list_archetypes()[:10]
    arch_list = [(a.id, a.name) for a in archetypes]
    return HandlerResult(CHOOSE_ARCHETYPE, keyboard=archetype_keyboard(tournament_id, arch_list))


def handle_save_name_then_register(
    db: Session,
    tg_id: int,
    username: str | None,
    name_text: str,
    tournament_id: int,
) -> HandlerResult:
    """Сохраняет имя пользователя и возвращает выбор архетипа."""
    parts = name_text.strip().split(None, 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else None
    svc = TournamentService(db)
    svc.update_user_name(tg_id, first_name, last_name)
    archetypes = svc.list_archetypes_for_user(tg_id)
    arch_list = [(a.id, a.name) for a in archetypes]
    return HandlerResult(CHOOSE_ARCHETYPE, keyboard=archetype_keyboard(tournament_id, arch_list))


def handle_archetype(
    db: Session,
    tg_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    tournament_id: int,
    archetype_id: int,
) -> HandlerResult:
    svc = TournamentService(db)
    try:
        db_user = svc.get_or_create_user(
            tg_id=tg_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        svc.register_participant(
            tournament_id=tournament_id,
            user_id=db_user.id,
            archetype_id=archetype_id,
        )
        archetypes = {a.id: a.name for a in svc.list_archetypes()}
        name = archetypes.get(archetype_id, "?")
        return HandlerResult(REGISTERED_AS.format(archetype_name=name))
    except errors.ParticipantAlreadyRegistered:
        return HandlerResult(ALREADY_REGISTERED, is_alert=True)
    except errors.TournamentInvalidState:
        return HandlerResult(REGISTRATION_CLOSED, is_alert=True)


def handle_custom_archetype_text(
    db: Session,
    tg_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    tournament_id: int,
    name: str,
) -> HandlerResult:
    svc = TournamentService(db)
    try:
        archetype = svc.get_or_create_archetype_by_name(name)
        db_user = svc.get_or_create_user(
            tg_id=tg_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        svc.register_participant(
            tournament_id=tournament_id,
            user_id=db_user.id,
            archetype_id=archetype.id,
        )
        return HandlerResult(REGISTERED)
    except errors.ParticipantAlreadyRegistered:
        return HandlerResult(ALREADY_REGISTERED)
    except errors.TournamentInvalidState:
        return HandlerResult(REGISTRATION_CLOSED)
