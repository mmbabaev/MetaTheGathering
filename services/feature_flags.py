from dataclasses import dataclass

from sqlalchemy.orm import Session

from core import models


@dataclass
class FeatureFlagMeta:
    description: str
    value_type: str
    default_value: str


@dataclass
class FeatureFlagInfo:
    name: str
    description: str
    value_type: str
    default_value: str
    enabled: bool


class FeatureFlags:
    RECORD_OPPONENTS = "recordOpponents"


KNOWN_FLAGS: dict[str, FeatureFlagMeta] = {
    FeatureFlags.RECORD_OPPONENTS: FeatureFlagMeta(
        description="Кнопка «Записать оппонентов» на карточке турнира",
        value_type="bool",
        default_value="true",
    ),
}


class FeatureFlagService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def ensure_defaults(self) -> None:
        for name, meta in KNOWN_FLAGS.items():
            existing = self.db.query(models.FeatureFlag).filter_by(name=name).first()
            if not existing:
                self.db.add(
                    models.FeatureFlag(
                        name=name,
                        description=meta.description,
                        value_type=meta.value_type,
                        default_value=meta.default_value,
                    )
                )
        self.db.commit()

    def _get_row(self, name: str) -> models.FeatureFlag | None:
        return self.db.query(models.FeatureFlag).filter_by(name=name).first()

    def _resolve_value(self, row: models.FeatureFlag) -> str:
        return row.current_value if row.current_value is not None else row.default_value

    def is_enabled(self, name: str) -> bool:
        row = self._get_row(name)
        if row is None:
            meta = KNOWN_FLAGS.get(name)
            return meta is not None and meta.default_value == "true"
        return self._resolve_value(row) == "true"

    def list_flags(self) -> list[FeatureFlagInfo]:
        rows = {r.name: r for r in self.db.query(models.FeatureFlag).all()}
        result = []
        for name, meta in KNOWN_FLAGS.items():
            row = rows.get(name)
            if row:
                enabled = self._resolve_value(row) == "true"
            else:
                enabled = meta.default_value == "true"
            result.append(
                FeatureFlagInfo(
                    name=name,
                    description=meta.description,
                    value_type=meta.value_type,
                    default_value=meta.default_value,
                    enabled=enabled,
                )
            )
        return result

    def toggle(self, name: str) -> bool:
        row = self._get_row(name)
        if row is None:
            meta = KNOWN_FLAGS.get(name)
            if meta is None:
                raise ValueError(f"Unknown feature flag: {name}")
            current = meta.default_value == "true"
            row = models.FeatureFlag(
                name=name,
                description=meta.description,
                value_type=meta.value_type,
                default_value=meta.default_value,
                current_value="false" if current else "true",
            )
            self.db.add(row)
        else:
            current = self._resolve_value(row) == "true"
            row.current_value = "false" if current else "true"
        self.db.commit()
        return not current
