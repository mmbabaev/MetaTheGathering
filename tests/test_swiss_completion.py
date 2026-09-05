from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.chart import RenderedChart, RenderedImage
from bot.swiss_completion import publish_swiss_completion
from core import models
from core.schemas import TournamentCreate
from services.tournament import TournamentService


def _standing(index: int):
    return SimpleNamespace(
        place=index,
        username=f"player{index}",
        display_name=f"Игрок {index}",
        match_points=3,
        record="1–0–0",
        opponents_match_win_percentage=1 / 3,
        game_win_percentage=2 / 3,
        opponents_game_win_percentage=1 / 3,
        byes=0,
        dropped=index > 30,
    )


async def test_publishes_all_text_pages_and_meta_images_only_to_tournament_chat(db):
    created = TournamentService(db).create_tournament(
        TournamentCreate(title="Endstep Swiss", chat_id=-100500, club="Endstep-ru", is_online=True)
    )
    tournament = db.get(models.Tournament, created.id)
    tournament.engine_mode = models.TournamentEngineMode.INTERNAL_SWISS
    tournament.status = models.TournamentStatus.CLOSED
    tournament.swiss_rounds = 4
    db.commit()
    standings = [_standing(index) for index in range(1, 36)]
    chart = RenderedChart(png=b"chart", filename="chart.png", sectors=[])
    standings_images = [
        RenderedImage(png=b"standings-1", filename="standings_1.png"),
        RenderedImage(png=b"standings-2", filename="standings_2.png"),
    ]
    bot = AsyncMock()

    with (
        patch("bot.swiss_completion.InternalSwissService.standings", return_value=standings),
        patch("bot.swiss_completion.build_chart", AsyncMock(return_value=chart)),
        patch("bot.swiss_completion.build_standings", AsyncMock(return_value=standings_images)),
    ):
        delivered = await publish_swiss_completion(bot, db, tournament.id)

    assert delivered is True
    assert bot.send_message.await_count == 2
    assert {call.kwargs["chat_id"] for call in bot.send_message.await_args_list} == {-100500}
    assert "Страница 1/2" in bot.send_message.await_args_list[0].kwargs["text"]
    assert "Страница 2/2" in bot.send_message.await_args_list[1].kwargs["text"]
    assert "@player35" in bot.send_message.await_args_list[1].kwargs["text"]
    assert "⛔ дроп" in bot.send_message.await_args_list[1].kwargs["text"]
    bot.send_media_group.assert_awaited_once()
    assert bot.send_media_group.await_args.kwargs["chat_id"] == -100500
    assert len(bot.send_media_group.await_args.kwargs["media"]) == 3


async def test_text_failure_does_not_attempt_images_or_raise(db):
    created = TournamentService(db).create_tournament(
        TournamentCreate(title="Endstep Swiss", chat_id=-100500, club="Endstep-ru", is_online=True)
    )
    tournament = db.get(models.Tournament, created.id)
    tournament.engine_mode = models.TournamentEngineMode.INTERNAL_SWISS
    tournament.status = models.TournamentStatus.CLOSED
    tournament.swiss_rounds = 4
    db.commit()
    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError("Telegram unavailable")

    with (
        patch("bot.swiss_completion.InternalSwissService.standings", return_value=[_standing(1)]),
        patch("bot.swiss_completion.build_chart", AsyncMock()) as build_chart,
        patch("bot.swiss_completion.build_standings", AsyncMock()) as build_standings,
    ):
        delivered = await publish_swiss_completion(bot, db, tournament.id)

    assert delivered is False
    build_chart.assert_not_awaited()
    build_standings.assert_not_awaited()
    bot.send_media_group.assert_not_awaited()
    bot.send_photo.assert_not_awaited()
