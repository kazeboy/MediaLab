"""Typed application errors.

Every error that reaches the API is an :class:`AppError` with:

* ``code``: stable, machine-readable;
* ``message``: what happened, stated only as far as it was actually established;
* ``action``: what the user can do about it (defaults per code);
* ``retryable``: whether simply trying again may help;
* ``details``: optional small machine-readable extras (e.g. a detected platform).

Internal details (stack traces, local paths, raw extractor output) are logged
server-side as diagnostics and never sent to clients.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    # URL input, validation, platform detection
    INVALID_URL = "invalid_url"
    UNSUPPORTED_URL = "unsupported_url"
    WRONG_PLATFORM = "wrong_platform"
    UNSUPPORTED_EPISODE_URL = "unsupported_episode_url"
    SHORT_LINK_EXPIRED = "short_link_expired"
    EPISODE_RESOLUTION_FAILED = "episode_resolution_failed"
    EPISODE_NOT_IN_SERIES = "episode_not_in_series"
    SERIES_METADATA_UNAVAILABLE = "series_metadata_unavailable"
    # Metadata extraction / access
    NO_VIDEO = "no_video"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    LOGIN_REQUIRED = "login_required"
    ACCOUNT_ACCESS_UNAVAILABLE = "account_access_unavailable"
    AUTH_EXPIRED = "auth_expired"
    PROTECTED_CONTENT = "protected_content"
    REGION_RESTRICTED = "region_restricted"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    EXTRACTION_FAILED = "extraction_failed"
    MEDIA_HOST_BLOCKED = "media_host_blocked"
    # Formats / selection
    ANALYSIS_EXPIRED = "analysis_expired"
    INVALID_SELECTION = "invalid_selection"
    FORMAT_UNAVAILABLE = "format_unavailable"
    INCOMPATIBLE_FORMAT = "incompatible_format"
    PREFERRED_RESOLUTION_UNAVAILABLE = "preferred_resolution_unavailable"
    FILE_TOO_LARGE = "file_too_large"
    INSUFFICIENT_SPACE = "insufficient_space"
    TOO_MANY_JOBS = "too_many_jobs"
    ALREADY_DOWNLOADING = "already_downloading"
    # Download / processing
    CDN_URL_EXPIRED = "cdn_url_expired"
    DOWNLOAD_INTERRUPTED = "download_interrupted"
    DOWNLOAD_FAILED = "download_failed"
    DOWNLOAD_CANCELLED = "download_cancelled"
    PROCESSING_FAILED = "processing_failed"
    AUDIO_MISSING = "audio_missing"
    AUDIO_CONVERSION_FAILED = "audio_conversion_failed"
    AV_SYNC_FAILED = "av_sync_failed"
    MP4_COMPATIBILITY = "mp4_compatibility"
    MERGE_INCOMPATIBLE = "merge_incompatible"
    MERGE_FAILED = "merge_failed"
    TRANSCODE_FAILED = "transcode_failed"
    ZIP_FAILED = "zip_failed"
    BATCH_OUTPUT_TOO_LARGE = "batch_output_too_large"
    FFMPEG_MISSING = "ffmpeg_missing"
    # Delivery / misc
    JOB_NOT_FOUND = "job_not_found"
    FILE_NOT_FOUND = "file_not_found"
    DELIVERY_IN_PROGRESS = "delivery_in_progress"
    DELIVERY_INTERRUPTED = "delivery_interrupted"
    CLEANUP_FAILED = "cleanup_failed"
    BATCH_NOT_FOUND = "batch_not_found"
    BATCH_PARTIAL = "batch_partial"
    BATCH_CANCELLED = "batch_cancelled"
    BATCH_IN_PROGRESS = "batch_in_progress"
    ITEM_NOT_FOUND = "item_not_found"
    BULK_NOT_FOUND = "bulk_not_found"
    BUSY = "busy"
    VALIDATION_ERROR = "validation_error"
    FORBIDDEN = "forbidden"
    INTERNAL_ERROR = "internal_error"


_DEFAULT_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_URL: 400,
    ErrorCode.UNSUPPORTED_URL: 400,
    ErrorCode.WRONG_PLATFORM: 400,
    ErrorCode.UNSUPPORTED_EPISODE_URL: 400,
    ErrorCode.SHORT_LINK_EXPIRED: 404,
    ErrorCode.EPISODE_RESOLUTION_FAILED: 502,
    ErrorCode.EPISODE_NOT_IN_SERIES: 404,
    ErrorCode.SERIES_METADATA_UNAVAILABLE: 502,
    ErrorCode.NO_VIDEO: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.UNAVAILABLE: 403,
    ErrorCode.LOGIN_REQUIRED: 403,
    ErrorCode.ACCOUNT_ACCESS_UNAVAILABLE: 403,
    ErrorCode.AUTH_EXPIRED: 401,
    ErrorCode.PROTECTED_CONTENT: 403,
    ErrorCode.REGION_RESTRICTED: 451,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.NETWORK_ERROR: 502,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.EXTRACTION_FAILED: 502,
    ErrorCode.MEDIA_HOST_BLOCKED: 422,
    ErrorCode.ANALYSIS_EXPIRED: 410,
    ErrorCode.INVALID_SELECTION: 400,
    ErrorCode.FORMAT_UNAVAILABLE: 409,
    ErrorCode.INCOMPATIBLE_FORMAT: 422,
    ErrorCode.PREFERRED_RESOLUTION_UNAVAILABLE: 422,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.INSUFFICIENT_SPACE: 507,
    ErrorCode.TOO_MANY_JOBS: 429,
    ErrorCode.ALREADY_DOWNLOADING: 409,
    ErrorCode.CDN_URL_EXPIRED: 502,
    ErrorCode.DOWNLOAD_INTERRUPTED: 502,
    ErrorCode.DOWNLOAD_FAILED: 502,
    ErrorCode.DOWNLOAD_CANCELLED: 409,
    ErrorCode.PROCESSING_FAILED: 500,
    ErrorCode.AUDIO_MISSING: 502,
    ErrorCode.AUDIO_CONVERSION_FAILED: 500,
    ErrorCode.AV_SYNC_FAILED: 500,
    ErrorCode.MP4_COMPATIBILITY: 500,
    ErrorCode.MERGE_INCOMPATIBLE: 422,
    ErrorCode.MERGE_FAILED: 500,
    ErrorCode.TRANSCODE_FAILED: 500,
    ErrorCode.ZIP_FAILED: 500,
    ErrorCode.BATCH_OUTPUT_TOO_LARGE: 413,
    ErrorCode.FFMPEG_MISSING: 500,
    ErrorCode.JOB_NOT_FOUND: 404,
    ErrorCode.FILE_NOT_FOUND: 404,
    ErrorCode.DELIVERY_IN_PROGRESS: 409,
    ErrorCode.DELIVERY_INTERRUPTED: 409,
    ErrorCode.CLEANUP_FAILED: 500,
    ErrorCode.BATCH_NOT_FOUND: 404,
    ErrorCode.BATCH_PARTIAL: 207,
    ErrorCode.BATCH_CANCELLED: 409,
    ErrorCode.BATCH_IN_PROGRESS: 409,
    ErrorCode.ITEM_NOT_FOUND: 404,
    ErrorCode.BULK_NOT_FOUND: 404,
    ErrorCode.BUSY: 429,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.INTERNAL_ERROR: 500,
}

# Errors where simply trying again later may succeed.
RETRYABLE = frozenset({
    ErrorCode.RATE_LIMITED, ErrorCode.NETWORK_ERROR, ErrorCode.TIMEOUT, ErrorCode.CDN_URL_EXPIRED,
    ErrorCode.DOWNLOAD_INTERRUPTED, ErrorCode.BUSY, ErrorCode.TOO_MANY_JOBS, ErrorCode.DELIVERY_IN_PROGRESS,
    ErrorCode.EXTRACTION_FAILED, ErrorCode.FORMAT_UNAVAILABLE, ErrorCode.EPISODE_RESOLUTION_FAILED,
    ErrorCode.SERIES_METADATA_UNAVAILABLE, ErrorCode.DELIVERY_INTERRUPTED, ErrorCode.AUDIO_MISSING,
    ErrorCode.AUDIO_CONVERSION_FAILED, ErrorCode.AV_SYNC_FAILED, ErrorCode.BATCH_PARTIAL,
    ErrorCode.MERGE_FAILED, ErrorCode.TRANSCODE_FAILED, ErrorCode.ZIP_FAILED,
})

# Recommended next step per code (an AppError may override it).
DEFAULT_ACTIONS: dict[ErrorCode, str] = {
    ErrorCode.INVALID_URL: "Check the link, or paste it into the tab for its platform.",
    ErrorCode.UNSUPPORTED_URL: "Use a link to an individual X post or TikTok video.",
    ErrorCode.WRONG_PLATFORM: "Switch to the suggested tab.",
    ErrorCode.UNSUPPORTED_EPISODE_URL: "Open the episode on TikTok and copy its link from the address bar.",
    ErrorCode.SHORT_LINK_EXPIRED: "Ask for a fresh share link, or open the video and copy its full address.",
    ErrorCode.NOT_FOUND: "Check the link still opens in your browser.",
    ErrorCode.EPISODE_RESOLUTION_FAILED: "Try again, or paste the episode's share link (Share, then Copy link in TikTok).",
    ErrorCode.EPISODE_NOT_IN_SERIES: "Check the episode number; open the series on TikTok to see its episodes.",
    ErrorCode.SERIES_METADATA_UNAVAILABLE: "Try again later. Single episodes can still be downloaded from their share links.",
    ErrorCode.AUTH_EXPIRED: "Sign in to tiktok.com again, export the cookies and re-link the account in Settings.",
    ErrorCode.PREFERRED_RESOLUTION_UNAVAILABLE: "Choose Best Available, or turn off strict resolution.",
    ErrorCode.DELIVERY_INTERRUPTED: "Click Save again; the file is kept until it expires.",
    ErrorCode.CLEANUP_FAILED: "Check the MediaLab terminal; temporary files are removed again at the next start.",
    ErrorCode.BATCH_NOT_FOUND: "Start the batch again. Downloads can't be resumed after MediaLab restarts.",
    ErrorCode.BATCH_PARTIAL: "Retry the failed episodes individually.",
    ErrorCode.BATCH_CANCELLED: "Start a new batch to continue.",
    ErrorCode.ACCOUNT_ACCESS_UNAVAILABLE: (
        "Check that the episode plays for your account on tiktok.com. If it does, export your TikTok cookies "
        "again and re-link the account in Settings."
    ),
    ErrorCode.NO_VIDEO: "Check that the link points to a post with a video (not only images or text).",
    ErrorCode.UNAVAILABLE: "MediaLab only downloads publicly accessible content.",
    ErrorCode.INVALID_SELECTION: "Choose one of the listed resolutions.",
    ErrorCode.JOB_NOT_FOUND: "Start the download again.",
    ErrorCode.VALIDATION_ERROR: "Check the request and try again.",
    ErrorCode.FORBIDDEN: "Analyse the video again from the MediaLab page.",
    ErrorCode.INTERNAL_ERROR: "Try again. If it keeps happening, check the MediaLab terminal for details.",
    ErrorCode.LOGIN_REQUIRED: "MediaLab only downloads content available without signing in.",
    ErrorCode.PROTECTED_CONTENT: "This content can't be downloaded with MediaLab.",
    ErrorCode.REGION_RESTRICTED: "This is decided by the platform; MediaLab doesn't work around region limits.",
    ErrorCode.RATE_LIMITED: "Wait a few minutes, then try again.",
    ErrorCode.NETWORK_ERROR: "Check your internet connection, then try again.",
    ErrorCode.TIMEOUT: "Try again. If it keeps happening, check your connection.",
    ErrorCode.EXTRACTION_FAILED: "Try again later. If it persists, update yt-dlp (make update-ytdlp).",
    ErrorCode.MEDIA_HOST_BLOCKED: "No action available: MediaLab only downloads from the platform's own media servers.",
    ErrorCode.ANALYSIS_EXPIRED: "Click Analyse again.",
    ErrorCode.FORMAT_UNAVAILABLE: "Click Analyse again and choose a resolution.",
    ErrorCode.INCOMPATIBLE_FORMAT: "Choose another resolution, if one is available.",
    ErrorCode.FILE_TOO_LARGE: "Raise the maximum file size in Settings, or choose a smaller resolution.",
    ErrorCode.INSUFFICIENT_SPACE: "Free up disk space or choose a smaller resolution.",
    ErrorCode.TOO_MANY_JOBS: "Wait for current downloads to finish.",
    ErrorCode.ALREADY_DOWNLOADING: "Open Downloads to follow the download that is already running.",
    ErrorCode.ITEM_NOT_FOUND: "Refresh the list; the item may have been removed.",
    ErrorCode.BULK_NOT_FOUND: "Paste the links and click Analyse again.",
    ErrorCode.CDN_URL_EXPIRED: "Start the download again; MediaLab will fetch fresh links.",
    ErrorCode.DOWNLOAD_INTERRUPTED: "Click Download MP4 to try again.",
    ErrorCode.DOWNLOAD_FAILED: "Try again. If it keeps failing, analyse the video again.",
    ErrorCode.DOWNLOAD_CANCELLED: "Click Download MP4 to start it again.",
    ErrorCode.PROCESSING_FAILED: "Try again or choose another resolution.",
    ErrorCode.AUDIO_MISSING: "Try again. If it keeps happening, choose another resolution.",
    ErrorCode.AUDIO_CONVERSION_FAILED: "Try again, or choose a resolution whose audio is already AAC.",
    ErrorCode.AV_SYNC_FAILED: "Try again, or choose another resolution.",
    ErrorCode.MP4_COMPATIBILITY: "Choose another resolution.",
    ErrorCode.MERGE_INCOMPATIBLE: "Retry the episode named in the message, or download the episodes as a ZIP instead.",
    ErrorCode.MERGE_FAILED: "Click Retry packaging. If it keeps failing, download the episodes as a ZIP instead.",
    ErrorCode.TRANSCODE_FAILED: "Click Retry packaging, or choose one quality for all episodes so no re-encoding is needed.",
    ErrorCode.ZIP_FAILED: "Click Retry packaging. Check the free disk space if it keeps failing.",
    ErrorCode.BATCH_OUTPUT_TOO_LARGE: "Raise the batch output limit in Settings, select fewer episodes or choose a lower quality.",
    ErrorCode.BATCH_IN_PROGRESS: "Wait for the existing batch for these episodes, or cancel it.",
    ErrorCode.FFMPEG_MISSING: "Install FFmpeg (brew install ffmpeg) and restart MediaLab.",
    ErrorCode.FILE_NOT_FOUND: "Click Download MP4 to fetch the video again.",
    ErrorCode.DELIVERY_IN_PROGRESS: "Wait for the current save to finish.",
    ErrorCode.BUSY: "Try again in a moment.",
}


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int | None = None,
        *,
        action: str | None = None,
        retryable: bool | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code or _DEFAULT_STATUS.get(code, 500)
        self.action = action if action is not None else DEFAULT_ACTIONS.get(code)
        self.retryable = retryable if retryable is not None else code in RETRYABLE
        self.details = details or None

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code.value, "message": self.message, "retryable": self.retryable}
        if self.action:
            out["action"] = self.action
        if self.details:
            out["details"] = self.details
        return out

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"AppError({self.code.value!r}, {self.message!r})"
