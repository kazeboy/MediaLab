"""FxTwitter (FxEmbed) metadata provider: an explicit, opt-in third-party fallback.

FxTwitter is an open-source (MIT) service with a documented public API
(https://docs.fxembed.com/api/introduction, spec: https://api.fxtwitter.com/2/openapi.json).
It returns post metadata and the direct MP4 variant URLs that X serves from
``video.twimg.com``.

Privacy: using this provider sends the **post ID** to ``api.fxtwitter.com``.
It is disabled unless ``MEDIALAB_FXTWITTER_FALLBACK=true``.

Access rules (enforced by MediaLab, not delegated):

* Only the post ID is sent; the request URL is built by MediaLab.
* Genuine access controls are respected: protected/private accounts, and
  deleted, suspended or blocked posts are reported as errors.
* ``possibly_sensitive`` is a *content classification*, not an access control.
  It is passed through as information only (and may be missing or wrong).
* No credentials or cookies are used, and video bytes are never proxied through
  FxTwitter: downloads go straight to X's CDN over https, with every redirect,
  the content type and the length validated (``app.net``).
* Only progressive MP4 variants are used (no re-encoding, no HLS assembly).
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..config import Settings
from ..errors import AppError, ErrorCode
from ..models import MediaFormat, PostMetadata, VideoEntry
from ..net import open_url
from ..retry import with_retries
from ..selection import format_mp4_compatibility
from ..validation import ValidatedUrl, is_allowed_media_url
from .base import ProgressCallback, ProgressUpdate, VideoProvider

log = logging.getLogger(__name__)

API_HOST = "api.fxtwitter.com"
API_URL = f"https://{API_HOST}/2/status/{{post_id}}"
MAX_API_BYTES = 2 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
_DIMENSIONS_RE = re.compile(r"/(\d{2,5})x(\d{2,5})/")
_CODECS = {"h264": "avc1", "hevc": "hvc1", "av1": "av01", "vp9": "vp09"}

# Tombstone reasons from the FxTwitter v2 spec (APIStatusTombstone.reason).
_TOMBSTONE_ERRORS = {
    "deleted": (ErrorCode.NOT_FOUND, "This post has been deleted."),
    "suspended": (ErrorCode.UNAVAILABLE, "This post's account is suspended."),
    "private": (ErrorCode.UNAVAILABLE, "This post is from a protected account. MediaLab does not access protected accounts."),
    "blocked": (ErrorCode.UNAVAILABLE, "This post is not accessible."),
    "unavailable": (ErrorCode.NOT_FOUND, "This post is unavailable."),
}


def _api_host_only(url: str) -> bool:
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        return False
    return parts.scheme == "https" and parts.hostname == API_HOST and port in (None, 443) and not parts.username


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


class FxTwitterProvider(VideoProvider):
    name = "fxtwitter"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _media_allowed(self, url: str) -> bool:
        return is_allowed_media_url(url, self.settings.media_host_suffixes)

    # ------------------------------------------------------------------ API
    # Injected in tests to avoid real waiting.
    retry_sleep = staticmethod(time.sleep)

    def _fetch_status(self, post_id: str) -> dict[str, Any]:
        # Transient network failures / timeouts: up to 3 attempts (1 s, 2 s backoff).
        return with_retries(lambda: self._fetch_status_once(post_id), what="FxTwitter lookup", sleep=self.retry_sleep)

    def _fetch_status_once(self, post_id: str) -> dict[str, Any]:
        if not post_id.isdigit():
            raise AppError(ErrorCode.INVALID_URL, "Invalid post ID.")
        resp = open_url(
            API_URL.format(post_id=post_id),
            _api_host_only,
            timeout=self.settings.socket_timeout_seconds,
            headers={"Accept": "application/json"},
        )
        with resp:
            status = getattr(resp, "status", None) or resp.getcode()
            raw = resp.read(MAX_API_BYTES + 1)
        if len(raw) > MAX_API_BYTES:
            raise AppError(ErrorCode.EXTRACTION_FAILED, "FxTwitter returned an unexpectedly large response.")
        if status == 429:
            raise AppError(ErrorCode.RATE_LIMITED, "FxTwitter is rate-limiting requests. Try again in a minute.")
        try:
            data = json.loads(raw or b"{}")
        except ValueError as exc:
            raise AppError(ErrorCode.EXTRACTION_FAILED, f"FxTwitter returned an invalid response (HTTP {status}).") from exc
        if not isinstance(data, dict):
            raise AppError(ErrorCode.EXTRACTION_FAILED, "FxTwitter returned an invalid response.")
        code = data.get("code") if isinstance(data.get("code"), int) else status
        if 404 in (code, status):
            raise AppError(ErrorCode.NOT_FOUND, "This post could not be found. It may have been deleted.")
        if 401 in (code, status):
            raise AppError(ErrorCode.UNAVAILABLE, "This post is from a protected account. MediaLab does not access protected accounts.")
        if status >= 500 or code >= 500:
            raise AppError(ErrorCode.EXTRACTION_FAILED, f"FxTwitter could not load this post (HTTP {status}).")
        if status >= 400 or code >= 400:
            raise AppError(ErrorCode.EXTRACTION_FAILED, f"FxTwitter rejected the request (HTTP {status}).")
        post = data.get("status")
        if not isinstance(post, dict):
            raise AppError(ErrorCode.EXTRACTION_FAILED, "FxTwitter returned no post data.")
        return post

    @staticmethod
    def _check_access(post: dict[str, Any]) -> None:
        """Enforce genuine access controls. Content classification is not one of them."""
        if post.get("type") == "tombstone":
            code, message = _TOMBSTONE_ERRORS.get(str(post.get("reason")), _TOMBSTONE_ERRORS["unavailable"])
            raise AppError(code, message)

    # ------------------------------------------------------------ normalise
    def _formats(self, video: dict[str, Any], duration: float | None) -> list[tuple[MediaFormat, str]]:
        """Return (format, media URL) pairs for the allowlisted progressive MP4 variants."""
        formats: list[tuple[MediaFormat, str]] = []
        seen: set[str] = set()
        for fmt in video.get("formats") or []:
            if not isinstance(fmt, dict) or fmt.get("container") != "mp4":
                continue  # HLS/WebM are not used by this provider
            url = fmt.get("url")
            if not isinstance(url, str) or not self._media_allowed(url):
                continue
            width, height = _num(fmt.get("width")), _num(fmt.get("height"))
            if not (width and height) and (m := _DIMENSIONS_RE.search(urlsplit(url).path)):
                width, height = float(m.group(1)), float(m.group(2))
            bitrate = _num(fmt.get("bitrate"))
            tbr = bitrate / 1000 if bitrate else None
            format_id = f"fx-mp4-{int(height) if height else 'x'}-{int(tbr) if tbr else len(formats)}"
            if format_id in seen:
                continue
            seen.add(format_id)
            size = _num(fmt.get("size"))
            codec = fmt.get("codec") if isinstance(fmt.get("codec"), str) else None
            media = MediaFormat(
                format_id=format_id,
                ext="mp4",
                protocol="https",
                width=int(width) if width else None,
                height=int(height) if height else None,
                vcodec=_CODECS.get(codec, codec) if codec else None,
                acodec=None,  # not reported; verified with ffprobe after download
                has_video=True,
                has_audio=None,
                tbr=tbr,
                filesize=int(size) if size else None,
                filesize_approx=int(tbr * 1000 / 8 * duration) if (not size and tbr and duration) else None,
            )
            formats.append((media.model_copy(update={"mp4_compatible": format_mp4_compatibility(media)}), url))
        return formats

    def _fill_exact_sizes(self, urls: dict[str, str], formats: list[MediaFormat]) -> list[MediaFormat]:
        """HEAD each MP4 on X's CDN for its exact size (no media is downloaded)."""
        out = []
        for fmt in formats:
            if fmt.filesize is None and fmt.format_id in urls:
                try:
                    resp = open_url(urls[fmt.format_id], self._media_allowed, method="HEAD",
                                    timeout=self.settings.socket_timeout_seconds)
                    with resp:
                        length = resp.headers.get("Content-Length")
                        if getattr(resp, "status", 200) == 200 and length and length.isdigit():
                            fmt = fmt.model_copy(update={"filesize": int(length), "filesize_approx": None})
                except AppError as exc:
                    log.debug("HEAD %s failed: %s", fmt.format_id, exc.message)
            out.append(fmt)
        return out

    def _videos(self, post: dict[str, Any], *, with_sizes: bool) -> tuple[list[VideoEntry], dict[tuple[int, str], str]]:
        entries: list[VideoEntry] = []
        urls: dict[tuple[int, str], str] = {}
        media = post.get("media") if isinstance(post.get("media"), dict) else {}
        for raw in media.get("videos") or []:
            if not isinstance(raw, dict) or raw.get("type") not in ("video", "gif"):
                continue
            duration = _num(raw.get("duration"))
            pairs = self._formats(raw, duration)
            if not pairs:
                continue
            index = len(entries) + 1
            by_id = {fmt.format_id: media_url for fmt, media_url in pairs}
            urls.update({(index, fid): media_url for fid, media_url in by_id.items()})
            formats = [fmt for fmt, _ in pairs]
            if with_sizes:
                formats = self._fill_exact_sizes(by_id, formats)
            thumb = raw.get("thumbnail_url")
            entries.append(
                VideoEntry(
                    index=index,
                    video_id=str(raw.get("id")) if raw.get("id") else None,
                    duration_seconds=duration,
                    thumbnail_url=thumb if isinstance(thumb, str) and self._media_allowed(thumb) else None,
                    formats=tuple(formats),
                )
            )
        return entries, urls

    # -------------------------------------------------------------- public
    def extract(self, url: ValidatedUrl) -> PostMetadata:
        post = self._fetch_status(url.post_id)
        self._check_access(post)
        videos, _ = self._videos(post, with_sizes=True)
        if not videos:
            raise AppError(ErrorCode.NO_VIDEO, "This post does not contain a downloadable video.")
        author = post.get("author") if isinstance(post.get("author"), dict) else {}
        text = post.get("text")
        sensitive = post.get("possibly_sensitive")
        return PostMetadata(
            url=url.canonical_url,
            post_id=url.post_id,
            author_name=(author.get("name") or None) if isinstance(author.get("name"), str) else None,
            author_handle=(author.get("screen_name") or None) if isinstance(author.get("screen_name"), str) else None,
            text=(text.strip()[:10_000] or None) if isinstance(text, str) else None,
            videos=tuple(videos),
            provider=self.name,
            possibly_sensitive=sensitive if isinstance(sensitive, bool) else None,
        )

    def download(
        self,
        url: ValidatedUrl,
        video_index: int,
        format_ids: list[str],
        dest_dir: Path,
        on_progress: ProgressCallback,
    ) -> dict[str, Path]:
        # Re-resolve from the API so only URLs MediaLab validated itself are used.
        post = self._fetch_status(url.post_id)
        self._check_access(post)
        _, urls = self._videos(post, with_sizes=False)
        outputs: dict[str, Path] = {}
        for fid in format_ids:
            media_url = urls.get((video_index, fid))
            if media_url is None:
                raise AppError(ErrorCode.FORMAT_UNAVAILABLE, "The selected format is no longer offered. Analyse the post again.")
            outputs[fid] = self._stream(media_url, fid, dest_dir, on_progress)
        return outputs

    def _stream(self, media_url: str, fid: str, dest_dir: Path, on_progress: ProgressCallback) -> Path:
        target = dest_dir / f"{fid}.mp4"
        partial = dest_dir / f"{fid}.mp4.part"
        resp = open_url(media_url, self._media_allowed, timeout=self.settings.socket_timeout_seconds)
        with resp:
            status = getattr(resp, "status", None) or resp.getcode()
            if status != 200:
                raise AppError(ErrorCode.DOWNLOAD_FAILED, f"X's media server refused the download (HTTP {status}).")
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if not (ctype.startswith("video/") or ctype == "application/octet-stream"):
                raise AppError(ErrorCode.DOWNLOAD_FAILED, f"Unexpected content type from the media server: {ctype or 'none'}.")
            length = resp.headers.get("Content-Length")
            total = int(length) if length and length.isdigit() else None
            done = 0
            with open(partial, "wb") as fh:
                while chunk := resp.read(CHUNK_BYTES):
                    fh.write(chunk)
                    done += len(chunk)
                    # May raise (size/time limit) to abort; the job manager cleans up.
                    on_progress(ProgressUpdate(fid, "downloading", done, total, total is None))
        if total is not None and done != total:
            raise AppError(ErrorCode.DOWNLOAD_FAILED, "The download was interrupted (incomplete file).")
        partial.replace(target)
        on_progress(ProgressUpdate(fid, "finished", done, done, False))
        return target
