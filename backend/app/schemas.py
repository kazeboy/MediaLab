"""Typed API request and response schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .jobs import JobSnapshot, JobState
from .models import DramaInfo, MediaFormat, ResolutionOption, SeriesInfo
from .storage import Delivery, DeliveryState


class ErrorBody(BaseModel):
    code: str
    message: str
    action: str | None = None
    retryable: bool = False
    details: dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# ------------------------------------------------------------------- analyse
class AnalyseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048, description="Public X post, TikTok video or Short Drama episode URL")
    platform: Literal["x", "tiktok", "tiktok_shortdrama"] | None = Field(
        default=None, description="The UI tab the URL was entered in; a URL for another platform gets wrong_platform"
    )


class PostInfo(BaseModel):
    url: str
    post_id: str
    author_name: str | None
    author_handle: str | None
    text: str | None
    possibly_sensitive: bool | None = None
    drama: DramaInfo | None = None


class TikTokAccountResponse(BaseModel):
    """Status of the optional TikTok sign-in used by the Short Drama tab. Never includes cookie values."""

    linked: bool
    cookie_count: int = 0
    session_expires_at: datetime | None = None
    expired: bool = False
    saved_at: datetime | None = None


class TikTokAccountUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cookies_txt: str = Field(min_length=1, max_length=1_000_000)


class FileSizeLimits(BaseModel):
    min_mb: int
    max_mb: int
    presets_mb: list[int]


class TempStorageInfo(BaseModel):
    auto_cleanup: bool = True  # mandatory in v1.2
    retention_minutes: int
    usage_bytes: int


class SettingsResponse(BaseModel):
    """GUI-editable settings plus read-only context. Never contains paths."""

    fxtwitter_fallback: bool
    fxtwitter_host: str = "api.fxtwitter.com"
    max_file_size_mb: int
    file_size_limits: FileSizeLimits
    batch_output_max_mb: int
    batch_output_limits: FileSizeLimits
    temp_storage: TempStorageInfo
    saved: bool  # False until settings have been saved once (environment/defaults in use)


class VideoResult(BaseModel):
    index: int
    video_id: str | None
    title: str | None
    duration_seconds: float | None
    thumbnail_url: str | None
    formats: list[MediaFormat]
    options: list[ResolutionOption]


class AnalyseResponse(BaseModel):
    analysis_id: str
    platform: str
    provider: str
    post: PostInfo
    videos: list[VideoResult]
    selected_video_index: int
    expires_at: datetime


# ------------------------------------------------------------------ download
class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    video_index: int = Field(default=1, ge=1, le=100)
    option_id: str = Field(default="best", min_length=1, max_length=40, pattern=r"^[a-z0-9-]+$")


class JobProgress(BaseModel):
    stage: str | None
    downloaded_bytes: int
    total_bytes: int | None
    total_is_estimate: bool
    percent: float | None
    speed_bytes_per_second: float | None
    eta_seconds: float | None


class JobFile(BaseModel):
    file_id: str
    filename: str
    size_bytes: int
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    duration_seconds: float | None
    audio_converted: bool = False
    source_audio_codec: str | None = None
    audio_silent_source: bool = False
    download_url: str
    delivery_state: DeliveryState
    available_until: datetime | None


class JobResponse(BaseModel):
    job_id: str
    state: JobState
    video_index: int
    option_id: str
    option_label: str
    created_at: datetime
    updated_at: datetime
    progress: JobProgress
    file: JobFile | None = None
    error: ErrorBody | None = None


def _dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def job_to_response(snap: JobSnapshot, delivery: Delivery | None = None) -> JobResponse:
    file = None
    if snap.result is not None:
        probe = snap.result.probe
        file = JobFile(
            file_id=snap.result.file_id,
            filename=snap.result.filename,
            size_bytes=snap.result.size_bytes,
            width=probe.width,
            height=probe.height,
            fps=probe.fps,
            video_codec=probe.video_codec,
            audio_codec=probe.audio_codec,
            duration_seconds=probe.duration_seconds,
            audio_converted=getattr(probe, "audio_converted", False),
            source_audio_codec=getattr(probe, "source_audio_codec", None),
            audio_silent_source=getattr(probe, "audio_silent", False),
            download_url=f"/api/files/{snap.result.file_id}",
            delivery_state=delivery.state if delivery else DeliveryState.EXPIRED,
            available_until=_dt(delivery.expires_at) if delivery and delivery.state == DeliveryState.READY else None,
        )
    error = ErrorBody(**snap.error.body()) if snap.error is not None else None
    return JobResponse(
        job_id=snap.job_id,
        state=snap.state,
        video_index=snap.video_index,
        option_id=snap.option.option_id,
        option_label=snap.option.label,
        created_at=_dt(snap.created_at),
        updated_at=_dt(snap.updated_at),
        progress=JobProgress(
            stage=snap.stage,
            downloaded_bytes=snap.downloaded_bytes,
            total_bytes=snap.total_bytes,
            total_is_estimate=snap.total_is_estimate,
            percent=snap.percent,
            speed_bytes_per_second=snap.speed_bytes_per_second,
            eta_seconds=snap.eta_seconds,
        ),
        file=file,
        error=error,
    )


# ------------------------------------------------------------- Short Drama
class SeriesResponse(SeriesInfo):
    """A Short Drama series and its episodes as TikTok lists them for this viewer."""


class BatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: str = Field(pattern=r"^[0-9]{5,25}$")
    episodes: list[int] = Field(min_length=1, max_length=500)
    quality: str = Field(default="best", pattern=r"^(best|[1-9][0-9]{2,3}p)$")
    strict: bool = False
    concurrency: int = Field(default=1, ge=1, le=2)
    output: Literal["files", "zip", "merge"] = "files"
    allow_partial: bool = False


# ------------------------------------------------------------- bulk (v1.9)
class BulkCreate(BaseModel):
    """Links pasted into the Bulk view, one per line (blank lines are ignored)."""

    model_config = ConfigDict(extra="forbid")

    platform: Literal["x", "tiktok"]
    urls: list[Annotated[str, StringConstraints(max_length=4096)]] = Field(min_length=1, max_length=500)


class BulkEstimate(BaseModel):
    label: str
    size_bytes: int | None
    size_is_estimate: bool
    note: str | None


class BulkItemResponse(BaseModel):
    index: int
    input: str
    state: str  # waiting | analysing | ready | failed | invalid | duplicate | cancelled
    canonical_url: str | None
    duplicate_of: int | None
    analysis_id: str | None
    title: str | None
    author: str | None
    duration_seconds: float | None
    thumbnail_url: str | None
    video_count: int
    video_index: int
    qualities: list[str]
    estimates: dict[str, BulkEstimate]
    error: ErrorBody | None


class BulkResponse(BaseModel):
    bulk_id: str
    platform: str
    state: str  # running | done | cancelled
    limit: int
    counts: dict[str, int]
    items: list[BulkItemResponse]


def bulk_to_response(bulk) -> BulkResponse:
    from .bulk import ANALYSING, CANCELLED, DUPLICATE, FAILED, INVALID, READY, WAITING

    states = (WAITING, ANALYSING, READY, FAILED, INVALID, DUPLICATE, CANCELLED)
    return BulkResponse(
        bulk_id=bulk.bulk_id, platform=bulk.platform, state=bulk.state, limit=bulk.limit,
        counts={s: sum(1 for i in bulk.items if i.state == s) for s in states},
        items=[BulkItemResponse(
            index=i.index, input=i.input, state=i.state,
            canonical_url=i.url.canonical_url if i.url and not i.url.short_link else None,
            duplicate_of=i.duplicate_of, analysis_id=i.analysis_id, title=i.title, author=i.author,
            duration_seconds=i.duration_seconds, thumbnail_url=i.thumbnail_url, video_count=i.video_count,
            video_index=i.video_index, qualities=i.qualities,
            estimates={k: BulkEstimate(label=v[0], size_bytes=v[1], size_is_estimate=v[2], note=v[3])
                       for k, v in i.estimates.items()},
            error=ErrorBody(**i.error.body()) if i.error else None,
        ) for i in bulk.items],
    )


class UrlBatchCreate(BaseModel):
    """A bulk download of analysed X or TikTok videos (``analysis_ids`` from a bulk analysis, in order)."""

    model_config = ConfigDict(extra="forbid")

    platform: Literal["x", "tiktok"]
    analysis_ids: list[Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]] = Field(min_length=1,
                                                                                            max_length=100)
    quality: Literal["best", "1080p", "720p", "480p"] = "best"
    output: Literal["files", "zip"] = "zip"
    concurrency: int = Field(default=2, ge=1, le=4)
    allow_partial: bool = False


class BatchEpisodeResponse(BaseModel):
    number: int
    item_id: str
    title: str | None
    state: str
    stage: str | None
    percent: float | None
    downloaded_bytes: int
    total_bytes: int | None
    option_label: str | None
    note: str | None
    attempts: int
    file_id: str | None
    filename: str | None
    size_bytes: int | None
    download_url: str | None
    error: ErrorBody | None
    # Link batches (v1.9)
    author: str | None = None
    duration_seconds: float | None = None
    thumbnail_url: str | None = None


class BatchResultResponse(BaseModel):
    file_id: str
    filename: str
    size_bytes: int
    kind: str
    method: str | None
    reason: str | None
    duration_seconds: float | None
    included: list[int]
    omitted: list[int]
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None
    download_url: str | None
    delivery_state: str | None


class BatchResponse(BaseModel):
    batch_id: str
    source: str = "shortdrama"  # "shortdrama" | "urls"
    platform: str = "tiktok_shortdrama"
    stopped: bool = False  # links: cancelled, finished videos kept
    series_id: str
    series_title: str | None
    quality: str
    strict: bool
    concurrency: int
    output: str
    allow_partial: bool
    state: str
    stage: str | None
    plan_note: str | None
    package_percent: float
    counts: dict[str, int]
    percent: float
    estimated_duration_seconds: float | None
    estimated_size_bytes: int | None
    episodes: list[BatchEpisodeResponse]
    result: BatchResultResponse | None = None
    error: ErrorBody | None = None


def batch_to_response(batch, deliveries=None) -> BatchResponse:
    from .batches import BatchState, EpisodeState

    eps = batch.episodes
    counts = {s.value: sum(1 for e in eps if e.state == s) for s in EpisodeState}
    weights = {EpisodeState.SAVED: 1.0, EpisodeState.DOWNLOADED: 1.0, EpisodeState.FAILED: 1.0,
               EpisodeState.SKIPPED: 1.0, EpisodeState.CANCELLED: 1.0, EpisodeState.SAVING: 0.95,
               EpisodeState.READY: 0.9, EpisodeState.PROCESSING: 0.85}
    done = sum(weights.get(e.state, 0.8 * (e.percent or 0) / 100) for e in eps) / len(eps) if eps else 1.0
    if batch.output in ("zip", "merge"):
        stage_share = {BatchState.PACKAGING: 0.8 + 0.15 * batch.package_percent / 100, BatchState.READY: 0.97,
                       BatchState.SAVING: 0.98, BatchState.COMPLETED: 1.0, BatchState.PARTIAL: 1.0}
        percent = stage_share.get(batch.state, 0.8 * done)
    else:
        percent = done
    summary = ErrorBody(**batch.error.body()) if batch.error else None
    noun = "video" if batch.source == "urls" else "episode"
    if summary is None and batch.state == BatchState.PARTIAL:
        bad = [e.number for e in eps if e.state in (EpisodeState.FAILED, EpisodeState.SKIPPED, EpisodeState.CANCELLED)]
        ok = counts["saved"] if batch.output == "files" else len(batch.result.included) if batch.result else 0
        summary = ErrorBody(code="batch_partial", retryable=True, action=f"Retry the failed {noun}s individually.",
                            message=f"{ok} of {len(eps)} {noun}s were saved; {noun}(s) "
                                    f"{', '.join(map(str, bad[:20]))} weren't.")
    elif summary is None and batch.state == BatchState.CANCELLED:
        summary = ErrorBody(code="batch_cancelled", retryable=False, action="Start a new batch to continue.",
                            message="The batch was cancelled. Unsaved and collected files were deleted.")
    durations = [e.duration_seconds for e in eps if e.state not in (EpisodeState.SKIPPED,)]
    sizes = [e.size_bytes or e.expected_bytes for e in eps if e.state not in (EpisodeState.SKIPPED,)]
    result = None
    if batch.result is not None:
        r = batch.result
        d = deliveries.status(r.file_id) if deliveries is not None else None
        result = BatchResultResponse(
            file_id=r.file_id, filename=r.filename, size_bytes=r.size_bytes, kind=r.kind, method=r.method,
            reason=r.reason, duration_seconds=r.duration_seconds, included=r.included, omitted=r.omitted,
            width=r.width, height=r.height, video_codec=r.video_codec, audio_codec=r.audio_codec,
            download_url=f"/api/files/{r.file_id}" if batch.state in (BatchState.READY, BatchState.SAVING) else None,
            delivery_state=d.state.value if d else None,
        )
    return BatchResponse(
        batch_id=batch.batch_id, source=batch.source, platform=batch.platform, stopped=batch.stopped,
        series_id=batch.series_id, series_title=batch.series_title, quality=batch.quality,
        strict=batch.strict, concurrency=batch.concurrency, output=batch.output, allow_partial=batch.allow_partial,
        state=batch.state.value, stage=batch.stage, plan_note=batch.plan_note, package_percent=batch.package_percent,
        counts=counts, percent=round(100 * percent, 1),
        estimated_duration_seconds=sum(durations) if durations and None not in durations else None,
        estimated_size_bytes=sum(sizes) if sizes and None not in sizes else None,
        episodes=[BatchEpisodeResponse(
            number=e.number, item_id=e.item_id, title=e.title, state=e.state.value, stage=e.stage, percent=e.percent,
            downloaded_bytes=e.downloaded_bytes, total_bytes=e.total_bytes, option_label=e.option_label, note=e.note,
            attempts=e.attempts, file_id=e.file_id, filename=e.filename, size_bytes=e.size_bytes,
            download_url=f"/api/files/{e.file_id}" if e.file_id and e.state.value in ("ready", "saving") else None,
            error=ErrorBody(**e.error.body()) if e.error else None,
            author=e.author, duration_seconds=e.duration_seconds, thumbnail_url=e.thumbnail_url,
        ) for e in eps],
        result=result,
        error=summary,
    )
