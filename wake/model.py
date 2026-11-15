from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    """One public notification observation.

    ``app_name`` and ``summary`` are untrusted. Neither is a recipient id.
    ``origin`` is the channel that delivered the observation to this process.
    """

    app_name: str
    replaces_id: int
    summary: str
    origin: str


@dataclass(frozen=True)
class ParseFailure:
    reason: str = "MALFORMED_NOTIFY"

    def __str__(self) -> str:
        return self.reason
