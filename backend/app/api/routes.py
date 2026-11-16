"""HTTP API routes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from ..errors import AppError, ErrorCode
from ..jobs import DownloadPlan
from ..schemas import (
    AnalyseRequest,
    AnalyseResponse,
    DownloadRequest,
    ErrorResponse,
    FileSizeLimits,
    JobResponse,
    PostInfo,
    SettingsResponse,
    TempStorageInfo,
    TikTokAccountResponse,
    TikTokAccountUpload,
    BatchCreate,
    BatchResponse,
    BulkCreate,
    BulkResponse,
    SeriesResponse,
    UrlBatchCreate,
    batch_to_response,
    bulk_to_response,
    VideoResult,
    job_to_response,
)
from ..selection import apply_size_limit, build_options, resolve_option
from ..services import Services, get_services
from ..storage import build_filename, directory_usage_bytes, ensure_free_space, episode_filename, is_valid_id
from ..user_settings import (
    BATCH_OUTPUT_PRESETS_MB,
    FILE_SIZE_PRESETS_MB,
    MAX_BATCH_OUTPUT_MB,
    MAX_FILE_SIZE_MB,
    MIN_FILE_SIZE_MB,
    SettingsPatch,
)
from ..bulk import resolve_validated
from ..validation import validate_post_url
from .delivery import DeliveryResponse

router = APIRouter(prefix="/api")

_ERRORS = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    410: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
}


@router.post("/analyse", response_model=AnalyseResponse, responses=_ERRORS)
async def analyse(body: AnalyseRequest, services: Services = Depends(get_services)) -> AnalyseResponse:
    validated = validate_post_url(body.url, body.platform)
    timeout = services.settings.socket_timeout_seconds

    def run():
        # Resolve share links first so the link is routed (and tab-checked) by what it really points to.
        url = resolve_validated(validated, body.platform, timeout)
        return url, services.provider.extract(url)

    if services.analysis_slots.locked():
        raise AppError(ErrorCode.BUSY, "MediaLab is already analysing several videos. Try again in a moment.")
    await services.analysis_slots.acquire()
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(services.analysis_executor, run)
    # The slot is released when the extractor thread really finishes, even on timeout.
    future.add_done_callback(lambda _: services.analysis_slots.release())
    try:
        validated, post = await asyncio.wait_for(
            asyncio.shield(future), timeout=services.settings.analysis_timeout_seconds
        )
    except asyncio.TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "Analysing the video took too long. Please try again.") from exc

    # Options are stored without a size limit and re-evaluated against the
    # current setting whenever they are shown or used.
    base_options = {video.index: build_options(video) for video in post.videos}
    stored = services.analyses.put(validated, post, base_options, post.provider or services.provider.name)
    limit = services.settings_store.get().max_file_size_bytes

    indices = [v.index for v in post.videos]
    selected = validated.video_index if validated.video_index in indices else indices[0]
    return AnalyseResponse(
        analysis_id=stored.analysis_id,
        platform=validated.platform,
        provider=stored.provider,
        post=PostInfo(
            url=post.url,
            post_id=post.post_id,
            author_name=post.author_name,
            author_handle=post.author_handle,
            text=post.text,
            possibly_sensitive=post.possibly_sensitive,
            drama=post.drama,
        ),
        videos=[
            VideoResult(
                index=v.index,
                video_id=v.video_id,
                title=v.title,
                duration_seconds=v.duration_seconds,
                thumbnail_url=v.thumbnail_url,
                formats=list(v.formats),
                options=apply_size_limit(base_options[v.index], limit),
            )
            for v in post.videos
        ],
        selected_video_index=selected,
        expires_at=datetime.fromtimestamp(stored.expires_at, tz=timezone.utc),
    )


@router.post(
    "/download", response_model=JobResponse, status_code=202,
    responses={**_ERRORS, 413: {"model": ErrorResponse}, 507: {"model": ErrorResponse}},
)
def download(body: DownloadRequest, services: Services = Depends(get_services)) -> JobResponse:
    analysis = services.analyses.get(body.analysis_id)
    video = analysis.video(body.video_index)
    user = services.settings_store.get()
    options = apply_size_limit(analysis.options.get(video.index, []), user.max_file_size_bytes)
    option = resolve_option(options, body.option_id)

    if analysis.provider == "fxtwitter" and not user.fxtwitter_fallback:
        raise AppError(ErrorCode.FORBIDDEN, "The FxTwitter fallback was turned off in Settings. Analyse the post again.")
    if not services.processor.available():
        raise AppError(
            ErrorCode.FFMPEG_MISSING,
            "FFmpeg/FFprobe were not found. Install them (e.g. `brew install ffmpeg`) and restart MediaLab.",
        )

    expected_total = option.known_size
    if expected_total is not None:
        ensure_free_space(services.settings.temp_dir, expected_total, services.settings.min_free_space_mb * 1024 * 1024)

    formats = {f.format_id: f for f in video.formats}
    expected = {
        fid: (formats[fid].filesize or formats[fid].filesize_approx) if fid in formats else None
        for fid in option.format_ids
    }
    label = analysis.url.platform_label
    plan = DownloadPlan(
        url=analysis.url,
        video_index=video.index,
        option=option,
        filename=(episode_filename(analysis.post.drama.series_title, analysis.post.drama.episode,
                                   analysis.post.drama.episode_count)
                  if analysis.post.drama and analysis.post.drama.episode
                  else build_filename(analysis.post, video, option, len(analysis.post.videos), label)),
        expected_sizes=expected,
        provider=analysis.provider,
        max_file_size_bytes=user.max_file_size_bytes,  # frozen for this job
        platform_label=label,
    )
    return job_to_response(services.jobs.submit(plan))


@router.get("/jobs/{job_id}", response_model=JobResponse, responses=_ERRORS)
def get_job(job_id: str, services: Services = Depends(get_services)) -> JobResponse:
    if not is_valid_id(job_id):
        raise AppError(ErrorCode.JOB_NOT_FOUND, "Download job not found.")
    snap = services.jobs.get(job_id)
    delivery = services.deliveries.status(snap.result.file_id) if snap.result else None
    return job_to_response(snap, delivery)


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse, responses=_ERRORS)
def cancel_job(job_id: str, services: Services = Depends(get_services)) -> JobResponse:
    """Cancel a queued, downloading or processing job. Idempotent.

    The job is ``cancelled`` at once; the transfer stops at its next progress update, a running
    FFmpeg is killed and the temporary folder is removed. A finished job is unchanged.
    """
    if not is_valid_id(job_id):
        raise AppError(ErrorCode.JOB_NOT_FOUND, "Download job not found.")
    services.jobs.get(job_id)  # 404 if unknown
    services.jobs.cancel(job_id, AppError(ErrorCode.DOWNLOAD_CANCELLED, "The download was cancelled.", retryable=False))
    snap = services.jobs.get(job_id)
    delivery = services.deliveries.status(snap.result.file_id) if snap.result else None
    return job_to_response(snap, delivery)


@router.get(
    "/files/{file_id}",
    response_class=DeliveryResponse,
    status_code=200,  # DeliveryResponse.__init__ has no status_code, so FastAPI can't infer it for /openapi.json
    responses={200: {"content": {"video/mp4": {}}}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def get_file(file_id: str, services: Services = Depends(get_services)) -> DeliveryResponse:
    """Stream a finished MP4 once; MediaLab deletes its temporary copy after a complete transfer."""
    item = services.deliveries.begin(file_id)  # raises 404/409; marks the file as delivering
    return DeliveryResponse(item, lambda completed: services.deliveries.finish(file_id, completed))


def _settings_response(services: Services) -> SettingsResponse:
    current = services.settings_store.get()
    return SettingsResponse(
        fxtwitter_fallback=current.fxtwitter_fallback,
        max_file_size_mb=current.max_file_size_mb,
        file_size_limits=FileSizeLimits(
            min_mb=MIN_FILE_SIZE_MB, max_mb=MAX_FILE_SIZE_MB, presets_mb=list(FILE_SIZE_PRESETS_MB)
        ),
        batch_output_max_mb=current.batch_output_max_mb,
        batch_output_limits=FileSizeLimits(
            min_mb=MIN_FILE_SIZE_MB, max_mb=MAX_BATCH_OUTPUT_MB, presets_mb=list(BATCH_OUTPUT_PRESETS_MB)
        ),
        temp_storage=TempStorageInfo(
            retention_minutes=services.settings.delivery_retention_seconds // 60,
            usage_bytes=directory_usage_bytes(services.settings.temp_dir),
        ),
        saved=services.settings_store.persisted,
    )


@router.get("/settings", response_model=SettingsResponse)
def get_settings(services: Services = Depends(get_services)) -> SettingsResponse:
    return _settings_response(services)


@router.patch("/settings", response_model=SettingsResponse, responses={422: {"model": ErrorResponse}})
def update_settings(body: SettingsPatch, services: Services = Depends(get_services)) -> SettingsResponse:
    """Change GUI settings. Takes effect immediately for new analyses and new jobs."""
    try:
        services.settings_store.update(body)
    except OSError as exc:
        raise AppError(ErrorCode.INTERNAL_ERROR, "Could not save the settings file.") from exc
    return _settings_response(services)


# ------------------------------------------------- TikTok account (Short Drama)
def _account_response(services: Services) -> TikTokAccountResponse:
    st = services.tiktok_account.status()

    def ts(value: float | None) -> datetime | None:
        return datetime.fromtimestamp(value, tz=timezone.utc) if value else None

    return TikTokAccountResponse(
        linked=st.linked,
        cookie_count=st.cookie_count,
        session_expires_at=ts(st.session_expires_at),
        expired=st.expired,
        saved_at=ts(st.saved_at),
    )


@router.get("/tiktok-account", response_model=TikTokAccountResponse)
def get_tiktok_account(services: Services = Depends(get_services)) -> TikTokAccountResponse:
    return _account_response(services)


@router.put("/tiktok-account", response_model=TikTokAccountResponse, responses={422: {"model": ErrorResponse}})
def link_tiktok_account(body: TikTokAccountUpload, services: Services = Depends(get_services)) -> TikTokAccountResponse:
    """Store the user's own tiktok.com cookies (Netscape cookies.txt) for the Short Drama tab only."""
    try:
        services.tiktok_account.save(body.cookies_txt)
    except OSError as exc:
        raise AppError(ErrorCode.INTERNAL_ERROR, "Could not save the TikTok sign-in file.") from exc
    return _account_response(services)


@router.delete("/tiktok-account", response_model=TikTokAccountResponse)
def unlink_tiktok_account(services: Services = Depends(get_services)) -> TikTokAccountResponse:
    services.tiktok_account.remove()
    return _account_response(services)


# --------------------------------------------------------- Short Drama series
def _batches(services: Services):
    if services.batches.provider is None:
        raise AppError(ErrorCode.UNSUPPORTED_URL, "Short Drama series aren't available in this configuration.")
    return services.batches


@router.get("/shortdrama/series/{series_id}", response_model=SeriesResponse, responses=_ERRORS)
async def get_series(series_id: str, services: Services = Depends(get_services)) -> SeriesResponse:
    """Episodes of a series as TikTok lists them for this viewer (uses the linked account, if any)."""
    if not series_id.isdigit() or not 5 <= len(series_id) <= 25:
        raise AppError(ErrorCode.INVALID_URL, "That isn't a valid Short Drama series ID.")
    manager = _batches(services)
    if services.analysis_slots.locked():
        raise AppError(ErrorCode.BUSY, "MediaLab is busy analysing other videos. Try again in a moment.")
    await services.analysis_slots.acquire()
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(services.analysis_executor, manager.provider.series, series_id)
    future.add_done_callback(lambda _: services.analysis_slots.release())
    try:
        info = await asyncio.wait_for(asyncio.shield(future), timeout=services.settings.analysis_timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "Loading the series took too long. Please try again.") from exc
    return SeriesResponse(**info.model_dump())


# ------------------------------------------------------ bulk links (v1.9)
def _bulk_id(bulk_id: str) -> str:
    if not is_valid_id(bulk_id):
        raise AppError(ErrorCode.BULK_NOT_FOUND, "This list of links is no longer available.")
    return bulk_id


@router.post("/bulk-analyses", response_model=BulkResponse, status_code=202, responses=_ERRORS)
def create_bulk_analysis(body: BulkCreate, services: Services = Depends(get_services)) -> BulkResponse:
    """Validate pasted links (one per line) and analyse each distinct one in the background."""
    return bulk_to_response(services.bulk.create(body.platform, body.urls))


@router.get("/bulk-analyses/{bulk_id}", response_model=BulkResponse, responses=_ERRORS)
def get_bulk_analysis(bulk_id: str, services: Services = Depends(get_services)) -> BulkResponse:
    return bulk_to_response(services.bulk.get(_bulk_id(bulk_id)))


@router.post("/bulk-analyses/{bulk_id}/cancel", response_model=BulkResponse, responses=_ERRORS)
def cancel_bulk_analysis(bulk_id: str, services: Services = Depends(get_services)) -> BulkResponse:
    return bulk_to_response(services.bulk.cancel(_bulk_id(bulk_id)))


@router.post("/batches", response_model=BatchResponse, status_code=202, responses=_ERRORS)
def create_url_batch(body: UrlBatchCreate, services: Services = Depends(get_services)) -> BatchResponse:
    """Download analysed X or TikTok videos as one queue (ZIP or separate files)."""
    if not services.processor.available():
        raise AppError(ErrorCode.FFMPEG_MISSING, "FFmpeg/FFprobe were not found. Install them and restart MediaLab.")
    if body.platform == "x" and any(services.analyses.get(a).provider == "fxtwitter" for a in body.analysis_ids) \
            and not services.settings_store.get().fxtwitter_fallback:
        raise AppError(ErrorCode.FORBIDDEN, "The FxTwitter fallback was turned off in Settings. Analyse the links again.")
    batch = services.batches.create_from_urls(body.platform, body.analysis_ids, body.quality, body.output,
                                              body.concurrency, body.allow_partial)
    return batch_to_response(batch, services.deliveries)


@router.post("/shortdrama/batches", response_model=BatchResponse, status_code=202, responses=_ERRORS)
async def create_batch(body: BatchCreate, services: Services = Depends(get_services)) -> BatchResponse:
    manager = _batches(services)
    if not services.processor.available():
        raise AppError(ErrorCode.FFMPEG_MISSING, "FFmpeg/FFprobe were not found. Install them and restart MediaLab.")
    loop = asyncio.get_running_loop()
    batch = await loop.run_in_executor(
        services.analysis_executor,
        lambda: manager.create(body.series_id, body.episodes, body.quality, body.strict, body.concurrency,
                               body.output, body.allow_partial),
    )
    return batch_to_response(batch, services.deliveries)


def _batch_id(batch_id: str) -> str:
    if not is_valid_id(batch_id):
        raise AppError(ErrorCode.BATCH_NOT_FOUND, "This batch no longer exists.")
    return batch_id


# Every batch (Short Drama or links) is reachable under /api/batches; the /api/shortdrama/batches
# paths from v1.4 to v1.8 stay as aliases.
@router.get("/batches/{batch_id}", response_model=BatchResponse, responses=_ERRORS)
@router.get("/shortdrama/batches/{batch_id}", response_model=BatchResponse, responses=_ERRORS)
def get_batch(batch_id: str, services: Services = Depends(get_services)) -> BatchResponse:
    return batch_to_response(services.batches.get(_batch_id(batch_id)), services.deliveries)


@router.post("/batches/{batch_id}/{action}", response_model=BatchResponse, responses=_ERRORS)
@router.post("/shortdrama/batches/{batch_id}/{action}", response_model=BatchResponse, responses=_ERRORS)
def control_batch(batch_id: str, action: str, services: Services = Depends(get_services)) -> BatchResponse:
    handlers = {"pause": services.batches.pause, "resume": services.batches.resume, "cancel": services.batches.cancel,
                "continue": services.batches.proceed}
    if action not in handlers:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown batch action.")
    return batch_to_response(handlers[action](_batch_id(batch_id)), services.deliveries)


@router.post("/batches/{batch_id}/items/{number}/{action}", response_model=BatchResponse, responses=_ERRORS)
@router.post("/shortdrama/batches/{batch_id}/episodes/{number}/{action}", response_model=BatchResponse,
             responses=_ERRORS)
def item_action(batch_id: str, number: int, action: str, services: Services = Depends(get_services)) -> BatchResponse:
    """``retry`` a failed, skipped or cancelled item, or ``cancel`` a waiting or running one."""
    handlers = {"retry": services.batches.retry, "cancel": services.batches.cancel_item}
    if action not in handlers:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown item action.")
    return batch_to_response(handlers[action](_batch_id(batch_id), number), services.deliveries)
