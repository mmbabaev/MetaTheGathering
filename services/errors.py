"""Re-export service errors for `from services import errors`."""

from services.services_errors import (
    ServiceError,
    TournamentError,
    TournamentNotFound,
    TournamentAlreadyExists,
    TournamentInvalidState,
    MultipleActiveTournaments,
    ParticipantError,
    ParticipantAlreadyRegistered,
    ParticipantNotFound,
    VotingError,
    VotingNotAllowed,
    SelfVoteNotAllowed,
    VoteTargetNotFound,
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
