"""
Collection-related enums.

This module contains enum definitions for Collection fields.
"""
from enum import Enum


class CollectionSphere(str, Enum):
    """Sphere options for collection."""
    HYDROSPHERE = "hydrosphere"
    CRYOSPHERE = "cryosphere"
    LITHOSPHERE = "lithosphere"
    PEDOSPHERE = "pedosphere"
    ATMOSPHERE = "atmosphere"
    BIOSPHERE = "biosphere"
    ANTHROPOSPHERE = "anthroposphere"
