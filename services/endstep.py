"""Read-only client for the authenticated Endstep ranked leaderboard API."""

from __future__ import annotations

from typing import Any, Iterable

import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError

ENDSTEP_DEFAULT_BASE_URL = "https://endstep.cc"
ENDSTEP_DEFAULT_FORMAT = "Pauper"
ENDSTEP_SEARCH_LIMIT = 50


class EndstepApiError(RuntimeError):
    """The Endstep API could not be read or returned an unexpected contract."""


class EndstepQueue(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    format_id: str = Field(alias="formatId", min_length=1)
    display_name: str = Field(alias="displayName", min_length=1)


class EndstepLeaderboardPlayer(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    user_id: str | int = Field(alias="userId")
    username: str = Field(min_length=1)
    rank: int | None = Field(default=None, ge=1)
    rating: int
    rd: int = Field(ge=0)
    wins: int = Field(default=0, ge=0)
    losses: int = Field(default=0, ge=0)
    draws: int = Field(default=0, ge=0)
    matches_played: int = Field(default=0, alias="matchesPlayed", ge=0)
    provisional: bool = False


class EndstepLeaderboardPage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    rows: tuple[EndstepLeaderboardPlayer, ...]
    total: int = Field(ge=0)
    provisional_count: int = Field(default=0, alias="provisionalCount", ge=0)


class EndstepPlayerLookup(BaseModel):
    model_config = ConfigDict(frozen=True)

    requested_username: str
    player: EndstepLeaderboardPlayer | None
    exact_matches: tuple[EndstepLeaderboardPlayer, ...] = ()


class EndstepClient:
    """Small session-based client for Endstep's own ranked JSON endpoints.

    The website protects leaderboard reads with the same cookie session as the
    browser application. The client uses Endstep's ``Continue as Guest`` flow,
    so no account credentials are required or stored.
    """

    def __init__(
        self,
        base_url: str = ENDSTEP_DEFAULT_BASE_URL,
        *,
        session: requests.Session | None = None,
        timeout: int = 15,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._timeout = timeout
        self._authenticated = False

    @staticmethod
    def _http_error(operation: str, status_code: int) -> EndstepApiError:
        if status_code == 401:
            return EndstepApiError(f"{operation}: Endstep отклонил авторизацию")
        if status_code == 429:
            return EndstepApiError(f"{operation}: Endstep временно ограничил частоту запросов")
        return EndstepApiError(f"{operation}: Endstep вернул HTTP {status_code}")

    @staticmethod
    def _json(response: requests.Response, operation: str) -> Any:
        if response.status_code >= 400:
            raise EndstepClient._http_error(operation, response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise EndstepApiError(f"{operation}: Endstep вернул не-JSON ответ") from exc

    def _start_guest_session(self) -> None:
        try:
            response = self._session.post(
                f"{self._base_url}/api/auth/guest",
                json={},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise EndstepApiError("Не удалось подключиться к Endstep при создании гостевой сессии") from exc
        body = self._json(response, "Гостевая сессия")
        if not isinstance(body, dict) or not isinstance(body.get("user"), dict):
            raise EndstepApiError("Гостевая сессия: неожиданный формат ответа Endstep")
        self._authenticated = True

    def _get_json(self, path: str, *, params: dict[str, str | int] | None = None) -> Any:
        if not self._authenticated:
            self._start_guest_session()
        for attempt in range(2):
            try:
                response = self._session.get(
                    f"{self._base_url}/api{path}",
                    params=params,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                raise EndstepApiError("Не удалось подключиться к Endstep") from exc
            if response.status_code != 401 or attempt == 1:
                return self._json(response, "Чтение лидерборда")
            self._authenticated = False
            self._start_guest_session()
        raise AssertionError("unreachable")

    @staticmethod
    def _rows(body: Any, key: str) -> list[Any]:
        if isinstance(body, list):
            return body
        if isinstance(body, dict) and isinstance(body.get(key), list):
            return body[key]
        raise EndstepApiError(f"Endstep изменил формат ответа {key}")

    def queues(self) -> tuple[EndstepQueue, ...]:
        body = self._get_json("/ranked/queues")
        try:
            return tuple(EndstepQueue.model_validate(row) for row in self._rows(body, "queues"))
        except ValidationError as exc:
            raise EndstepApiError("Endstep изменил формат списка ranked-форматов") from exc

    def resolve_format_id(self, format_name: str = ENDSTEP_DEFAULT_FORMAT) -> str:
        wanted = format_name.strip().casefold()
        matches = [
            queue
            for queue in self.queues()
            if queue.format_id.casefold() == wanted or queue.display_name.casefold() == wanted
        ]
        if len(matches) != 1:
            raise EndstepApiError(f'Формат Endstep "{format_name}": найдено {len(matches)} совпадений')
        return matches[0].format_id

    def leaderboard(
        self,
        *,
        format_id: str,
        season_id: str | None = None,
        query: str | None = None,
        limit: int = ENDSTEP_SEARCH_LIMIT,
        offset: int = 0,
    ) -> EndstepLeaderboardPage:
        params: dict[str, str | int] = {
            "format": format_id,
            "limit": limit,
            "offset": offset,
        }
        if season_id:
            params["season"] = season_id
        if query:
            params["q"] = query
        body = self._get_json("/ranked/leaderboard", params=params)
        try:
            return EndstepLeaderboardPage.model_validate(body)
        except ValidationError as exc:
            raise EndstepApiError("Endstep изменил формат ranked-лидерборда") from exc

    def find_players(
        self,
        usernames: Iterable[str],
        *,
        format_name: str = ENDSTEP_DEFAULT_FORMAT,
        season_id: str | None = None,
    ) -> tuple[EndstepPlayerLookup, ...]:
        """Find exact usernames despite Endstep's substring ``q`` search."""

        unique: list[str] = []
        seen: set[str] = set()
        for raw_username in usernames:
            username = raw_username.strip()
            if not username:
                continue
            key = username.casefold()
            if key not in seen:
                seen.add(key)
                unique.append(username)

        if not unique:
            return ()

        format_id = self.resolve_format_id(format_name)
        result: list[EndstepPlayerLookup] = []
        for username in unique:
            page = self.leaderboard(
                format_id=format_id,
                season_id=season_id,
                query=username,
            )
            exact = [row for row in page.rows if row.username.casefold() == username.casefold()]
            result.append(
                EndstepPlayerLookup(
                    requested_username=username,
                    player=exact[0] if len(exact) == 1 else None,
                    exact_matches=tuple(exact),
                )
            )
        return tuple(result)
