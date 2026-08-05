"""
Domain-level exceptions.

These exceptions carry business/validation semantics and are translated
into appropriate HTTP responses by the global exception handlers in main.py.
Repository and service layers should raise these instead of HTTPException
to keep HTTP concerns out of the data-access layer.
"""


class AppValidationError(Exception):
    """Raised when a business-rule or data-integrity validation fails.

    Translated to HTTP 400 by the global handler.
    """

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)
