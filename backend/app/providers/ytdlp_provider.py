"""yt-dlp implementation of :class:`VideoProvider`.

Security notes:

* Only the platform's own yt-dlp extractor is loaded (``twitter`` for X,
  ``tiktok`` for TikTok via ``allowed_extractors``), so a post that links to
  external content cannot make yt-dlp fetch arbitrary URLs through the generic
  extractor.
* Extraction is run with ``process=False`` first; the raw result is inspected
  and every format whose URL is not on an allowlisted media host is dropped
  before yt-dlp is allowed to touch it.
* No cookies, browser profiles, ``.netrc`` credentials or cache are used.
"""

from __future__ import annotations

import logging
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from ..config import Settings
from ..errors import AppError, ErrorCode
from ..models import PostMetadata
from ..validation import (
    PLATFORM_TIKTOK,
    PLATFORM_X,
    ValidatedUrl,
    is_allowed_media_url,
    is_allowed_tiktok_media_url,
)
from ..retry import with_retries
from .base import ProgressCallback, ProgressUpdate, VideoProvider
from .ytdlp_normalise import is_safe_format, normalise_format, normalise_info

log = logging.getLogger(__name__)


class _YtDlpLogger:
    """Route yt-dlp output to Python logging instead of stdout."""

    def debug(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
        log.info("yt-dlp warning: %s", msg)

    def error(self, msg: str) -> None:
        log.info("yt-dlp error: %s", msg)


_PREFIX_RE = re.compile(r"^(?:ERROR:\s*)?(?:\[[^\]]+\]\s*)?(?:[\w-]+:\s+)?")

_Rule = tuple[tuple[str, ...], ErrorCode, str]

# TikTok-specific rules, checked before the shared ones.
_TIKTOK_RULES: tuple[_Rule, ...] = (
    (("ip address is blocked", "not available in your", "not available in this region", "geo restrict",
      "geo-restrict"), ErrorCode.REGION_RESTRICTED,
     "This video isn't available from your current region: TikTok blocked it for your location or IP address."),
    (("unexpected response from webpage", "impersonat"), ErrorCode.EXTRACTION_FAILED,
     "TikTok refused the request. MediaLab needs yt-dlp's browser-impersonation support: run `make setup` "
     "(installs yt-dlp[curl-cffi]) and update yt-dlp with `make update-ytdlp`."),
    (("video not available", "status code 10204", "item doesn't exist", "video has been removed"),
     ErrorCode.NOT_FOUND, "This TikTok video could not be found. It may have been deleted or made private."),
    (("no video could be found", "no formats found", "is not a video", "photo", "slideshow", "image post"),
     ErrorCode.NO_VIDEO,
     "No downloadable video was found. TikTok photo slideshows aren't supported; the video may also be "
     "private or deleted."),
    (("private", "log in", "login", "sign in", "age-restricted", "--cookies"), ErrorCode.LOGIN_REQUIRED,
     "TikTok only shows this video to signed-in users or approved followers. MediaLab supports public videos only."),
)

# Ordered: first match wins. "{label}" is replaced with the platform name.
_ERROR_RULES: tuple[_Rule, ...] = (
    (("drm protected", "drm-protected", "is drm"), ErrorCode.PROTECTED_CONTENT,
     "This video is DRM-protected and can't be downloaded with the available method."),
    (("not available in your country", "geo restriction", "geo-restricted", "not available in your location"),
     ErrorCode.REGION_RESTRICTED, "This video isn't available from your current region."),
    (("requested format is not available", "requested format not available"), ErrorCode.FORMAT_UNAVAILABLE,
     "The selected format is no longer offered by {label}. Analyse it again and pick a resolution."),
    # X returns the same response for a post without video and for a deleted/hidden post. For logged-out
    # clients X may answer with a bare "TweetTombstone" (no reason text), which yt-dlp also reports as
    # "No video could be found", so the cause cannot be distinguished here.
    (("no video could be found", "is not a video", "no formats found"), ErrorCode.NO_VIDEO,
     "No downloadable video was found. The post may not contain a video, may have been deleted, or may "
     "only be visible to signed-in X users (MediaLab supports public posts only)."),
    (("nsfw", "requires authentication", "login required", "log in", "sign in", "age-restricted", "--cookies"),
     ErrorCode.LOGIN_REQUIRED,
     "X only shows this post to signed-in users. MediaLab only supports publicly accessible posts."),
    (("suspended", "protected", "private"), ErrorCode.UNAVAILABLE,
     "This post is not publicly accessible (protected or suspended account)."),
    (("rate limit", "rate-limit", "429", "too many requests"), ErrorCode.RATE_LIMITED,
     "{label} is rate-limiting requests right now. Wait a few minutes and try again."),
    (("unavailable", "deleted", "does not exist", "not found", "404", "no status found"), ErrorCode.NOT_FOUND,
     "This post could not be found. It may have been deleted or is unavailable."),
    (("http error 403", "403: forbidden"), ErrorCode.CDN_URL_EXPIRED,
     "{label}'s media server refused the video link (HTTP 403), even after MediaLab fetched fresh links. "
     "Try again in a moment."),
    (("timed out", "timeout"), ErrorCode.TIMEOUT, "The request to {label} timed out. Please try again."),
    (("unable to download", "connection", "name or service not known", "nodename nor servname",
      "network is unreachable", "temporary failure in name resolution", "ssl", "remote end closed"),
     ErrorCode.NETWORK_ERROR, "Could not reach {label}. Check your internet connection and try again."),
    (("no suitable extractor", "unsupported url"), ErrorCode.UNSUPPORTED_URL,
     "This post links to content that MediaLab does not support."),
)


def map_ytdlp_error(exc: BaseException, *, during_download: bool = False, platform: str = PLATFORM_X) -> AppError:
    """Translate a yt-dlp exception into a user-facing :class:`AppError`."""
    if isinstance(exc, AppError):
        return exc
    raw = str(exc).strip() or exc.__class__.__name__
    lowered = raw.lower()
    label = "TikTok" if platform == PLATFORM_TIKTOK else "X"
    rules = (_TIKTOK_RULES + _ERROR_RULES) if platform == PLATFORM_TIKTOK else _ERROR_RULES
    for needles, code, message in rules:
        if any(n in lowered for n in needles):
            if during_download and code in (ErrorCode.NETWORK_ERROR, ErrorCode.TIMEOUT):
                return AppError(ErrorCode.DOWNLOAD_INTERRUPTED,
                                f"The download was interrupted ({'timed out' if code == ErrorCode.TIMEOUT else 'network problem'}"
                                f" while receiving the video from {label}). You can retry.")
            return AppError(code, message.replace("{label}", label))
    # Unrecognised: say what we know (the extractor failed) and keep yt-dlp's reason for diagnosis.
    detail = _PREFIX_RE.sub("", raw.splitlines()[0])[:200]
    if during_download:
        return AppError(ErrorCode.DOWNLOAD_FAILED, f"The download from {label} failed: {detail}")
    return AppError(ErrorCode.EXTRACTION_FAILED, f"MediaLab couldn't retrieve this video's details from {label}: {detail}")


def _keep_tiktok_format(fmt: dict[str, Any]) -> bool:
    note = str(fmt.get("format_note") or "").lower()
    return "unplayable" not in note  # bytevc2 streams yt-dlp marks as unplayable


@dataclass(frozen=True)
class PlatformSpec:
    platform: str
    label: str
    extractor: str
    media_allowed: Callable[[str | None], bool]
    keep_format: Callable[[dict[str, Any]], bool] = lambda fmt: True
    drop_watermarked: bool = False
    mirrored_formats: bool = False  # source lists the same format on several CDN nodes (<id>-0, <id>-1)


def platform_spec(settings: Settings, platform: str) -> PlatformSpec:
    if platform == PLATFORM_TIKTOK:
        return PlatformSpec(PLATFORM_TIKTOK, "TikTok", "tiktok", is_allowed_tiktok_media_url,
                            _keep_tiktok_format, drop_watermarked=True, mirrored_formats=True)
    return PlatformSpec(PLATFORM_X, "X", "twitter", partial(is_allowed_media_url, host_suffixes=settings.media_host_suffixes))


def _disambiguate_format_ids(formats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give duplicate format IDs the same ``<id>-<n>`` suffixes yt-dlp would.

    Some sources (e.g. TikTok's mirrored CDN nodes) repeat a format ID. yt-dlp
    only disambiguates while *processing*, so doing it here keeps the IDs seen at
    analysis time identical to the ones checked and requested at download time.
    """
    counts: dict[str, int] = {}
    for f in formats:
        counts[str(f.get("format_id"))] = counts.get(str(f.get("format_id")), 0) + 1
    seen: dict[str, int] = {}
    out = []
    for f in formats:
        fid = str(f.get("format_id"))
        if counts[fid] > 1:
            n = seen.get(fid, 0)
            seen[fid] = n + 1
            f = {**f, "format_id": f"{fid}-{n}"}
        out.append(f)
    return out


_MIRROR_RE = re.compile(r"^(?P<base>.+)-(?P<n>[01])$")


def _mirror_of(format_id: str) -> str:
    """``x-0`` <-> ``x-1`` (mirrored CDN copies); other IDs are retried as-is."""
    m = _MIRROR_RE.match(format_id)
    return f"{m['base']}-{1 - int(m['n'])}" if m else format_id


# TikTok format IDs embed a bitrate (e.g. "bytevc1_720p_517560-0") that can change between
# page loads when TikTok serves another encode of the same rendition.
_TIKTOK_ID_RE = re.compile(r"^(?P<codec>[a-z0-9]+)_(?P<res>[0-9]+p)_[0-9]+(?P<mirror>-[0-9]+)?$")


def equivalent_format_id(requested: str, available: list[str]) -> str | None:
    """Same codec, resolution and mirror as ``requested`` among ``available`` (or None)."""
    m = _TIKTOK_ID_RE.match(requested)
    if not m:
        return None
    for fid in available:
        n = _TIKTOK_ID_RE.match(fid)
        if n and (n["codec"], n["res"], n["mirror"]) == (m["codec"], m["res"], m["mirror"]):
            return fid
    return None


def _is_http_403(exc: AppError) -> bool:
    cause = str(exc.__cause__ or "").lower()
    return "http error 403" in cause or "403: forbidden" in cause


class YtDlpProvider(VideoProvider):
    name = "yt-dlp"

    def __init__(self, settings: Settings, platform: str = PLATFORM_X) -> None:
        self.settings = settings
        self.spec = platform_spec(settings, platform)

    # ------------------------------------------------------------------ params
    def _base_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _YtDlpLogger(),
            "allowed_extractors": [self.spec.extractor],
            "noplaylist": False,
            "socket_timeout": self.settings.socket_timeout_seconds,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 3,
            "cachedir": False,
            "usenetrc": False,
            "cookiefile": None,
            "cookiesfrombrowser": None,
            "check_formats": False,
            "writethumbnail": False,
            "writesubtitles": False,
            "writeinfojson": False,
            "updatetime": False,
            "overwrites": True,
            "color": {"stdout": "no_color", "stderr": "no_color"},
        }
        ffmpeg = shutil.which(self.settings.ffmpeg_path)
        if ffmpeg:
            params["ffmpeg_location"] = str(Path(ffmpeg).parent)
        return params

    def _ydl(self, extra: dict[str, Any] | None = None):
        from yt_dlp import YoutubeDL

        return YoutubeDL({**self._base_params(), **(extra or {})})

    def _raw_info(self, ydl: Any, url: ValidatedUrl) -> Any:
        """The unprocessed extractor result for ``url`` (subclasses may fetch it differently)."""
        return ydl.extract_info(url.canonical_url, download=False, process=False)

    def _finish(self, post: PostMetadata, info: dict[str, Any]) -> PostMetadata:
        """Hook for subclasses to add platform-specific metadata."""
        return post

    # ---------------------------------------------------------------- sanitise
    def _keep_separate_audio(self, entry: dict[str, Any]) -> bool:
        """Whether a TikTok item's separate track ("audio", the item's *music*) may be offered.

        On ordinary TikTok videos that track is not reliably the video's own audio: it can be a
        licensed song or differ from the video's soundtrack even when labelled "original sound"
        (measured 2026-11-12). It is therefore never paired with video-only streams here.
        Subclasses with stronger evidence (Short Drama) override this.
        """
        return self.spec.platform != PLATFORM_TIKTOK

    def _sanitise_entry(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        suffixes = self.spec.media_allowed
        if entry.get("_type", "video") != "video":
            return None
        formats = entry.get("formats")
        if isinstance(formats, list):
            if self.spec.platform == PLATFORM_TIKTOK and not self._keep_separate_audio(entry):
                formats = [f for f in formats if not (isinstance(f, dict) and f.get("format_id") == "audio"
                                                      and str(f.get("vcodec") or "none") == "none")]
            safe = [f for f in formats if isinstance(f, dict) and self.spec.keep_format(f) and is_safe_format(f, suffixes)]
            if self.spec.drop_watermarked:
                # Prefer the clean source streams the platform serves; keep a
                # watermarked variant only if it is the sole video available.
                clean = [f for f in safe if "watermark" not in str(f.get("format_note") or "").lower()]
                if any(normalise_format(f, None).has_video is not False for f in clean):
                    safe = clean
            safe = _disambiguate_format_ids(safe)
        elif entry.get("url"):
            safe = [entry] if is_safe_format(entry, suffixes) else []
        else:
            safe = []
        duration = entry.get("duration") if isinstance(entry.get("duration"), (int, float)) else None
        if not any(normalise_format(f, duration).has_video is not False for f in safe):
            return None
        if isinstance(formats, list):
            return {**entry, "formats": safe}
        return entry

    def _video_only_on_foreign_hosts(self, entry: dict[str, Any]) -> bool:
        """True if the entry *has* video formats but none on an allowed media host."""
        formats = entry.get("formats") if isinstance(entry.get("formats"), list) else [entry]
        videos = [f for f in formats if isinstance(f, dict) and f.get("url")
                  and str(f.get("vcodec") or "") != "none" and self.spec.keep_format(f)]
        return bool(videos) and not any(is_safe_format(f, self.spec.media_allowed) for f in videos)

    def _no_video(self, entries: list[dict[str, Any]]) -> AppError:
        if any(self._video_only_on_foreign_hosts(e) for e in entries):
            return AppError(
                ErrorCode.MEDIA_HOST_BLOCKED,
                f"The video was found, but {self.spec.label} served it from a host outside MediaLab's allowlist, "
                "so it wasn't downloaded.",
            )
        return AppError(ErrorCode.NO_VIDEO, "This post does not contain a downloadable video.")

    def _sanitise(self, raw: Any) -> dict[str, Any]:
        """Drop anything that is not a video on the platform's own CDN before yt-dlp processes it."""
        if not isinstance(raw, dict):
            raise AppError(ErrorCode.EXTRACTION_FAILED,
                           f"{self.spec.label} answered, but MediaLab couldn't read the video details it returned.")
        kind = raw.get("_type", "video")
        if kind in ("url", "url_transparent"):
            raise AppError(
                ErrorCode.NO_VIDEO,
                f"This post does not contain a video hosted on {self.spec.label} (it links to external content).",
            )
        if kind == "playlist":
            raw_entries = [x for x in list(raw.get("entries") or []) if isinstance(x, dict)]
            entries = [e for e in (self._sanitise_entry(x) for x in raw_entries) if e]
            if not entries:
                raise self._no_video(raw_entries)
            return {**raw, "entries": entries}
        entry = self._sanitise_entry(raw)
        if entry is None:
            raise self._no_video([raw])
        return entry

    # ----------------------------------------------------------------- extract
    def _resolved(self, url: ValidatedUrl) -> ValidatedUrl:
        if url.short_link:
            from ..resolve import resolve_tiktok_short_link

            return resolve_tiktok_short_link(url, self.settings.socket_timeout_seconds)
        return url

    # Injected in tests to avoid real waiting.
    retry_sleep: Callable[[float], None] = staticmethod(time.sleep)

    def extract(self, url: ValidatedUrl) -> PostMetadata:
        url = self._resolved(url)
        # Transient network failures/timeouts: up to 3 attempts with 1 s, 2 s backoff.
        try:
            return with_retries(lambda: self._extract_once(url), what=f"{self.spec.label} analysis",
                                sleep=self.retry_sleep)
        except AppError as exc:
            # A Short Drama episode looks like a video with no formats; say which tab handles it.
            if exc.code == ErrorCode.NO_VIDEO and self.drama_probe is not None and self.drama_probe(url):
                from ..validation import PLATFORM_SHORTDRAMA, TAB_NAMES

                raise AppError(
                    ErrorCode.WRONG_PLATFORM,
                    "This is a TikTok Short Drama episode, not an ordinary TikTok video.",
                    action=f"Switch to the {TAB_NAMES[PLATFORM_SHORTDRAMA]} tab.",
                    details={"detected_platform": PLATFORM_SHORTDRAMA, "url": url.canonical_url},
                ) from exc
            raise

    # Set for the TikTok Videos tab: tells whether a video without formats is a Short Drama episode.
    drama_probe: Callable[[ValidatedUrl], bool] | None = None

    def _extract_once(self, url: ValidatedUrl) -> PostMetadata:
        from yt_dlp.utils import YoutubeDLError

        try:
            with self._ydl({"skip_download": True}) as ydl:
                raw = self._raw_info(ydl, url)
                safe = self._sanitise(raw)
                processed = ydl.process_ie_result(safe, download=False)
                self._fill_exact_sizes(ydl, processed)
        except AppError:
            raise
        except (YoutubeDLError, OSError) as exc:
            raise map_ytdlp_error(exc, platform=self.spec.platform) from exc
        return self._finish(normalise_info(processed, url, self.spec.media_allowed), processed)

    def _fill_exact_sizes(self, ydl: Any, info: dict[str, Any], max_requests: int = 12) -> None:
        """Ask the media host for the exact size of progressive MP4 files.

        X's reported bitrates are nominal, so bitrate-based estimates can be
        off by several times. A HEAD request returns the real Content-Length
        without downloading any media. Failures are ignored (the estimate stays).
        """
        from yt_dlp.networking import Request

        entries = info.get("entries") if info.get("_type") == "playlist" else [info]
        targets = [
            f
            for e in entries or []
            for f in (e.get("formats") or [])
            if f.get("protocol") in ("https", "http") and not f.get("filesize")
            and self.spec.media_allowed(f.get("url"))
        ][:max_requests]

        def head(fmt: dict[str, Any]) -> None:
            try:
                resp = ydl.urlopen(Request(fmt["url"], headers=fmt.get("http_headers") or {}, method="HEAD"))
                try:
                    length = resp.headers.get("Content-Length")
                    if length and length.isdigit() and self.spec.media_allowed(resp.url):
                        fmt["filesize"] = int(length)
                        fmt.pop("filesize_approx", None)
                finally:
                    resp.close()
            except Exception as exc:  # noqa: BLE001 - size is optional metadata
                log.debug("HEAD %s failed: %s", fmt.get("format_id"), exc)

        # Sequential on purpose: a YoutubeDL instance is not documented as thread-safe.
        for fmt in targets:
            head(fmt)

    # ---------------------------------------------------------------- download
    def download(
        self,
        url: ValidatedUrl,
        video_index: int,
        format_ids: list[str],
        dest_dir: Path,
        on_progress: ProgressCallback,
    ) -> dict[str, Path]:
        """Download the formats, retrying transient failures (at most 3 attempts in total).

        * HTTP 403 from the CDN (an expired/refused signed link): re-extract to get
          fresh signed URLs at once; where the format has a mirrored copy
          (``<id>-0`` / ``<id>-1``), use the other mirror.
        * Interrupted transfers / timeouts: retry with backoff (2 s, 4 s).
        Each attempt runs in a clean sub-folder; the stage shown to the user says
        why MediaLab is retrying. Other errors are raised immediately.
        """
        url = self._resolved(url)
        max_attempts = 3
        ids = list(format_ids)
        for n in range(max_attempts):
            work = dest_dir / f"attempt-{n}"
            work.mkdir(parents=True, exist_ok=True)
            try:
                got = self._download_once(url, video_index, ids, work, on_progress)
            except AppError as exc:
                expired = _is_http_403(exc)
                interrupted = exc.code in (ErrorCode.DOWNLOAD_INTERRUPTED, ErrorCode.TIMEOUT)
                if not (expired or interrupted) or n == max_attempts - 1:
                    raise
                if expired:
                    note = "The video link expired. Refreshing the download information…"
                    if self.spec.mirrored_formats:
                        ids = [_mirror_of(f) for f in ids]
                    delay = 0.0
                else:
                    note = "The download was interrupted. Retrying…"
                    delay = 2.0 * (2 ** n)
                log.info("%s download attempt %d failed (%s: %s); retrying", self.spec.label, n + 1,
                         exc.code.value, exc.__cause__ or exc.message)
                on_progress(ProgressUpdate(format_ids[0], "retrying", 0, None, True, note=f"{note} (attempt {n + 2} of {max_attempts})"))
                if delay:
                    self.retry_sleep(delay)
                continue
            # Report outputs under the IDs the caller asked for.
            return {orig: got[used] for orig, used in zip(format_ids, ids)}
        raise AssertionError("unreachable")  # pragma: no cover

    def _download_once(
        self,
        url: ValidatedUrl,
        video_index: int,
        format_ids: list[str],
        dest_dir: Path,
        on_progress: ProgressCallback,
    ) -> dict[str, Path]:
        from yt_dlp.utils import YoutubeDLError

        def hook(d: dict[str, Any]) -> None:
            status = d.get("status")
            if status not in ("downloading", "finished"):
                return
            info = d.get("info_dict") or {}
            total = d.get("total_bytes")
            estimate = d.get("total_bytes_estimate")
            on_progress(
                ProgressUpdate(
                    format_id=str(info.get("format_id") or ""),
                    status=status,
                    downloaded_bytes=int(d.get("downloaded_bytes") or 0),
                    total_bytes=int(total) if total else (int(estimate) if estimate else None),
                    total_is_estimate=not total,
                    speed_bytes_per_second=d.get("speed"),
                    eta_seconds=d.get("eta"),
                )
            )

        params = {
            # "a,b" downloads each format separately; MediaLab muxes them itself.
            "format": ",".join(format_ids),
            "outtmpl": {"default": "%(format_id)s.%(ext)s"},
            "paths": {"home": str(dest_dir), "temp": str(dest_dir)},
            "progress_hooks": [hook],
        }
        try:
            with self._ydl(params) as ydl:
                raw = self._raw_info(ydl, url)
                safe = self._sanitise(raw)
                if safe.get("_type") == "playlist":
                    entries = safe["entries"]
                    if not 1 <= video_index <= len(entries):
                        raise AppError(ErrorCode.FORMAT_UNAVAILABLE, "That video is no longer part of the post.")
                    entry = dict(entries[video_index - 1])
                    for key in ("extractor", "extractor_key", "webpage_url", "original_url",
                                "webpage_url_basename", "webpage_url_domain"):
                        if key in safe and key not in entry:
                            entry[key] = safe[key]
                else:
                    if video_index != 1:
                        raise AppError(ErrorCode.FORMAT_UNAVAILABLE, "That video is no longer part of the post.")
                    entry = safe
                available = [str(f.get("format_id")) for f in entry.get("formats") or []]
                if self.spec.mirrored_formats:
                    for i, fid in enumerate(format_ids):
                        if fid not in available and (alt := equivalent_format_id(fid, available)):
                            log.info("%s served another encode of %s; using %s", self.spec.label, fid, alt)
                            format_ids[i] = alt
                            spec = ",".join(format_ids)
                            ydl.params["format"] = spec  # the selector is built at construction
                            if hasattr(ydl, "build_format_selector"):
                                ydl.format_selector = ydl.build_format_selector(spec)
                missing = [f for f in format_ids if f not in available]
                if missing:
                    raise AppError(
                        ErrorCode.FORMAT_UNAVAILABLE,
                        f"The selected format is no longer offered by {self.spec.label}. Analyse it again.",
                    )
                result = ydl.process_ie_result(entry, download=True)
        except AppError:
            raise
        except (YoutubeDLError, OSError) as exc:
            raise map_ytdlp_error(exc, during_download=True, platform=self.spec.platform) from exc

        return self._collect_outputs(result, format_ids, dest_dir)

    @staticmethod
    def _collect_outputs(result: Any, format_ids: list[str], dest_dir: Path) -> dict[str, Path]:
        outputs: dict[str, Path] = {}
        dest = dest_dir.resolve()
        for item in (result or {}).get("requested_downloads") or []:
            fid, path = item.get("format_id"), item.get("filepath")
            if fid in format_ids and path:
                candidate = Path(path).resolve()
                if candidate.is_file() and candidate.is_relative_to(dest):
                    outputs[fid] = candidate
        for fid in format_ids:
            if fid in outputs:
                continue
            # Fallback: locate the file by its format-id stem.
            for candidate in sorted(dest.iterdir()):
                if candidate.is_file() and candidate.name.startswith(fid + ".") and not candidate.name.endswith(
                    (".part", ".ytdl", ".temp")
                ):
                    outputs[fid] = candidate
                    break
        missing = [fid for fid in format_ids if fid not in outputs]
        if missing:
            raise AppError(ErrorCode.DOWNLOAD_FAILED, "The download finished but the media file is missing.")
        return outputs
