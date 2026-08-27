from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from bot.keyboards import CB_TOURNAMENT
from bot.telegram import player
from core.database import Base
from core.schemas import TournamentCreate
from main import build_application
from services.tournament import TournamentService
from tests.telegram_e2e.harness import (
    RecordingRequest,
    callback_data_for_button,
    private_callback_update,
    private_command_update,
)


async def test_tournaments_command_routes_to_card_without_telegram_network(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        tournament = TournamentService(db).create_tournament(
            TournamentCreate(title="E2E Pauper", chat_id=-100_000_001, slug="e2e-pauper")
        )
        TournamentService(db).create_tournament(
            TournamentCreate(title="E2E Pauper Thursday", chat_id=-100_000_002, slug="e2e-pauper-thursday")
        )
        tournament_id = tournament.id

    monkeypatch.setattr(player, "SessionLocal", session_factory)
    monkeypatch.setattr(player, "_log", lambda *_args, **_kwargs: None)

    request = RecordingRequest()
    application = build_application(
        token="0000000000:dummy-not-a-real-key",
        request=request,
        enable_scheduler=False,
        post_init=None,
    )
    await application.initialize()
    try:
        await application.process_update(private_command_update(application.bot, text="/tournaments"))

        sent = request.last_call("sendMessage")
        assert sent.parameters["chat_id"] == 10_001
        assert sent.parameters["text"] == "Выберите турнир:"
        callback_data = callback_data_for_button(sent, "E2E Pauper")
        assert callback_data == f"{CB_TOURNAMENT}:{tournament_id}"
        assert len(callback_data.encode()) <= 64

        await application.process_update(
            private_callback_update(application.bot, data=callback_data, source_message=sent)
        )

        edited = request.last_call("editMessageText")
        assert edited.parameters["chat_id"] == 10_001
        assert edited.parameters["message_id"] == sent.result["message_id"]
        assert "E2E Pauper" in edited.parameters["text"]
        assert request.last_call("answerCallbackQuery").parameters["callback_query_id"] == "callback-2"
        outbound = request.calls_for("sendMessage") + request.calls_for("editMessageText")
        assert {call.parameters.get("chat_id") for call in outbound} == {10_001}
    finally:
        await application.shutdown()
        Base.metadata.drop_all(engine)
        engine.dispose()
