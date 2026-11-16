"""TikTok Short Drama episodes.

How episodes are delivered (investigated 2026-11-12; see docs/PROVIDERS.md):

* An episode is an ordinary TikTok item (``/@<publisher>/video/<item id>``) whose
  page data carries ``dramaInfo`` (series ID and title, ``EpisodeNumber``,
  ``numVideos``) and ``DramaVideoData`` (``IsPreview``, ``PreviewType``,
  ``LinkedEpisodeID``). A share link for an episode (``vm.tiktok.com/…``)
  redirects to that item page.
* Logged out, TikTok returns the item with ``IsPreview: true``,
  ``PreviewType: 4`` and **no** stream (empty ``playAddr``, no ``bitrateInfo``).
  The ``LinkedEpisodeID`` item answers status 203008 both logged out and in.
* Signed in, the *same* item page lists the full episode as progressive MP4 on
  TikTok's CDN (observed: 720x1280 HEVC and 576x1024 H.264/HEVC, no DRM), which
  yt-dlp's TikTok extractor parses like any other video.
* ``/shortdrama/episode/<series>/<n>`` pages contain no episode data. The web
  app loads the series from ``/api/drama/detail/`` and
  ``/api/drama/episode/item_list/`` (24 per page, ordered by episode). Verified
  2026-11-12: these answer plain requests (no X-Bogus/X-Gnarly signatures are
  generated or sent): logged out with item IDs but no streams, and with the
  viewer's session with each episode's playable streams. MediaLab uses them to
  map (series, episode) to the episode's item and to list a series.

So this provider extracts episodes from item pages with yt-dlp's TikTok
extractor, sending the user's own TikTok session cookies *only if* the user
linked them explicitly (see ``app.tiktok_account``). All of the yt-dlp
provider's safeguards (TikTok extractor only, media-host allowlist,
stream-copy, retries) apply unchanged.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

from ..config import Settings
from ..errors import AppError, ErrorCode
from ..models import DramaInfo, PostMetadata, SeriesEpisode, SeriesInfo
from ..tiktok_account import TikTokAccountStore
from ..validation import (
    PLATFORM_SHORTDRAMA,
    PLATFORM_TIKTOK,
    TAB_NAMES,
    ValidatedUrl,
    adopt_for_tab,
    is_allowed_tiktok_media_url,
    validate_post_url,
)
from .base import ProgressCallback
from ..retry import with_retries
from .ytdlp_provider import YtDlpProvider, map_ytdlp_error

log = logging.getLogger(__name__)

ANON_LOGIN_MESSAGE = (
    "TikTok only plays this Short Drama episode to signed-in viewers. Logged out, it returns a locked preview "
    "(“Log in to start watching”) with no video."
)
ANON_LOGIN_ACTION = (
    "To download episodes you can watch on TikTok, link your TikTok account in Settings (Short Drama only). "
    "MediaLab never asks for your password."
)
ACCOUNT_DENIED_MESSAGE = (
    "TikTok didn't give your linked account access to this episode: it still returned a locked preview with no "
    "video. The episode may need to be unlocked in TikTok (for example with coins or ads), or your TikTok "
    "sign-in may have expired."
)
INTERNAL_ITEM_MESSAGE = (
    "TikTok doesn't serve this item directly (status 203008). It's TikTok's internal episode record, not the "
    "playable episode."
)


def drama_data(item: dict[str, Any]) -> dict[str, Any] | None:
    info = item.get("dramaInfo") if isinstance(item, dict) else None
    return info if isinstance(info, dict) and info.get("dramaID") else None


def has_stream(item: dict[str, Any]) -> bool:
    video = item.get("video") if isinstance(item, dict) else None
    if not isinstance(video, dict):
        return False
    return bool(video.get("playAddr") or video.get("downloadAddr") or video.get("bitrateInfo"))


API_BASE = "https://www.tiktok.com/api/"
API_HOST = "www.tiktok.com"
SERIES_PAGE_SIZE = 24
MAX_SERIES_EPISODES = 500
MAX_API_RESPONSE_BYTES = 16 * 1024 * 1024
SERIES_CACHE_SECONDS = 300


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class TikTokShortDramaProvider(YtDlpProvider):
    name = "tiktok-shortdrama"

    def __init__(self, settings: Settings, account: TikTokAccountStore) -> None:
        super().__init__(settings, PLATFORM_TIKTOK)
        self.account = account
        self._series_cache: dict[tuple[str, bool], tuple[float, SeriesInfo]] = {}
        self._series_lock = threading.Lock()

    # ------------------------------------------------------------ yt-dlp setup
    def _ydl(self, extra: dict[str, Any] | None = None):
        ydl = super()._ydl(extra)
        # In-memory only: "cookiefile" stays None, so yt-dlp never writes the file back.
        try:
            self.account.load_into(ydl.cookiejar)
        except Exception as exc:  # noqa: BLE001 - a damaged file must not leak details
            log.warning("TikTok account cookies could not be loaded: %s", type(exc).__name__)
        return ydl

    def _web_item(self, ydl: Any, url: ValidatedUrl) -> tuple[Any, dict[str, Any]]:
        ie = ydl.get_info_extractor("TikTok")
        if not hasattr(ie, "_extract_web_data_and_status") or not hasattr(ie, "_parse_aweme_video_web"):
            raise AppError(ErrorCode.EXTRACTION_FAILED,
                           "This yt-dlp version can't read TikTok item pages. Update it with `make update-ytdlp`.")
        ie.initialize()
        data, status = ie._extract_web_data_and_status(url.canonical_url, url.post_id)
        if status == 203008:
            raise AppError(ErrorCode.NOT_FOUND, INTERNAL_ITEM_MESSAGE,
                           action="Paste the episode's share link (Share, then Copy link in TikTok) instead.")
        if status in (10216, 10222):
            raise AppError(ErrorCode.UNAVAILABLE, "This TikTok video is private.")
        if status == 10204:
            raise AppError(ErrorCode.NOT_FOUND, "This TikTok video could not be found. It may have been deleted.")
        if status != 0 or not isinstance(data, dict) or not data:
            raise AppError(ErrorCode.EXTRACTION_FAILED,
                           f"TikTok didn't return this episode's details (status {status}).")
        return ie, data

    def _raw_info(self, ydl: Any, url: ValidatedUrl) -> Any:
        ie, item = self._web_item(ydl, url)
        drama = drama_data(item)
        if drama is None:
            raise AppError(
                ErrorCode.WRONG_PLATFORM,
                "This is an ordinary TikTok video, not a Short Drama episode.",
                action=f"Switch to the {TAB_NAMES[PLATFORM_TIKTOK]} tab.",
                details={"detected_platform": PLATFORM_TIKTOK, "url": url.canonical_url},
            )
        episode = drama.get("DramaVideoData") if isinstance(drama.get("DramaVideoData"), dict) else {}
        details = {
            "platform": PLATFORM_SHORTDRAMA,
            "series_id": str(drama.get("dramaID")),
            "episode": _int(episode.get("EpisodeNumber")),
            "preview_type": _int(episode.get("PreviewType")),
        }
        if not has_stream(item):
            linked = self.account.linked()
            log.info("Short Drama item %s has no stream (IsPreview=%s PreviewType=%s, account linked=%s)",
                     url.post_id, episode.get("IsPreview"), episode.get("PreviewType"), linked)
            if linked:
                raise AppError(ErrorCode.ACCOUNT_ACCESS_UNAVAILABLE, ACCOUNT_DENIED_MESSAGE, details=details)
            raise AppError(ErrorCode.LOGIN_REQUIRED, ANON_LOGIN_MESSAGE, action=ANON_LOGIN_ACTION, details=details)
        info = ie._parse_aweme_video_web(item, url.canonical_url, url.post_id)
        ydl.add_default_extra_info(info, ie, url.canonical_url)
        music = item.get("music") if isinstance(item.get("music"), dict) else {}
        # TikTok marks the episode's own soundtrack as "original sound"; only then is the separate
        # track used (it matched the episodes' audio in testing; see docs/MEDIA_PIPELINE.md).
        info["_medialab_original_sound"] = music.get("original") is True
        info["_medialab_drama"] = {
            "series_id": str(drama.get("dramaID")),
            "series_title": drama.get("dramaName") if isinstance(drama.get("dramaName"), str) else None,
            "episode": details["episode"],
            "episode_count": _int(drama.get("numVideos")),
            "account_used": self.account.linked(),
        }
        return info

    def _keep_separate_audio(self, entry: dict[str, Any]) -> bool:
        return entry.get("_medialab_original_sound") is True

    def _finish(self, post: PostMetadata, info: dict[str, Any]) -> PostMetadata:
        drama = info.get("_medialab_drama")
        if not isinstance(drama, dict):
            return post
        return post.model_copy(update={"drama": DramaInfo(**drama)})

    # ------------------------------------------------------------------ series
    def _api(self, ydl: Any, path: str, params: dict[str, str]) -> dict[str, Any]:
        """GET a fixed TikTok web API path (no user-supplied URL parts except numeric IDs)."""
        from yt_dlp.networking import Request
        from yt_dlp.networking.impersonate import ImpersonateTarget
        from yt_dlp.utils import YoutubeDLError

        query = {"aid": "1988", "app_name": "tiktok_web", "device_platform": "web_pc", **params}
        url = API_BASE + path + "/?" + urllib.parse.urlencode(query)
        try:
            resp = ydl.urlopen(Request(url, headers={"Referer": "https://www.tiktok.com/"},
                                       extensions={"impersonate": ImpersonateTarget("chrome")}))
            try:
                final = urllib.parse.urlsplit(getattr(resp, "url", url) or url)
                if final.scheme != "https" or (final.hostname or "").lower() != API_HOST:
                    raise AppError(ErrorCode.SERIES_METADATA_UNAVAILABLE,
                                   "TikTok redirected the series request away from tiktok.com, so MediaLab stopped.")
                body = resp.read(MAX_API_RESPONSE_BYTES + 1)
            finally:
                resp.close()
        except AppError:
            raise
        except (YoutubeDLError, OSError) as exc:
            raise map_ytdlp_error(exc, platform=PLATFORM_TIKTOK) from exc
        if len(body) > MAX_API_RESPONSE_BYTES:
            raise AppError(ErrorCode.SERIES_METADATA_UNAVAILABLE, "TikTok's series response was unexpectedly large.")
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise AppError(ErrorCode.SERIES_METADATA_UNAVAILABLE,
                           "TikTok answered the series request with something other than series data.") from exc
        status = data.get("statusCode", data.get("status_code")) if isinstance(data, dict) else None
        if status not in (0, None):
            raise AppError(ErrorCode.SERIES_METADATA_UNAVAILABLE,
                           f"TikTok didn't return this series (status {status}).", details={"tiktok_status": status})
        return data

    def series(self, series_id: str) -> SeriesInfo:
        """Series details and every episode, in order, as TikTok lists them for this viewer."""
        if not series_id.isdigit() or len(series_id) > 25:
            raise AppError(ErrorCode.INVALID_URL, "That isn't a valid Short Drama series ID.")
        self._check_session()
        linked = self.account.linked()
        cache = self._series_cache
        key = (series_id, linked)
        with self._series_lock:
            hit = cache.get(key)
            if hit and time.time() - hit[0] < SERIES_CACHE_SECONDS:
                return hit[1]
        info = with_retries(lambda: self._fetch_series(series_id, linked), what="TikTok series lookup",
                            sleep=self.retry_sleep)
        with self._series_lock:
            cache[key] = (time.time(), info)
            for k in [k for k, (t, _) in cache.items() if time.time() - t > SERIES_CACHE_SECONDS]:
                cache.pop(k, None)
        return info

    def _fetch_series(self, series_id: str, linked: bool) -> SeriesInfo:
        with self._ydl() as ydl:
            detail = self._api(ydl, "drama/detail", {"dramaID": series_id}).get("dramaInfo") or {}
            items: list[dict[str, Any]] = []
            cursor = "0"
            total: int | None = None
            for _ in range(MAX_SERIES_EPISODES // SERIES_PAGE_SIZE + 1):
                page = self._api(ydl, "drama/episode/item_list",
                                 {"dramaID": series_id, "count": str(SERIES_PAGE_SIZE), "cursor": cursor})
                total = _int(page.get("totalEpisodeCount")) or total
                batch = [i for i in page.get("itemList") or [] if isinstance(i, dict)]
                items += batch
                nxt = str(page.get("cursor") or "")
                if not page.get("hasMore") or not batch or not nxt.isdigit() or nxt == cursor \
                        or len(items) >= MAX_SERIES_EPISODES:
                    break
                cursor = nxt
        if not detail and not items:
            raise AppError(ErrorCode.SERIES_METADATA_UNAVAILABLE, "TikTok returned no details for this series.")
        episodes: dict[int, SeriesEpisode] = {}
        for item in items:
            drama = drama_data(item) or {}
            if drama and str(drama.get("dramaID")) != series_id:
                continue
            ep = drama.get("DramaVideoData") if isinstance(drama.get("DramaVideoData"), dict) else {}
            number, item_id = _int(ep.get("EpisodeNumber")), str(item.get("id") or "")
            if not number or not item_id.isdigit() or number in episodes:
                continue
            video = item.get("video") if isinstance(item.get("video"), dict) else {}
            author = item.get("author") if isinstance(item.get("author"), dict) else {}
            available = has_stream(item) or bool(video.get("PlayAddrStruct"))
            cover = video.get("cover") if isinstance(video.get("cover"), str) else None
            episodes[number] = SeriesEpisode(
                number=number,
                item_id=item_id,
                title=item.get("desc") if isinstance(item.get("desc"), str) else None,
                duration_seconds=float(video["duration"]) if isinstance(video.get("duration"), (int, float)) else None,
                thumbnail_url=cover if is_allowed_tiktok_media_url(cover) else None,
                available=available,
                availability="available" if available else ("locked" if linked else "login_required"),
                publisher_handle=author.get("uniqueId") if isinstance(author.get("uniqueId"), str) else None,
            )
        author = detail.get("author") if isinstance(detail.get("author"), dict) else {}
        cover_urls = ((detail.get("cover") or {}).get("UrlList") or (detail.get("cover") or {}).get("urlList") or []) \
            if isinstance(detail.get("cover"), dict) else []
        cover = next((u for u in cover_urls if is_allowed_tiktok_media_url(u)), None)
        ordered = tuple(episodes[n] for n in sorted(episodes))
        return SeriesInfo(
            series_id=series_id,
            title=detail.get("dramaName") if isinstance(detail.get("dramaName"), str) else None,
            description=detail.get("description") if isinstance(detail.get("description"), str) else None,
            episode_count=_int(detail.get("numVideos")) or total or (len(ordered) or None),
            cover_url=cover,
            publisher_handle=(author.get("uniqueId") if isinstance(author.get("uniqueId"), str) else None)
            or next((e.publisher_handle for e in ordered if e.publisher_handle), None),
            publisher_name=author.get("nickname") if isinstance(author.get("nickname"), str) else None,
            account_used=linked,
            episodes=ordered,
        )

    def episode_url(self, series_id: str, number: int) -> ValidatedUrl:
        """The TikTok item URL of episode ``number`` of a series."""
        try:
            info = self.series(series_id)
        except AppError as exc:
            if exc.code in (ErrorCode.AUTH_EXPIRED, ErrorCode.INVALID_URL):
                raise
            raise AppError(
                ErrorCode.EPISODE_RESOLUTION_FAILED,
                f"MediaLab couldn't look up episode {number} of this series: {exc.message}",
                retryable=exc.retryable,
                details={"platform": PLATFORM_SHORTDRAMA, "series_id": series_id, "episode": number},
            ) from exc
        episode = next((e for e in info.episodes if e.number == number), None)
        if episode is None:
            count = info.episode_count or len(info.episodes)
            raise AppError(
                ErrorCode.EPISODE_NOT_IN_SERIES,
                f"Episode {number} isn't in this series" + (f" (TikTok lists {count} episodes)." if count else "."),
                details={"platform": PLATFORM_SHORTDRAMA, "series_id": series_id, "episode": number,
                         "episode_count": count},
            )
        handle = episode.publisher_handle or info.publisher_handle or ""
        return adopt_for_tab(validate_post_url(f"https://www.tiktok.com/@{handle}/video/{episode.item_id}"),
                             PLATFORM_SHORTDRAMA)

    def _check_session(self) -> None:
        status = self.account.status()
        if status.linked and status.expired:
            raise AppError(ErrorCode.AUTH_EXPIRED, "Your linked TikTok sign-in has expired (according to the "
                           "cookies file's expiry date).")

    # ----------------------------------------------------------------- public
    def _item_url(self, url: ValidatedUrl) -> ValidatedUrl:
        """Direct episode links are resolved to the episode's TikTok item."""
        if url.episode is not None:
            return self.episode_url(url.post_id, url.episode)
        return url

    def extract(self, url: ValidatedUrl) -> PostMetadata:
        self._check_session()
        return super().extract(self._item_url(url))

    def download(
        self,
        url: ValidatedUrl,
        video_index: int,
        format_ids: list[str],
        dest_dir: Path,
        on_progress: ProgressCallback,
    ) -> dict[str, Path]:
        self._check_session()
        return super().download(self._item_url(url), video_index, format_ids, dest_dir, on_progress)

    def is_drama_episode(self, url: ValidatedUrl) -> bool:
        """Anonymous probe used by the TikTok Videos tab to suggest switching tabs. Never raises."""
        if url.short_link or url.episode is not None or not url.post_id:
            return False
        try:
            from yt_dlp import YoutubeDL

            with YoutubeDL(self._base_params()) as ydl:  # no account cookies for a probe
                ie = ydl.get_info_extractor("TikTok")
                ie.initialize()
                data, status = ie._extract_web_data_and_status(url.canonical_url, url.post_id, fatal=False)
            return status == 0 and drama_data(data) is not None
        except Exception as exc:  # noqa: BLE001
            log.debug("Short Drama probe failed: %s", map_ytdlp_error(exc, platform=PLATFORM_TIKTOK).code)
            return False
