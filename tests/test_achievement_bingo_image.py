"""Visual contract for the owner bingo board preview."""

import io

from PIL import Image

from services.achievement_bingo_image import BOARD_HEIGHT, BOARD_WIDTH, render_bingo_board
from services.achievements.bingo import FIXTURE_CATALOG_VERSION, FixturePersona, fixture_candidates, generate_board


def _draft():
    return generate_board(
        fixture_candidates(FixturePersona.REGULAR),
        season_id="test-board-lab",
        player_id="fixture-regular",
        seed=42,
        catalog_version=FIXTURE_CATALOG_VERSION,
    )


def test_board_renders_as_nonempty_png():
    payload = render_bingo_board(_draft(), persona_label="Регуляр")

    image = Image.open(io.BytesIO(payload))
    assert image.format == "PNG"
    assert image.size == (BOARD_WIDTH, BOARD_HEIGHT)
    assert len(payload) > 50_000


def test_renderer_is_byte_for_byte_deterministic():
    draft = _draft()

    first = render_bingo_board(draft, persona_label="Регуляр")
    repeated = render_bingo_board(draft, persona_label="Регуляр")

    assert first == repeated
