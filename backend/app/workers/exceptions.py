class TaskRetryError(Exception):
    """Request delayed retry from the RabbitMQ worker."""

    def __init__(self, message: str = "Task should be retried", *, defer: int = 30) -> None:
        super().__init__(message)
        self.defer = defer
