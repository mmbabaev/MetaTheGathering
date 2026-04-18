from dataclasses import dataclass, field


@dataclass
class AppConfig:
    debug: bool
    tournament_timezone: str
    tournament_create_time: str
    version: str = "0.1.1"
