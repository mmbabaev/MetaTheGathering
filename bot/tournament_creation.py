"""Execute durable tournament-creation plans and announce registration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select

from bot.registration_messages import send_registration_open
from core import models
from services import errors
from services.tournament_creation import InvalidCreationPlan, TournamentCreationPlanService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreationExecutionResult:
    plan_id: int
    tournament_id: int | None
    announced: bool
    error: str | None = None


async def execute_creation_plan(bot, db, plan_id: int) -> CreationExecutionResult:
    service = TournamentCreationPlanService(db)
    try:
        prepared = service.prepare_tournament(plan_id)
    except (InvalidCreationPlan, errors.TournamentAlreadyExists, errors.TournamentNotFound) as exc:
        service.mark_failed(plan_id, str(exc))
        logger.warning("Tournament creation plan #%s failed: %s", plan_id, exc)
        return CreationExecutionResult(plan_id, None, False, str(exc))
    except Exception as exc:  # noqa: BLE001 — один план не должен остановить очередь
        db.rollback()
        service.mark_failed(plan_id, str(exc))
        logger.exception("Tournament creation plan #%s failed", plan_id)
        return CreationExecutionResult(plan_id, None, False, str(exc))

    event_icon = "🎮" if prepared.club.is_online else "🏆"
    base_text = (
        f"{event_icon} {prepared.club.name} Pauper — {prepared.event_at_local.strftime('%d.%m.%Y')} "
        f"в {prepared.event_at_local.strftime('%H:%M')}\n"
        "Турнир создан. Регистрация открыта."
    )
    already_tracked = db.execute(
        select(models.TournamentRegistrationMessage.id).where(
            models.TournamentRegistrationMessage.tournament_id == prepared.tournament.id,
            models.TournamentRegistrationMessage.chat_id == prepared.club.chat_id,
        )
    ).scalar_one_or_none()
    if already_tracked is not None:
        service.mark_announced(plan_id)
        return CreationExecutionResult(plan_id, prepared.tournament.id, True)
    sent = await send_registration_open(bot, db, prepared.club, prepared.tournament.id, base_text)
    if sent:
        service.mark_announced(plan_id)
        return CreationExecutionResult(plan_id, prepared.tournament.id, True)
    service.record_delivery_error(plan_id, "Не удалось отправить объявление в чат клуба; повторим автоматически.")
    return CreationExecutionResult(
        plan_id,
        prepared.tournament.id,
        False,
        "Не удалось отправить объявление в чат клуба; повторим автоматически.",
    )


async def execute_due_creation_plans(bot, db) -> list[CreationExecutionResult]:
    service = TournamentCreationPlanService(db)
    results = []
    for plan in service.list_due():
        results.append(await execute_creation_plan(bot, db, plan.id))
    return results
