"""Pure owner/admin bingo preview command: parsing, authorization and text."""

from bot.handlers.base import HandlerResult
from bot.handlers.bingo import BingoPreview, BingoPreviewHandler, format_bingo_preview
from bot.messages import BINGO_PREVIEW_DISABLED, BINGO_PREVIEW_USAGE, NOT_ADMIN
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.user import UserService


def _handler(db) -> BingoPreviewHandler:
    return BingoPreviewHandler(UserService(db), FeatureFlagService(db))


def _admin(db, user_svc, tg_id: int = 7101):
    user = user_svc.get_or_create(tg_id=tg_id, first_name="Админ")
    user.is_admin = True
    db.commit()
    return user


def test_admin_gets_default_regular_board_with_supplied_seed(db, user_svc):
    admin = _admin(db, user_svc)

    result = _handler(db).preview(admin.tg_id, [], default_seed=123)

    assert isinstance(result, BingoPreview)
    assert result.persona.value == "regular"
    assert result.seed == 123
    assert len(result.draft.cells) == 16


def test_russian_persona_and_explicit_seed_are_reproducible(db, user_svc):
    admin = _admin(db, user_svc)
    handler = _handler(db)

    first = handler.preview(admin.tg_id, ["новичок", "42"], default_seed=1)
    repeated = handler.preview(admin.tg_id, ["newcomer", "42"], default_seed=2)

    assert isinstance(first, BingoPreview)
    assert isinstance(repeated, BingoPreview)
    assert first.persona.value == "newcomer"
    assert first.draft.stable_json() == repeated.draft.stable_json()


def test_seed_without_persona_uses_regular(db, user_svc):
    admin = _admin(db, user_svc)

    result = _handler(db).preview(admin.tg_id, ["777"], default_seed=1)

    assert isinstance(result, BingoPreview)
    assert result.persona.value == "regular"
    assert result.seed == 777


def test_invalid_arguments_return_usage(db, user_svc):
    admin = _admin(db, user_svc)
    handler = _handler(db)

    invalid_persona = handler.preview(admin.tg_id, ["маг", "42"], default_seed=1)
    invalid_seed = handler.preview(admin.tg_id, ["regular", "-1"], default_seed=1)

    assert isinstance(invalid_persona, HandlerResult)
    assert isinstance(invalid_seed, HandlerResult)
    assert invalid_persona.text == BINGO_PREVIEW_USAGE
    assert invalid_seed.text == BINGO_PREVIEW_USAGE


def test_non_admin_is_denied(db, user_svc):
    player = user_svc.get_or_create(tg_id=7102, first_name="Игрок")

    result = _handler(db).preview(player.tg_id, [], default_seed=123)

    assert isinstance(result, HandlerResult)
    assert result.text == NOT_ADMIN


def test_disabled_feature_flag_blocks_admin(db, user_svc):
    admin = _admin(db, user_svc)
    FeatureFlagService(db).toggle(FeatureFlags.ACHIEVEMENT_BOARD_LAB)

    result = _handler(db).preview(admin.tg_id, [], default_seed=123)

    assert isinstance(result, HandlerResult)
    assert result.text == BINGO_PREVIEW_DISABLED


def test_text_contains_all_cells_and_can_split_between_rows(db, user_svc):
    admin = _admin(db, user_svc)
    preview = _handler(db).preview(admin.tg_id, ["pro", "42"], default_seed=1)
    assert isinstance(preview, BingoPreview)

    messages = format_bingo_preview(preview, limit=900)
    text = "\n".join(messages)

    assert len(messages) > 1
    assert all(len(message) <= 900 for message in messages)
    assert all(f"Ряд {row}" in text for row in range(1, 5))
    assert all(cell.candidate.title in text for cell in preview.draft.cells)
    assert all(cell.candidate.hint in text for cell in preview.draft.cells)
    assert "/bingo_preview pro 42" in text
