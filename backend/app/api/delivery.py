"""Streaming hand-off of a finished MP4 to the browser.

The file is read in 1 MiB chunks in a worker thread (never loaded into memory)
and the delivery is reported *complete* only after every byte and the final
empty body frame have been handed to the server. Whatever happens (normal
completion, client disconnect (``ClientDisconnect`` on ASGI 2.4+, task
cancellation on older servers), or an error), ``on_done`` runs exactly once in
``finally``, so the temporary file is never deleted mid-stream and never leaked.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote

import anyio
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from ..storage import Delivery

CHUNK_BYTES = 1024 * 1024


def _content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "").replace("\\", "") or "video.mp4"
    return f"attachment; filename=\"{ascii_name}\"; filename*=utf-8''{quote(filename)}"


class DeliveryResponse(StreamingResponse):
    def __init__(self, item: Delivery, on_done: Callable[[bool], None]) -> None:
        self.item = item
        self.on_done = on_done
        self.sent_bytes = 0
        self.completed = False
        super().__init__(
            self._chunks(),
            media_type="application/zip" if item.filename.lower().endswith(".zip") else "video/mp4",
            headers={
                "Content-Length": str(item.size_bytes),
                "Content-Disposition": _content_disposition(item.filename),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def _chunks(self):
        handle = await anyio.to_thread.run_sync(open, self.item.path, "rb")
        try:
            while True:
                chunk = await anyio.to_thread.run_sync(handle.read, CHUNK_BYTES)
                if not chunk:
                    break
                yield chunk
                self.sent_bytes += len(chunk)
        finally:
            handle.close()

    async def stream_response(self, send: Send) -> None:
        await super().stream_response(send)
        # Reached only after the final (more_body=False) frame was sent.
        self.completed = self.sent_bytes == self.item.size_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.on_done(self.completed)
