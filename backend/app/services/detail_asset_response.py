"""Release audio read leases on completion, cancellation, and transport errors."""

from contextlib import ExitStack

from fastapi.responses import FileResponse


class DetailAssetFileResponse(FileResponse):
    def __init__(self, *args, leases: ExitStack, **kwargs):
        super().__init__(*args, **kwargs)
        self.leases = leases

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.leases.close()
