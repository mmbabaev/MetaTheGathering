import pytest

from tests.telegram_e2e.harness import RecordingRequest


def test_recording_transport_rejects_unexpected_recipient():
    request = RecordingRequest(allowed_chat_ids={10_001})

    with pytest.raises(AssertionError, match="unexpected chat_id"):
        request._validate_outbound("sendMessage", {"chat_id": 10_002, "text": "hello"})


def test_recording_transport_enforces_telegram_limits():
    request = RecordingRequest(allowed_chat_ids={10_001})

    with pytest.raises(AssertionError, match="4096"):
        request._validate_outbound("sendMessage", {"chat_id": 10_001, "text": "x" * 4097})

    with pytest.raises(AssertionError, match="64 byte"):
        request._validate_outbound(
            "sendMessage",
            {
                "chat_id": 10_001,
                "reply_markup": {
                    "inline_keyboard": [[{"text": "Too long", "callback_data": "я" * 33}]],
                },
            },
        )
