"""
Worker task type enumerations.
"""
from enum import Enum


class WorkerTaskType(str, Enum):
    """
    RabbitMQ worker task types.
    
    Used for type-safe task submission.
    """
    ANALYZE_BIRDNET = "analyze_birdnet"
    ANALYZE_BATDETECT = "analyze_batdetect"
    ANALYZE_INSECTS = "analyze_insects"
    ANALYZE_ACOUSTIC_INDEX = "analyze_acoustic_index"
    PROCESS_MEDIA_BATCH = "process_media_batch"
    MERGE_FILE_CHUNKS = "merge_file_chunks"
    IMPORT_COLLECTION_BUNDLE = "import_collection_bundle"
    EXPORT_COLLECTION_BUNDLE = "export_collection_bundle"
