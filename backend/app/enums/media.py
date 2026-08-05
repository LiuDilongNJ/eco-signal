from enum import Enum


class MediaType(str, Enum):
    """Media type enum."""
    AUDIO = "audio"
    PHOTO = "photo"
    VIDEO = "video"
