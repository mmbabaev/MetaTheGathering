"""Re-export service errors for `from services import errors`."""

from services.services_errors import (
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
    "MultipleActiveTournaments",
    "ParticipantError",
    "ParticipantAlreadyRegistered",
    "ParticipantNotFound",
    "VotingError",
    "VotingNotAllowed",
    "SelfVoteNotAllowed",
    "VoteTargetNotFound",
]
