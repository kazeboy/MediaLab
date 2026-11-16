"""Convert yt-dlp info dictionaries into provider-agnostic models.

Only values present in the yt-dlp output are used. The one derived value is
``filesize_approx`` = bitrate x duration, which yt-dlp itself also computes and
which is always exposed as *approximate*.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..errors import AppError, ErrorCode
from ..models import MediaFormat, PostMetadata, VideoEntry
from ..selection import format_mp4_compatibility
from ..validation import ValidatedUrl, is_allowed_media_url

ALLOWED_PROTOCOLS = frozenset({"https", "http", "m3u8", "m3u8_native"})

HostCheck = Callable[[str | None], bool]


def host_check(allowed: HostCheck | tuple[str, ...]) -> HostCheck:
    """Accept either a predicate or a tuple of allowed domain suffixes."""
    if callable(allowed):
        return allowed
    return lambda url: is_allowed_media_url(url, allowed)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return None


def _str(value: Any, limit: int = 10_000) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _codec(value: Any) -> str | None:
    """yt-dlp uses 'none' for an absent stream and None for unknown."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def _ext_and_protocol(fmt: dict[str, Any]) -> tuple[str | None, str | None]:
    ext = _str(fmt.get("ext"), 16)
    protocol = _str(fmt.get("protocol"), 32)
    if ext is None or protocol is None:
        # Unprocessed formats lack these; derive them the way yt-dlp does.
        from yt_dlp.utils import determine_ext, determine_protocol

        url = fmt.get("url") or ""
        if ext is None:
            ext = determine_ext(url, default_ext=None) or None
        if protocol is None:
            protocol = determine_protocol({"url": url, **fmt})
    return ext, protocol


def is_safe_format(fmt: dict[str, Any], host_suffixes: HostCheck | tuple[str, ...]) -> bool:
    """Check a raw yt-dlp format points at an allowlisted media host."""
    if not isinstance(fmt, dict) or not _str(fmt.get("format_id"), 128):
        return False
    allowed = host_check(host_suffixes)
    if not allowed(fmt.get("url")):
        return False
    manifest = fmt.get("manifest_url")
    if manifest and not allowed(manifest):
        return False
    _, protocol = _ext_and_protocol(fmt)
    return protocol in ALLOWED_PROTOCOLS


def normalise_format(fmt: dict[str, Any], duration: float | None) -> MediaFormat:
    ext, protocol = _ext_and_protocol(fmt)
    vcodec = _codec(fmt.get("vcodec"))
    acodec = _codec(fmt.get("acodec"))
    width, height = _int(fmt.get("width")), _int(fmt.get("height"))

    has_video: bool | None
    if vcodec == "none":
        has_video = False
    elif vcodec is not None or width or height:
        has_video = True
    else:
        has_video = None

    has_audio: bool | None
    if acodec == "none":
        has_audio = False
    elif acodec is not None:
        has_audio = True
    else:
        has_audio = None

    tbr = _float(fmt.get("tbr"))
    filesize = _int(fmt.get("filesize"))
    filesize_approx = _int(fmt.get("filesize_approx"))
    if filesize is None and filesize_approx is None and tbr and duration:
        filesize_approx = int(tbr * 1000 / 8 * duration)

    fps = _float(fmt.get("fps"))
    media = MediaFormat(
        format_id=str(fmt["format_id"])[:128],
        ext=ext,
        protocol=protocol,
        width=width,
        height=height,
        fps=fps if fps else None,
        vcodec=None if vcodec == "none" else vcodec,
        acodec=None if acodec == "none" else acodec,
        has_video=has_video,
        has_audio=has_audio,
        tbr=tbr,
        filesize=filesize,
        filesize_approx=filesize_approx if filesize is None else None,
    )
    return media.model_copy(update={"mp4_compatible": format_mp4_compatibility(media)})


def _thumbnail(entry: dict[str, Any], host_suffixes: HostCheck | tuple[str, ...]) -> str | None:
    allowed = host_check(host_suffixes)
    candidates: list[str] = []
    if isinstance(entry.get("thumbnail"), str):
        candidates.append(entry["thumbnail"])
    thumbs = entry.get("thumbnails")
    if isinstance(thumbs, list):
        # yt-dlp orders thumbnails worst -> best.
        candidates.extend(t.get("url") for t in reversed(thumbs) if isinstance(t, dict) and isinstance(t.get("url"), str))
    for url in candidates:
        if allowed(url):
            return url
    return None


def _entries(info: dict[str, Any]) -> list[dict[str, Any]]:
    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        return [e for e in entries if isinstance(e, dict) and e.get("_type", "video") == "video"]
    return [info]


def normalise_info(info: dict[str, Any], url: ValidatedUrl, host_suffixes: HostCheck | tuple[str, ...]) -> PostMetadata:
    """Build :class:`PostMetadata` from a (processed or raw) yt-dlp info dict."""
    if not isinstance(info, dict):
        raise AppError(ErrorCode.EXTRACTION_FAILED, "The extractor returned no usable data.")

    videos: list[VideoEntry] = []
    for position, entry in enumerate(_entries(info), start=1):
        duration = _float(entry.get("duration"))
        raw_formats = entry.get("formats")
        if not isinstance(raw_formats, list):
            raw_formats = [entry] if entry.get("url") and entry.get("format_id") else []
        formats = [normalise_format(f, duration) for f in raw_formats if is_safe_format(f, host_suffixes)]
        formats = [f for f in formats if f.has_video is not False or f.has_audio]
        if not any(f.has_video is not False for f in formats):
            continue
        videos.append(
            VideoEntry(
                index=position,
                video_id=_str(entry.get("id"), 64),
                title=_str(entry.get("title"), 500),
                duration_seconds=duration,
                thumbnail_url=_thumbnail(entry, host_suffixes),
                formats=tuple(formats),
            )
        )

    if not videos:
        raise AppError(ErrorCode.NO_VIDEO, "No downloadable video was found in this post.")

    first = _entries(info)[0] if _entries(info) else info
    if url.platform in ("tiktok", "tiktok_shortdrama"):
        # yt-dlp TikTok: "uploader" is the @handle, "channel"/"creator" the display name,
        # "uploader_id" a numeric account ID (not shown to users).
        author_name = _str(first.get("channel"), 200) or _str(first.get("creator"), 200)
        author_handle = _str(first.get("uploader"), 64) or url.handle
    else:
        author_name = _str(info.get("uploader"), 200) or _str(first.get("uploader"), 200)
        author_handle = _str(info.get("uploader_id"), 64) or _str(first.get("uploader_id"), 64)
    text = _str(info.get("description")) or _str(first.get("description"))

    return PostMetadata(
        url=url.canonical_url,
        post_id=url.post_id,
        author_name=author_name,
        author_handle=author_handle,
        text=text,
        videos=tuple(videos),
    )
