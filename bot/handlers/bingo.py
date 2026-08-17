"""Pure owner/admin handler for deterministic bingo board previews."""

from __future__ import annotations

from dataclasses import dataclass

from bot.handlers.base import HandlerResult
from bot.messages import (
    BINGO_PREVIEW_DISABLED,
    BINGO_PREVIEW_FAILED,
    BINGO_PREVIEW_USAGE,
    NOT_ADMIN,
)
from services.achievements.bingo import (
    FIXTURE_CATALOG_VERSION,
    BoardDraft,
    BoardGenerationError,
    FixturePersona,
    fixture_candidates,
    generate_board,
)
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.user import UserService

MAX_PREVIEW_SEED = 2_147_483_647
PREVIEW_SEASON_ID = "owner-board-lab-preview"

PERSONA_LABELS: dict[FixturePersona, str] = {
    FixturePersona.NEWCOMER: "Новичок",
    FixturePersona.AMATEUR: "Любитель",
    FixturePersona.REGULAR: "Регуляр",
    FixturePersona.PRO: "Про",
}

_PERSONA_ALIASES: dict[str, FixturePersona] = {
    "newcomer": FixturePersona.NEWCOMER,
    "новичок": FixturePersona.NEWCOMER,
    "amateur": FixturePersona.AMATEUR,
    "любитель": FixturePersona.AMATEUR,
    "regular": FixturePersona.REGULAR,
    "регуляр": FixturePersona.REGULAR,
    "pro": FixturePersona.PRO,
    "про": FixturePersona.PRO,
}

_DIFFICULTY_LABELS = {
    "easy": "легко",
    "medium": "средне",
    "hard": "сложно",
    "rare": "редко",
}

_CATEGORY_LABELS = {
    "participation": "участие",
    "performance": "результат",
    "deck": "колоды",
    "exploration": "исследование",
    "social": "сообщество",
    "h2h": "личные встречи",
    "peer_confirmation": "подтверждение оппонента",
}


@dataclass(frozen=True)
class BingoPreview:
    persona: FixturePersona
    seed: int
    draft: BoardDraft

    @property
    def persona_label(self) -> str:
        return PERSONA_LABELS[self.persona]

    @property
    def caption(self) -> str:
        return (
            f"Бинго 4×4 · {self.persona_label} · seed {self.seed}\n"
            f"{self.draft.input.catalog_version} · {self.draft.input.algorithm_version}"
        )


class BingoPreviewHandler:
    def __init__(self, user_svc: UserService, feature_flags: FeatureFlagService) -> None:
        self.user_svc = user_svc
        self.feature_flags = feature_flags

    def preview(self, tg_id: int, args: list[str], *, default_seed: int) -> BingoPreview | HandlerResult:
        """Generate one read-only fixture board for an authorized requester."""

        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        if not self.feature_flags.is_enabled(FeatureFlags.ACHIEVEMENT_BOARD_LAB):
            return HandlerResult(BINGO_PREVIEW_DISABLED)

        parsed = _parse_args(args, default_seed=default_seed)
        if parsed is None:
            return HandlerResult(BINGO_PREVIEW_USAGE)
        persona, seed = parsed

        try:
            draft = generate_board(
                fixture_candidates(persona),
                season_id=PREVIEW_SEASON_ID,
                player_id=f"fixture-{persona.value}",
                seed=seed,
                catalog_version=FIXTURE_CATALOG_VERSION,
            )
        except BoardGenerationError:
            return HandlerResult(BINGO_PREVIEW_FAILED)
        return BingoPreview(persona=persona, seed=seed, draft=draft)


def format_bingo_preview(preview: BingoPreview, *, limit: int = 4096) -> list[str]:
    """Plain-text descriptions of all cells, split only between rows."""

    header = (
        f"Бинго 4×4 · {preview.persona_label} · seed {preview.seed}\n"
        f"Каталог: {preview.draft.input.catalog_version}\n"
        f"Алгоритм: {preview.draft.input.algorithm_version}"
    )
    row_blocks: list[str] = []
    columns = preview.draft.input.constraints.columns
    for row_index in range(preview.draft.input.constraints.rows):
        lines = [f"Ряд {row_index + 1}"]
        for cell in preview.draft.cells[row_index * columns : (row_index + 1) * columns]:
            candidate = cell.candidate
            difficulty = _DIFFICULTY_LABELS[candidate.difficulty.value]
            category = _CATEGORY_LABELS[candidate.category.value]
            lines.append(f"{cell.index + 1}. {candidate.title} · {difficulty}, {category}")
            lines.append(f"   {candidate.hint}")
        row_blocks.append("\n".join(lines))

    rejected = len(preview.draft.diagnostics.rejected_candidates)
    footer = (
        f"Отклонено кандидатов: {rejected}. Preview ничего не записывает в БД.\n"
        f"Повторить: /bingo_preview {preview.persona.value} {preview.seed}"
    )
    return _pack_blocks(header, [*row_blocks, footer], limit=limit)


def _parse_args(args: list[str], *, default_seed: int) -> tuple[FixturePersona, int] | None:
    if not 0 <= default_seed <= MAX_PREVIEW_SEED:
        raise ValueError("default_seed is outside supported range")
    if len(args) > 2:
        return None

    persona = FixturePersona.REGULAR
    seed_text: str | None = None
    if args:
        first = args[0].strip().casefold()
        if first in _PERSONA_ALIASES:
            persona = _PERSONA_ALIASES[first]
            seed_text = args[1].strip() if len(args) == 2 else None
        elif len(args) == 1:
            seed_text = first
        else:
            return None

    seed = default_seed if seed_text is None else _parse_seed(seed_text)
    if seed is None:
        return None
    return persona, seed


def _parse_seed(value: str) -> int | None:
    try:
        seed = int(value)
    except ValueError:
        return None
    return seed if 0 <= seed <= MAX_PREVIEW_SEED else None


def _pack_blocks(header: str, blocks: list[str], *, limit: int) -> list[str]:
    if limit < 1:
        raise ValueError("limit must be positive")
    messages: list[str] = []
    current = header
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            messages.append(current)
        if len(block) > limit:
            raise ValueError("one bingo preview row exceeds message limit")
        current = block
    if current:
        messages.append(current)
    return messages
