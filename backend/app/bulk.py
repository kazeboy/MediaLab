"""Bulk analysis of X and TikTok links (v1.9).

A bulk analysis takes the lines a user pasted into the Bulk view of the X or TikTok
Videos tab and analyses each link once, so the user can review and select videos before
anything is downloaded.

* **Validation** uses the same rules as a single analysis (:func:`validate_post_url`):
  every line is checked server-side; links for another tab are reported as
  ``wrong_platform`` (never redirected or mixed into the batch).
* **Duplicates** are recognised by post ID (and video number for X posts with several
  videos), so ``x.com/a/status/1`` and ``twitter.com/b/status/1`` count once. TikTok
  share links can only be compared after they are resolved.
* **Limits:** at most ``settings.max_bulk_urls`` (default 50) distinct links per analysis,
  :data:`MAX_LINES` pasted lines, :data:`MAX_ACTIVE` analyses at once, and
  :data:`BULK_CONCURRENCY` extractions at a time per server.
* **Caching:** each link is extracted once; the result is stored in the shared
  :class:`AnalysisStore` and reused by the batch download, which re-analyses only if the
  stored analysis expired in the meantime.
* **Cancellation:** waiting links are cancelled at once; an extraction already talking to
  the platform can't be interrupted, so its result is discarded when it returns.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

from . import resolve
from .errors import AppError, ErrorCode
from .retry import with_retries
from .selection import BEST_OPTION_ID, apply_size_limit, build_options, choose_option
from .storage import AnalysisStore, StoredAnalysis, new_id
from .validation import (
    PLATFORM_LABELS,
    PLATFORM_TIKTOK,
    PLATFORM_X,
    ValidatedUrl,
    adopt_for_tab,
    check_platform,
    validate_post_url,
)

log = logging.getLogger(__name__)

BULK_PLATFORMS = (PLATFORM_X, PLATFORM_TIKTOK)
BULK_CONCURRENCY = 2
MAX_ACTIVE = 2
MAX_LINES = 500
QUALITY_PREFERENCES = (BEST_OPTION_ID, "1080p", "720p", "480p")

WAITING, ANALYSING, READY, FAILED, INVALID, DUPLICATE, CANCELLED = (
    "waiting", "analysing", "ready", "failed", "invalid", "duplicate", "cancelled")
FINAL = frozenset({READY, FAILED, INVALID, DUPLICATE, CANCELLED})


def resolve_validated(url: ValidatedUrl, platform: str, timeout: int) -> ValidatedUrl:
    """Follow a TikTok share link and check the result belongs to ``platform``'s tab."""
    if url.short_link:
        url = with_retries(lambda: resolve.resolve_tiktok_short_link(url, timeout), what="short-link resolution")
        url = adopt_for_tab(url, platform)
        check_platform(url, platform)
    return url


def analyse_validated(provider, analyses: AnalysisStore, url: ValidatedUrl, platform: str,
                      timeout: int) -> StoredAnalysis:
    """Resolve, extract and store one link (the same steps as ``POST /api/analyse``)."""
    url = resolve_validated(url, platform, timeout)
    post = provider.extract(url)
    base = {v.index: build_options(v) for v in post.videos}
    return analyses.put(url, post, base, post.provider or provider.name)


def _key(url: ValidatedUrl) -> tuple | None:
    if url.short_link or not url.post_id:
        return None
    return (url.platform, url.post_id, url.video_index or 1)


@dataclass
class BulkItem:
    index: int
    input: str
    state: str = WAITING
    url: ValidatedUrl | None = None
    key: tuple | None = None
    duplicate_of: int | None = None
    analysis_id: str | None = None
    error: AppError | None = None
    title: str | None = None
    author: str | None = None
    duration_seconds: float | None = None
    thumbnail_url: str | None = None
    video_count: int = 0
    video_index: int = 1
    qualities: list[str] = field(default_factory=list)
    # Per quality preference: (label, size in bytes or None, size is an estimate, note)
    estimates: dict[str, tuple[str, int | None, bool, str | None]] = field(default_factory=dict)


@dataclass
class BulkAnalysis:
    bulk_id: str
    platform: str
    items: list[BulkItem]
    limit: int
    state: str = "running"  # running | done | cancelled
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cancel_event: threading.Event = field(default_factory=threading.Event)


class BulkAnalysisManager:
    def __init__(self, settings, settings_store, provider, analyses: AnalysisStore) -> None:
        self.settings = settings
        self.settings_store = settings_store
        self.provider = provider
        self.analyses = analyses
        self._items: dict[str, BulkAnalysis] = {}
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=BULK_CONCURRENCY, thread_name_prefix="medialab-bulk")

    # --------------------------------------------------------------- public
    def create(self, platform: str, lines: list[str]) -> BulkAnalysis:
        if platform not in BULK_PLATFORMS:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Bulk downloads are available on the X and TikTok Videos tabs.")
        cleaned = [line.strip() for line in lines if line and line.strip()]
        if not cleaned:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Paste at least one link, one per line.")
        if len(cleaned) > MAX_LINES:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"That's {len(cleaned)} lines; paste at most {MAX_LINES}.")
        limit = self.settings.max_bulk_urls
        items: list[BulkItem] = []
        seen: dict[tuple, int] = {}
        for n, raw in enumerate(cleaned, 1):
            item = BulkItem(index=n, input=raw[:300])
            try:
                item.url = validate_post_url(raw, platform)
            except AppError as exc:
                item.state, item.error = INVALID, exc
                items.append(item)
                continue
            item.key = _key(item.url)
            if item.key is not None and item.key in seen:
                item.state, item.duplicate_of = DUPLICATE, seen[item.key]
            elif item.key is not None:
                seen[item.key] = n
            items.append(item)
        valid = [i for i in items if i.state == WAITING]
        if not valid:
            raise AppError(ErrorCode.INVALID_URL, f"None of the lines is a {PLATFORM_LABELS[platform]} video link.",
                           details={"invalid": sum(i.state == INVALID for i in items)})
        if len(valid) > limit:
            raise AppError(ErrorCode.VALIDATION_ERROR,
                           f"That's {len(valid)} different links; a bulk download can hold at most {limit}.",
                           action=f"Remove some links (the limit is {limit} per batch) and try again.",
                           details={"valid": len(valid), "limit": limit})
        bulk = BulkAnalysis(new_id(), platform, items, limit)
        with self._lock:
            running = sum(1 for b in self._items.values() if b.state == "running")
            if running >= MAX_ACTIVE:
                raise AppError(ErrorCode.BUSY, "Two bulk analyses are already running. Wait for one to finish.")
            self._items[bulk.bulk_id] = bulk
        log.info("Bulk %s: %d lines, %d to analyse (%s)", bulk.bulk_id, len(items), len(valid), platform)
        for item in valid:
            self._pool.submit(self._analyse, bulk.bulk_id, item.index)
        return self.get(bulk.bulk_id)

    def get(self, bulk_id: str) -> BulkAnalysis:
        with self._lock:
            bulk = self._items.get(bulk_id)
            if bulk is None:
                raise AppError(ErrorCode.BULK_NOT_FOUND, "This list of links is no longer available.")
            return replace(bulk, items=[replace(i) for i in bulk.items])

    def cancel(self, bulk_id: str) -> BulkAnalysis:
        with self._lock:
            bulk = self._items.get(bulk_id)
            if bulk is None:
                raise AppError(ErrorCode.BULK_NOT_FOUND, "This list of links is no longer available.")
            if bulk.state == "running":
                bulk.cancel_event.set()
                for item in bulk.items:
                    if item.state in (WAITING, ANALYSING):
                        item.state = CANCELLED
                bulk.state, bulk.updated_at = "cancelled", time.time()
                log.info("Bulk %s cancelled", bulk_id)
        return self.get(bulk_id)

    def prune(self, now: float | None = None) -> int:
        now = now or time.time()
        with self._lock:
            old = [k for k, b in self._items.items()
                   if b.state != "running" and now - b.updated_at > self.settings.analysis_ttl_seconds]
            for k in old:
                del self._items[k]
        return len(old)

    def shutdown(self) -> None:
        with self._lock:
            for b in self._items.values():
                b.cancel_event.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    # --------------------------------------------------------------- worker
    def _analyse(self, bulk_id: str, index: int) -> None:
        with self._lock:
            bulk = self._items.get(bulk_id)
            if bulk is None:
                return
            item = bulk.items[index - 1]
            if bulk.cancel_event.is_set() or item.state != WAITING:
                return
            item.state = ANALYSING
            url, platform = item.url, bulk.platform
        stored: StoredAnalysis | None = None
        error: AppError | None = None
        try:
            stored = analyse_validated(self.provider, self.analyses, url, platform,
                                       self.settings.socket_timeout_seconds)
        except AppError as exc:
            error = exc
        except Exception:  # noqa: BLE001 - one broken link must not stop the others
            log.exception("Bulk %s item %d crashed", bulk_id, index)
            error = AppError(ErrorCode.EXTRACTION_FAILED, "Analysing this link failed unexpectedly.")
        with self._lock:
            bulk = self._items.get(bulk_id)
            if bulk is None:
                return
            item = bulk.items[index - 1]
            if item.state == ANALYSING:
                if error is not None:
                    item.state, item.error = FAILED, error
                else:
                    self._fill(bulk, item, stored)
            bulk.updated_at = time.time()
            if bulk.state == "running" and all(i.state in FINAL for i in bulk.items):
                bulk.state = "done"
                log.info("Bulk %s done: %d ready", bulk_id, sum(i.state == READY for i in bulk.items))

    def _fill(self, bulk: BulkAnalysis, item: BulkItem, stored: StoredAnalysis) -> None:
        url = stored.url
        indices = [v.index for v in stored.post.videos]
        index = url.video_index if url.video_index in indices else indices[0]
        key = (url.platform, url.post_id, index)
        earlier = next((i for i in bulk.items if i is not item and i.key == key and i.state in (READY, ANALYSING)
                        and i.index < item.index), None)
        if earlier is None:
            earlier = next((i for i in bulk.items if i is not item and i.key == key and i.state == READY), None)
        item.key, item.url = key, url
        if earlier is not None:  # e.g. a share link and the full link of the same video
            item.state, item.duplicate_of = DUPLICATE, earlier.index
            return
        video = stored.video(index)
        limit = self.settings_store.get().max_file_size_bytes
        options = apply_size_limit(stored.options.get(index, []), limit)
        item.state, item.analysis_id = READY, stored.analysis_id
        item.title = video.title or stored.post.text or None
        item.author = stored.post.author_handle or stored.post.author_name
        item.duration_seconds = video.duration_seconds
        item.thumbnail_url = video.thumbnail_url
        item.video_count, item.video_index = len(stored.post.videos), index
        item.qualities = [o.label for o in options if not o.is_best and o.downloadable]
        for pref in QUALITY_PREFERENCES:
            try:
                option, note = choose_option(options, pref, strict=False, above="closest")
            except AppError as exc:
                if pref == BEST_OPTION_ID:  # nothing downloadable at all: report it as the item's error
                    item.state, item.error, item.analysis_id = FAILED, exc, None
                    return
                continue
            exact = option.filesize is not None
            item.estimates[pref] = (option.label, option.filesize if exact else option.filesize_approx, not exact, note)
