from unittest.mock import MagicMock

import requests

from services.aetherhub_service import AetherhubService


def test_retries_transient_ssl_eof(monkeypatch):
    """Issue #248: one broken TLS handshake must not abort an AetherHub fetch."""
    scraper = MagicMock()
    response = MagicMock()
    response.text = "<html><body></body></html>"
    scraper.get.side_effect = [
        requests.exceptions.SSLError("[SSL: UNEXPECTED_EOF_WHILE_READING]"),
        response,
    ]
    sleeps = []
    monkeypatch.setattr("services.aetherhub_service.time.sleep", sleeps.append)

    links = AetherhubService(scraper=scraper).fetch_club_tournaments("https://aetherhub.com/User/PairOfDice")

    assert links == []
    assert scraper.get.call_count == 2
    assert sleeps == [0.5]
