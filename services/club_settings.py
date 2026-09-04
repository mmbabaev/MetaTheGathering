"""Per-club destination for manual tournament announcements."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.clubs import (
    TEST_ANNOUNCEMENT_CHAT_ID,
    TEST_ANNOUNCEMENT_CHAT_URL,
    ClubIdentity,
    club_identities,
)

DESTINATION_NONE = "none"
DESTINATION_TEST = "test"
DESTINATION_REAL = "real"
DESTINATIONS = {DESTINATION_NONE, DESTINATION_TEST, DESTINATION_REAL}


@dataclass(frozen=True)
class AnnouncementTarget:
    destination: str
    chat_id: int | None
    label: str


class InvalidClubAnnouncementSetting(ValueError):
    pass


class ClubAnnouncementSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_destination(self, club_name: str) -> str:
        value = self.db.execute(
            select(models.ClubAnnouncementSetting.destination).where(
                models.ClubAnnouncementSetting.club_name == club_name
            )
        ).scalar_one_or_none()
        return value if value in DESTINATIONS else DESTINATION_NONE

    def set_destination(self, club_name: str, destination: str) -> AnnouncementTarget:
        identity = self._identity(club_name)
        target = self.resolve(identity, destination)
        row = self.db.execute(
            select(models.ClubAnnouncementSetting).where(models.ClubAnnouncementSetting.club_name == club_name)
        ).scalar_one_or_none()
        if row is None:
            row = models.ClubAnnouncementSetting(club_name=club_name, destination=destination)
            self.db.add(row)
        else:
            row.destination = destination
        self.db.commit()
        return target

    def current_target(self, identity: ClubIdentity) -> AnnouncementTarget:
        try:
            return self.resolve(identity, self.get_destination(identity.name))
        except InvalidClubAnnouncementSetting:
            return self.resolve(identity, DESTINATION_NONE)

    @staticmethod
    def resolve(identity: ClubIdentity, destination: str) -> AnnouncementTarget:
        if destination == DESTINATION_NONE:
            return AnnouncementTarget(destination, None, "не отправлять")
        if destination == DESTINATION_TEST:
            return AnnouncementTarget(destination, TEST_ANNOUNCEMENT_CHAT_ID, TEST_ANNOUNCEMENT_CHAT_URL)
        if destination == DESTINATION_REAL and identity.real_chat_id and identity.real_chat_label:
            return AnnouncementTarget(destination, identity.real_chat_id, identity.real_chat_label)
        raise InvalidClubAnnouncementSetting("Для этого клуба такой чат недоступен.")

    @staticmethod
    def _identity(club_name: str) -> ClubIdentity:
        identity = next((row for row in club_identities() if row.name == club_name), None)
        if identity is None:
            raise InvalidClubAnnouncementSetting("Клуб не найден.")
        return identity
