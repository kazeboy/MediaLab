"""Deterministic primary -> fallback provider chain.

The primary provider (yt-dlp, talking to X directly) is always tried first.
The fallback is tried only when the primary reports that X gave it **no
usable video or post** (``no_video`` / ``not_found``), which is what X returns
to logged-out clients for posts it withholds from them. Network errors,
timeouts, rate limits and explicit login/protected-account errors never
trigger the fallback.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from ..errors import AppError, ErrorCode
from ..models import PostMetadata
from ..validation import ValidatedUrl
from .base import ProgressCallback, VideoProvider

log = logging.getLogger(__name__)

FALLBACK_ON = frozenset({ErrorCode.NO_VIDEO, ErrorCode.NOT_FOUND})


class ProviderChain(VideoProvider):
    name = "chain"

    def __init__(
        self, primary: VideoProvider, fallback: VideoProvider, enabled: Callable[[], bool] = lambda: True
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        # Read on every analysis, so toggling the GUI setting needs no restart.
        self.enabled = enabled

    def provider_for(self, name: str | None, platform: str | None = None) -> VideoProvider:
        if name == self.fallback.name:
            if not self.enabled():
                # The user switched the fallback off after analysing: don't contact the third party again.
                raise AppError(
                    ErrorCode.FORBIDDEN,
                    "The FxTwitter fallback was turned off in Settings. Analyse the post again.",
                )
            return self.fallback
        return self.primary

    def extract(self, url: ValidatedUrl) -> PostMetadata:
        try:
            post = self.primary.extract(url)
        except AppError as primary_error:
            if primary_error.code not in FALLBACK_ON or not self.enabled():
                raise
            log.info("%s: %s; trying fallback provider %s", self.primary.name, primary_error.code.value, self.fallback.name)
            try:
                post = self.fallback.extract(url)
            except AppError as fallback_error:
                # The fallback's answer is more specific unless it only repeats "no video/not found".
                if fallback_error.code in FALLBACK_ON:
                    raise primary_error from fallback_error
                raise
            return post if post.provider else post.model_copy(update={"provider": self.fallback.name})
        return post if post.provider else post.model_copy(update={"provider": self.primary.name})

    def download(
        self,
        url: ValidatedUrl,
        video_index: int,
        format_ids: list[str],
        dest_dir: Path,
        on_progress: ProgressCallback,
    ) -> dict[str, Path]:  # pragma: no cover - JobManager resolves the concrete provider first
        return self.primary.download(url, video_index, format_ids, dest_dir, on_progress)
