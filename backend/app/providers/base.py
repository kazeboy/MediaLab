"""Extraction provider interface.

A provider turns a validated post URL into :class:`~app.models.PostMetadata`
and downloads specific formats into a directory. Swapping yt-dlp for another
implementation only requires a new class implementing this interface; the API
and frontend are unaffected.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..models import PostMetadata
from ..validation import ValidatedUrl


@dataclass(frozen=True)
class ProgressUpdate:
    format_id: str
    status: str  # "downloading" | "finished" | "retrying"
    downloaded_bytes: int
    total_bytes: int | None
    total_is_estimate: bool
    speed_bytes_per_second: float | None = None
    eta_seconds: float | None = None
    note: str | None = None  # for status "retrying": why, shown as the job stage


ProgressCallback = Callable[[ProgressUpdate], None]


class VideoProvider(ABC):
    """Interface implemented by every extraction backend."""

    name: str = "provider"

    def provider_for(self, name: str | None, platform: str | None = None) -> "VideoProvider":
        """Return the provider that must download an analysis made by ``name``.

        Single providers return themselves; a chain or platform router returns
        the member that produced the analysis (download URLs are provider-specific).
        """
        return self

    @abstractmethod
    def extract(self, url: ValidatedUrl) -> PostMetadata:
        """Return metadata for ``url`` without downloading media.

        Must raise :class:`~app.errors.AppError` on failure.
        """

    @abstractmethod
    def download(
        self,
        url: ValidatedUrl,
        video_index: int,
        format_ids: list[str],
        dest_dir: Path,
        on_progress: ProgressCallback,
    ) -> dict[str, Path]:
        """Download each format in ``format_ids`` into ``dest_dir``.

        Returns a mapping of format ID to the downloaded file. Must raise
        :class:`~app.errors.AppError` on failure. Exceptions raised by
        ``on_progress`` (used to abort a download) must propagate.
        """
