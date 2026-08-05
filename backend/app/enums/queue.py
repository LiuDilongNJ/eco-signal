from enum import IntEnum


class QueueStatus(IntEnum):
    """Persisted queue processing states."""

    PENDING = 0
    RUNNING = 1
    COMPLETED = 2
    ERROR = 3
    WARNING = 4
