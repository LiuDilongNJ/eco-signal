"""Custom exceptions for AI analysis modules."""


class ModelDownloadError(Exception):
    """Raised when a model file cannot be loaded due to download or network failure.

    This exception signals that the error is transient and the task should be retried.
    It is distinct from RuntimeError (e.g., invalid audio, tool not installed) which
    should NOT be retried.
    """
    pass
