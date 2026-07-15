"""Тонкий клиент YandexGPT (Yandex Cloud Foundation Models).

Опционален: без `YANDEX_API_KEY`/`YANDEX_FOLDER_ID` клиент выключен и `complete()` возвращает None —
вызывающий код обязан иметь фолбэк.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from core.config import settings

logger = logging.getLogger(__name__)

_COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


class YandexLLM:
    def __init__(
        self,
        api_key: Optional[str] = None,
        folder_id: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 15,
    ):
        self.api_key = api_key if api_key is not None else settings.YANDEX_API_KEY
        self.folder_id = folder_id if folder_id is not None else settings.YANDEX_FOLDER_ID
        self.model = model if model is not None else settings.YANDEX_MODEL
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.folder_id)

    @property
    def model_uri(self) -> str:
        return f"gpt://{self.folder_id}/{self.model}"

    def complete(self, system: str, user: str) -> Optional[str]:
        """Ответ модели одной строкой. None — клиент выключен или запрос не удался."""
        if not self.enabled:
            return None
        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {"stream": False, "temperature": 0, "maxTokens": 200},
            "messages": [
                {"role": "system", "text": system},
                {"role": "user", "text": user},
            ],
        }
        headers = {"Authorization": f"Api-Key {self.api_key}", "x-folder-id": self.folder_id}
        try:
            response = requests.post(_COMPLETION_URL, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return self._extract_text(response.json())
        except requests.RequestException as e:
            logger.warning("[llm] запрос к YandexGPT не удался: %s", e)
            return None

    @staticmethod
    def _extract_text(body: dict) -> Optional[str]:
        alternatives = (body.get("result") or {}).get("alternatives") or []
        if not alternatives:
            logger.warning("[llm] пустой ответ YandexGPT: %s", body)
            return None
        return (alternatives[0].get("message") or {}).get("text")
