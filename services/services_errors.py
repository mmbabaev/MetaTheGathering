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
