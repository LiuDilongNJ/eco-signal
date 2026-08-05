"""
Task status enumerations.
"""
from enum import Enum


class AssignmentTaskType(str, Enum):
    """Supported task target scopes in ecoSignal."""

    MEDIA = "media"
    ANNOTATION = "annotation"


class TaskStatus(str, Enum):
    """Status of a user-assigned review/annotation task."""

    ASSIGNED = "assigned"
    REVIEWED = "reviewed"
