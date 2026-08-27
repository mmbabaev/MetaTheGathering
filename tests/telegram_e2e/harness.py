"""Deterministic Telegram Bot API transport and synthetic Update helpers."""

import json
from dataclasses import dataclass
from typing import Any

from telegram import Bot, Update
from telegram.request import BaseRequest, RequestData

BOT_ID = 7_700_001
BOT_USERNAME = "MetaGatheringE2ETestBot"


@dataclass(frozen=True)
class RecordedCall:
    method: str
    parameters: dict[str, Any]
    result: dict[str, Any] | bool


class RecordingRequest(BaseRequest):
    """Minimal in-memory Bot API implementation used by PTB routing tests."""

    def __init__(self, *, allowed_chat_ids: set[int]) -> None:
        self.calls: list[RecordedCall] = []
        self._next_message_id = 100
        self._allowed_chat_ids = frozenset(allowed_chat_ids)

    @property
    def read_timeout(self) -> float | None:
        return None

    async def initialize(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def do_request(
        self,
        url: str,
        method: str,
        request_data: RequestData | None = None,
        **_kwargs,
    ) -> tuple[int, bytes]:
        api_method = url.rsplit("/", 1)[-1]
        parameters = dict(request_data.parameters) if request_data else {}
        self._validate_outbound(api_method, parameters)
        result = self._result(api_method, parameters)
        self.calls.append(RecordedCall(api_method, parameters, result))
        return 200, json.dumps({"ok": True, "result": result}).encode()

    def _result(self, method: str, parameters: dict[str, Any]) -> dict[str, Any] | bool:
        if method == "getMe":
            return {
                "id": BOT_ID,
                "is_bot": True,
                "first_name": "MetaGatherer E2E",
                "username": BOT_USERNAME,
            }
        if method in {"sendMessage", "editMessageText"}:
            self._next_message_id += 1
            return self._message(parameters, self._next_message_id)
        if method in {"answerCallbackQuery", "setMyCommands", "deleteMessage"}:
            return True
        raise AssertionError(f"RecordingRequest has no response fixture for {method}")

    def _validate_outbound(self, method: str, parameters: dict[str, Any]) -> None:
        chat_id = parameters.get("chat_id")
        if chat_id is not None and int(chat_id) not in self._allowed_chat_ids:
            raise AssertionError(f"{method} attempted unexpected chat_id={chat_id}")

        text = parameters.get("text")
        if isinstance(text, str) and len(text) > 4096:
            raise AssertionError(f"{method} text exceeds Telegram's 4096 character limit")

        markup = parameters.get("reply_markup") or {}
        for row in markup.get("inline_keyboard", []):
            for button in row:
                callback_data = button.get("callback_data")
                if callback_data and len(callback_data.encode()) > 64:
                    raise AssertionError("callback_data exceeds Telegram's 64 byte limit")

    @staticmethod
    def _message(parameters: dict[str, Any], message_id: int) -> dict[str, Any]:
        chat_id = int(parameters.get("chat_id", 0))
        chat = {"id": chat_id, "type": "private", "first_name": "E2E User"}
        result: dict[str, Any] = {
            "message_id": message_id,
            "date": 1_700_000_000,
            "chat": chat,
            "from": {
                "id": BOT_ID,
                "is_bot": True,
                "first_name": "MetaGatherer E2E",
                "username": BOT_USERNAME,
            },
            "text": parameters.get("text", ""),
        }
        if parameters.get("reply_markup"):
            result["reply_markup"] = parameters["reply_markup"]
        return result

    def calls_for(self, method: str) -> list[RecordedCall]:
        return [call for call in self.calls if call.method == method]

    def last_call(self, method: str) -> RecordedCall:
        return self.calls_for(method)[-1]


def private_command_update(
    bot: Bot,
    *,
    text: str,
    user_id: int = 10_001,
    username: str = "e2e_user",
    update_id: int = 1,
) -> Update:
    command = text.split(maxsplit=1)[0]
    return Update.de_json(
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": 1_700_000_000,
                "chat": {"id": user_id, "type": "private", "first_name": "E2E"},
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": "E2E",
                    "username": username,
                },
                "text": text,
                "entities": [{"offset": 0, "length": len(command), "type": "bot_command"}],
            },
        },
        bot,
    )


def private_callback_update(
    bot: Bot,
    *,
    data: str,
    source_message: RecordedCall,
    user_id: int = 10_001,
    username: str = "e2e_user",
    update_id: int = 2,
) -> Update:
    parameters = source_message.parameters
    return Update.de_json(
        {
            "update_id": update_id,
            "callback_query": {
                "id": f"callback-{update_id}",
                "chat_instance": "e2e-chat-instance",
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": "E2E",
                    "username": username,
                },
                "data": data,
                "message": {
                    "message_id": source_message.result["message_id"],
                    "date": 1_700_000_000,
                    "chat": {"id": user_id, "type": "private", "first_name": "E2E"},
                    "from": {
                        "id": BOT_ID,
                        "is_bot": True,
                        "first_name": "MetaGatherer E2E",
                        "username": BOT_USERNAME,
                    },
                    "text": parameters["text"],
                    "reply_markup": parameters.get("reply_markup"),
                },
            },
        },
        bot,
    )


def callback_data_for_button(call: RecordedCall, button_text: str) -> str:
    keyboard = call.parameters["reply_markup"]["inline_keyboard"]
    for row in keyboard:
        for button in row:
            if button["text"] == button_text:
                return button["callback_data"]
    raise AssertionError(f"Button {button_text!r} not found in {keyboard!r}")
