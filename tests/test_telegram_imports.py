"""Smoke tests: all bot/telegram/ wrappers must import without errors.

This catches cases like referencing a deleted module (e.g. core.impersonate)
that would crash the bot at runtime even though unit tests pass.
"""


def test_import_player():
    import bot.telegram.player  # noqa: F401


def test_import_admin():
    import bot.telegram.admin  # noqa: F401


def test_import_settings():
    import bot.telegram.settings  # noqa: F401


def test_import_common():
    import bot.telegram.common  # noqa: F401
