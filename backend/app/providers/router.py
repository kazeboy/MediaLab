"""Route each request to the provider chain for its platform (X or TikTok).

Platforms never share providers: the FxTwitter fallback exists only in the X
chain, and each yt-dlp provider loads only its own platform's extractor.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import AppError, ErrorCode
from ..models import PostMetadata
from ..validation import ValidatedUrl
from .base import ProgressCallback, VideoProvider


class PlatformRouter(VideoProvider):
    name = "router"

    def __init__(self, providers: dict[str, VideoProvider]) -> None:
        self.providers = providers

    def _for(self, platform: str | None) -> VideoProvider:
        provider = self.providers.get(platform or "")
        if provider is None:
            raise AppError(ErrorCode.UNSUPPORTED_URL, "This platform is not supported.")
        return provider

    def provider_for(self, name: str | None, platform: str | None = None) -> VideoProvider:
        return self._for(platform).provider_for(name, platform)

    def extract(self, url: ValidatedUrl) -> PostMetadata:
        provider = self._for(url.platform)
        post = provider.extract(url)
        # Record which concrete provider answered (a chain sets this itself).
        return post if post.provider else post.model_copy(update={"provider": provider.name})

    def download(
        self,
        url: ValidatedUrl,
        video_index: int,
        format_ids: list[str],
        dest_dir: Path,
        on_progress: ProgressCallback,
    ) -> dict[str, Path]:  # pragma: no cover - JobManager resolves the concrete provider first
        return self._for(url.platform).download(url, video_index, format_ids, dest_dir, on_progress)
