"""
Recording-related enums.

This module contains enum definitions for Recording fields.
"""
from enum import Enum


class RecordingMedium(str, Enum):
    """Medium options for recording."""
    AIR = "Air"
    WATER = "Water"


class RecordingType(str, Enum):
    """Recording type options."""
    PASSIVE = "Passive"
    FOCAL = "Focal"
    ENCLOSURE = "Enclosure"
