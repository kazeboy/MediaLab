"""Provider-agnostic domain models.

Extraction providers return these models; the rest of the application (option
selection, downloads, API responses) only depends on them, never on the raw
output of a specific extraction library.

Unknown values are always ``None``; nothing is guessed or filled in.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MediaFormat(BaseModel):
    """A single stream/format offered by the source."""

    model_config = ConfigDict(frozen=True)

    format_id: str
    ext: str | None = None
    protocol: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    vcodec: str | None = Field(default=None, description="Video codec; None if unknown")
    acodec: str | None = Field(default=None, description="Audio codec; None if unknown")
    has_video: bool | None = Field(default=None, description="None if the source does not say")
    has_audio: bool | None = Field(default=None, description="None if the source does not say")
    tbr: float | None = Field(default=None, description="Total bitrate in kbit/s")
    filesize: int | None = Field(default=None, description="Exact size in bytes, if reported")
    filesize_approx: int | None = Field(default=None, description="Approximate size in bytes (e.g. bitrate x duration)")
    mp4_compatible: bool | None = Field(
        default=None, description="Whether the stream can be placed in an MP4 without re-encoding; None if unknown"
    )


class VideoEntry(BaseModel):
    """One video inside a post (posts can contain several)."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=1, description="1-based position of the video within the post")
    video_id: str | None = None
    title: str | None = None
    duration_seconds: float | None = None
    thumbnail_url: str | None = None
    formats: tuple[MediaFormat, ...] = ()


class DramaInfo(BaseModel):
    """TikTok Short Drama episode details, as reported by TikTok."""

    model_config = ConfigDict(frozen=True)

    series_id: str
    series_title: str | None = None
    episode: int | None = None
    episode_count: int | None = None
    account_used: bool = Field(default=False, description="Whether the linked TikTok account was used")


class SeriesEpisode(BaseModel):
    """One episode of a Short Drama series, as listed by TikTok for the current viewer."""

    model_config = ConfigDict(frozen=True)

    number: int
    item_id: str
    title: str | None = None
    duration_seconds: float | None = None
    thumbnail_url: str | None = None
    available: bool = Field(description="TikTok lists a playable stream for this viewer")
    availability: str = Field(description="available | login_required | locked")
    publisher_handle: str | None = None


class SeriesInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    series_id: str
    title: str | None = None
    description: str | None = None
    episode_count: int | None = None
    cover_url: str | None = None
    publisher_handle: str | None = None
    publisher_name: str | None = None
    account_used: bool = False
    episodes: tuple[SeriesEpisode, ...] = ()


class PostMetadata(BaseModel):
    """Normalised metadata for a post."""

    model_config = ConfigDict(frozen=True)

    url: str
    post_id: str
    author_name: str | None = None
    author_handle: str | None = None
    text: str | None = None
    videos: tuple[VideoEntry, ...] = ()
    provider: str | None = Field(default=None, description="Name of the provider that produced this metadata")
    possibly_sensitive: bool | None = Field(
        default=None,
        description="Content classification as reported by the source (informational; may be missing or wrong)",
    )
    drama: DramaInfo | None = None


class ResolutionOption(BaseModel):
    """A downloadable choice presented to the user.

    An option is either a single file that already contains video (+ audio), or
    a video-only stream that will be combined with an audio stream using a
    lossless FFmpeg stream copy.
    """

    model_config = ConfigDict(frozen=True)

    option_id: str
    label: str
    is_best: bool = False
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    vcodec: str | None = None
    acodec: str | None = None
    has_audio: bool | None = None
    video_format_id: str
    audio_format_id: str | None = None
    requires_merge: bool = False
    tbr: float | None = None
    filesize: int | None = None
    filesize_approx: int | None = None
    downloadable: bool = True
    too_large: bool = Field(default=False, description="Not downloadable because it exceeds the size limit")
    audio_converted: bool = Field(default=False, description="Audio will be converted to AAC for MP4 playback compatibility")
    fallback_audio_format_id: str | None = Field(
        default=None,
        description="Separate audio to use if the video, despite its metadata, turns out to have no audio track",
    )
    note: str | None = None
    base_note: str | None = Field(default=None, exclude=True, description="Note before a size-limit note replaced it")

    @property
    def format_ids(self) -> list[str]:
        ids = [self.video_format_id]
        if self.audio_format_id:
            ids.append(self.audio_format_id)
        return ids

    @property
    def known_size(self) -> int | None:
        return self.filesize if self.filesize is not None else self.filesize_approx
