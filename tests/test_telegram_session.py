from unittest.mock import Mock

import pytest

from bot.telegram.session import db_session


def test_db_session_closes_after_successful_block():
    db = Mock()

    with db_session(lambda: db) as actual_db:
        assert actual_db is db

    db.close.assert_called_once_with()


def test_db_session_closes_after_exception():
    db = Mock()

    with pytest.raises(RuntimeError, match="boom"):
        with db_session(lambda: db):
            raise RuntimeError("boom")

    db.close.assert_called_once_with()
