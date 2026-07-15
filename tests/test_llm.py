"""Tests for the YandexGPT client (services/llm.py)."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from services.llm import YandexLLM

# Заведомо ненастоящие значения — в тестах не должно быть даже похожего на реальный ключ.
FAKE_API_KEY = "dummy-not-a-real-key"
FAKE_FOLDER_ID = "dummy-folder"


@pytest.fixture
def llm():
    return YandexLLM(api_key=FAKE_API_KEY, folder_id=FAKE_FOLDER_ID, model="yandexgpt-lite/latest")


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class TestEnabled:
    def test_disabled_without_credentials(self):
        assert YandexLLM(api_key="", folder_id="").enabled is False

    def test_disabled_with_only_api_key(self):
        assert YandexLLM(api_key="key", folder_id="").enabled is False

    def test_enabled_with_both(self, llm):
        assert llm.enabled is True

    def test_disabled_client_does_not_call_network(self):
        with patch("services.llm.requests.post") as post:
            assert YandexLLM(api_key="", folder_id="").complete("sys", "user") is None
        post.assert_not_called()


class TestModelUri:
    def test_built_from_folder_and_model(self, llm):
        assert llm.model_uri == f"gpt://{FAKE_FOLDER_ID}/yandexgpt-lite/latest"


class TestComplete:
    def test_returns_text_from_first_alternative(self, llm):
        payload = {"result": {"alternatives": [{"message": {"role": "assistant", "text": '{"colors":"UB"}'}}]}}

        with patch("services.llm.requests.post", return_value=_response(payload)):
            assert llm.complete("sys", "Spy Combo") == '{"colors":"UB"}'

    def test_sends_expected_payload_and_auth(self, llm):
        payload = {"result": {"alternatives": [{"message": {"text": "ok"}}]}}

        with patch("services.llm.requests.post", return_value=_response(payload)) as post:
            llm.complete("system prompt", "user prompt")

        _, kwargs = post.call_args
        assert kwargs["headers"]["Authorization"] == f"Api-Key {FAKE_API_KEY}"
        assert kwargs["headers"]["x-folder-id"] == FAKE_FOLDER_ID
        assert kwargs["json"]["modelUri"] == f"gpt://{FAKE_FOLDER_ID}/yandexgpt-lite/latest"
        assert kwargs["json"]["messages"] == [
            {"role": "system", "text": "system prompt"},
            {"role": "user", "text": "user prompt"},
        ]
        assert kwargs["timeout"] == llm.timeout

    def test_network_error_returns_none(self, llm):
        with patch("services.llm.requests.post", side_effect=requests.RequestException("boom")):
            assert llm.complete("sys", "user") is None

    def test_http_error_returns_none(self, llm):
        response = MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError("401")

        with patch("services.llm.requests.post", return_value=response):
            assert llm.complete("sys", "user") is None

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"result": {}},
            {"result": {"alternatives": []}},
        ],
    )
    def test_empty_answer_returns_none(self, llm, payload):
        with patch("services.llm.requests.post", return_value=_response(payload)):
            assert llm.complete("sys", "user") is None

    def test_alternative_without_message_returns_none(self, llm):
        payload = {"result": {"alternatives": [{"status": "ALTERNATIVE_STATUS_FINAL"}]}}

        with patch("services.llm.requests.post", return_value=_response(payload)):
            assert llm.complete("sys", "user") is None
