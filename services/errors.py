"""Re-export service errors for `from services import errors`."""

from services.services_errors import (
    AetherhubTournamentAlreadyLinked,
    MultipleActiveTournaments,
    ParticipantAlreadyRegistered,
    ParticipantError,
    ParticipantNotFound,
    SelfVoteNotAllowed,
    ServiceError,
    TournamentAlreadyExists,
    TournamentError,
    TournamentInvalidState,
    TournamentNotFound,
    VoteTargetNotFound,
    VotingError,
    VotingNotAllowed,
)

__all__ = [
    "ServiceError",
    "TournamentError",
    "TournamentNotFound",
    "TournamentAlreadyExists",
    "TournamentInvalidState",
    "AetherhubTournamentAlreadyLinked",
    "MultipleActiveTournaments",
    "ParticipantError",
    "ParticipantAlreadyRegistered",
    "ParticipantNotFound",
    "VotingError",
    "VotingNotAllowed",
    "SelfVoteNotAllowed",
    "VoteTargetNotFound",
]
