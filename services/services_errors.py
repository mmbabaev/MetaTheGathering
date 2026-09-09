class ServiceError(Exception):
    """Базовый класс для ошибок сервисного слоя."""


# --- Tournament ---


class TournamentError(ServiceError):
    pass


class TournamentNotFound(TournamentError):
    pass


class TournamentAlreadyExists(TournamentError):
    pass


class TournamentInvalidState(TournamentError):
    pass


class AetherhubTournamentAlreadyLinked(TournamentError):
    """The same external AetherHub event belongs to another local tournament."""

    def __init__(self, *, url: str, tournament_id: int, tournament_title: str):
        self.url = url
        self.tournament_id = tournament_id
        self.tournament_title = tournament_title
        super().__init__(
            f"AetherHub-турнир уже привязан к турниру #{tournament_id} «{tournament_title}». "
            "Повторный импорт в другой турнир запрещён."
        )


class MultipleActiveTournaments(TournamentError):
    """Активных турниров несколько — нужно уточнить, с каким работать."""

    def __init__(self, tournaments: list):
        self.tournaments = tournaments  # list of (id, title)
        super().__init__(f"Multiple active tournaments: {[t[0] for t in tournaments]}")


# --- Participant ---


class ParticipantError(ServiceError):
    pass


class ParticipantAlreadyRegistered(ParticipantError):
    pass


class ParticipantNotFound(ParticipantError):
    pass


# --- Voting ---


class VotingError(ServiceError):
    pass


class VotingNotAllowed(VotingError):
    pass


class SelfVoteNotAllowed(VotingError):
    pass


class VoteTargetNotFound(VotingError):
    pass
