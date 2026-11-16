"""Batch downloads: several episodes of one Short Drama series, or (v1.9) a list of X or
TikTok video links, through one queue.

Sources
-------
* ``shortdrama``: episodes of one series (looked up by number with the linked account).
* ``urls``: X or TikTok videos already analysed by a bulk analysis (:mod:`app.bulk`). Items
  are numbered in input order. Output is ``files`` or ``zip`` (never ``merge``: unrelated
  videos aren't joined). Cancelling the batch keeps items that already finished (see
  :meth:`BatchManager.cancel`).

Output modes
------------
* ``files`` (v1.4): every episode is handed to the browser as its own MP4.
* ``zip``: episodes are collected privately, then packaged into one ZIP of separate MP4s.
* ``merge``: episodes are collected privately, then joined into one continuous MP4.

Design:

* A worker thread per batch starts episodes in order through the normal pipeline
  (episode lookup → analysis → option choice → :class:`~app.jobs.JobManager` job), so every
  per-download safeguard (size limit, disk check, retries, audio validation, cleanup)
  applies unchanged.
* **Temporary storage.** In ``files`` mode a finished episode waits in ``ready/`` for the
  browser and at most ``concurrency + MAX_UNSAVED - 1`` episodes occupy temporary storage.
  In ``zip``/``merge`` mode finished episodes move to the batch's private folder
  (``<temp>/job-batch-<id>/``); free space is checked before every episode and before
  packaging, and the final output must fit the separate *batch output* size limit.
* **Merge planning.** Before downloading, ``merge`` analyses every selected episode and,
  with Best Available, picks the highest resolution *all* of them offer, so identical
  renditions can be joined by stream copy (episode Best Available differs within a series).
* **Failure policy** (``zip``/``merge``): by default packaging stops if any selected
  episode failed or was skipped; downloaded episodes are kept (for the retention period)
  so failed ones can be retried. With ``allow_partial`` (or the *continue* action) the
  output is built from the successful episodes and lists exactly which were omitted; it is
  never named "Complete Series".
* Pause stops new episodes from starting; cancel stops running jobs, kills packaging,
  and deletes unsaved and collected files (never a file the browser is receiving).
* Episodes TikTok lists without a stream for this viewer are skipped with the reason;
  MediaLab never tries to unlock them.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

from .config import Settings
from .errors import AppError, ErrorCode
from .jobs import DownloadPlan, JobManager, JobState
from .media import MediaProcessor
from .models import ResolutionOption, SeriesInfo
from .selection import BEST_OPTION_ID, apply_size_limit, short_side, build_options, choose_option
from .storage import (
    AnalysisStore,
    DeliveryState,
    DeliveryStore,
    build_filename,
    free_bytes,
    ensure_free_space,
    episode_filename,
    new_id,
    remove_tree_within,
    sanitise_filename_part,
)
from .user_settings import SettingsStore
from .validation import PLATFORM_LABELS, PLATFORM_TIKTOK, PLATFORM_X, ValidatedUrl

log = logging.getLogger(__name__)

MAX_CONCURRENCY = 4  # hard cap; the effective limit is also settings.max_concurrent_downloads
MAX_UNSAVED = 2
MAX_EPISODES = 500
MAX_ACTIVE_BATCHES = 2  # Short Drama and link batches together
TICK_SECONDS = 0.5
BATCH_DIR_PREFIX = "job-batch-"
OUTPUT_MODES = ("files", "zip", "merge")
URL_OUTPUT_MODES = ("files", "zip")
URL_PLATFORMS = (PLATFORM_X, PLATFORM_TIKTOK)
SOURCE_SHORTDRAMA = "shortdrama"
SOURCE_URLS = "urls"


class EpisodeState(str, Enum):
    PENDING = "pending"
    RESOLVING = "resolving"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    READY = "ready"              # files mode: waiting for the browser
    SAVING = "saving"            # files mode: the browser is receiving it
    SAVED = "saved"              # files mode: done
    DOWNLOADED = "downloaded"    # zip/merge: collected for packaging
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class BatchState(str, Enum):
    PLANNING = "planning"        # merge: choosing one quality for all episodes
    RUNNING = "running"
    PAUSED = "paused"
    NEEDS_DECISION = "needs_decision"  # zip/merge: some episodes failed; retry or continue
    PACKAGING = "packaging"
    READY = "ready"              # final file waiting for the browser
    SAVING = "saving"
    COMPLETED = "completed"
    PARTIAL = "partial"          # finished, but some episodes are missing from the result
    FAILED = "failed"            # packaging failed (collected episodes kept for a retry)
    CANCELLED = "cancelled"


IN_FLIGHT = frozenset({EpisodeState.RESOLVING, EpisodeState.DOWNLOADING, EpisodeState.PROCESSING})
WAITING = frozenset({EpisodeState.READY, EpisodeState.SAVING})
NOT_OK = frozenset({EpisodeState.FAILED, EpisodeState.SKIPPED, EpisodeState.CANCELLED})
RETRYABLE_STATES = NOT_OK
ACTIVE_BATCH = frozenset({BatchState.PLANNING, BatchState.RUNNING, BatchState.PAUSED, BatchState.PACKAGING,
                          BatchState.NEEDS_DECISION, BatchState.READY, BatchState.SAVING, BatchState.FAILED})
DONE_BATCH = frozenset({BatchState.COMPLETED, BatchState.PARTIAL, BatchState.CANCELLED})


@dataclass
class BatchEpisode:
    number: int
    item_id: str
    title: str | None
    duration_seconds: float | None = None
    state: EpisodeState = EpisodeState.PENDING
    available: bool = True
    job_id: str | None = None
    file_id: str | None = None
    filename: str | None = None
    size_bytes: int | None = None
    option_label: str | None = None
    note: str | None = None
    error: AppError | None = None
    attempts: int = 0
    stage: str | None = None
    percent: float | None = None
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    expected_bytes: int | None = None
    local_path: Path | None = None   # zip/merge: collected file
    planned: tuple[str, list[ResolutionOption]] | None = None  # merge plan: (quality, options)
    # Link batches: the analysed video this item downloads.
    url: ValidatedUrl | None = None
    analysis_id: str | None = None
    video_index: int = 1
    author: str | None = None
    thumbnail_url: str | None = None


@dataclass
class BatchResult:
    file_id: str
    filename: str
    size_bytes: int
    kind: str                      # "zip" | "mp4"
    method: str | None = None      # merge: "stream_copy" | "re_encoded"; zip: "stored"
    reason: str | None = None      # merge: why re-encoding was needed
    duration_seconds: float | None = None
    included: list[int] = field(default_factory=list)
    omitted: list[int] = field(default_factory=list)
    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None


@dataclass
class Batch:
    batch_id: str
    series_id: str
    series_title: str | None
    episode_count: int | None
    series_numbers: frozenset[int]
    quality: str
    strict: bool
    concurrency: int
    episodes: list[BatchEpisode]
    output: str = "files"
    allow_partial: bool = False
    state: BatchState = BatchState.RUNNING
    stage: str | None = None
    package_percent: float = 0.0
    plan_note: str | None = None
    error: AppError | None = None
    result: BatchResult | None = None
    partial_approved: bool = False
    held_since: float | None = None     # when collected files started waiting (decision/failure)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    worker: threading.Thread | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    source: str = SOURCE_SHORTDRAMA
    platform: str = "tiktok_shortdrama"
    stopped: bool = False  # links: cancelled while finished items were kept

    @property
    def packaged(self) -> bool:
        return self.output in ("zip", "merge")

    @property
    def noun(self) -> str:
        return "video" if self.source == SOURCE_URLS else "episode"


def range_label(numbers: list[int], series_numbers: frozenset[int], complete_allowed: bool, count: int | None) -> str:
    """``E01-E10``, ``E01, E03, E05``, ``E01-E40 (12 episodes)`` or ``Complete Series``."""
    nums = sorted(numbers)
    if complete_allowed and series_numbers and set(nums) == set(series_numbers):
        return "Complete Series"
    width = max(2, len(str(count or max(nums))))

    def e(n: int) -> str:
        return f"E{n:0{width}d}"
    if len(nums) == 1:
        return e(nums[0])
    if nums == list(range(nums[0], nums[-1] + 1)):
        return f"{e(nums[0])}-{e(nums[-1])}"
    if len(nums) <= 4:
        return ", ".join(e(n) for n in nums)
    return f"{e(nums[0])}-{e(nums[-1])} ({len(nums)} episodes)"


class BatchManager:
    def __init__(self, settings: Settings, settings_store: SettingsStore, provider, jobs: JobManager,
                 deliveries: DeliveryStore, processor: MediaProcessor | None = None,
                 analyses: AnalysisStore | None = None, router=None) -> None:
        self.settings = settings
        self.settings_store = settings_store
        self.provider = provider  # Short Drama provider (series lookup); None without one
        self.analyses = analyses
        self.router = router      # every platform's provider (link batches re-analyse expired items)
        self.jobs = jobs
        self.deliveries = deliveries
        self.processor = processor or jobs.processor
        self._batches: dict[str, Batch] = {}
        self._lock = threading.RLock()
        self._stopping = threading.Event()

    # --------------------------------------------------------------- public
    def create(self, series_id: str, numbers: list[int], quality: str = "best", strict: bool = False,
               concurrency: int = 1, output: str = "files", allow_partial: bool = False) -> Batch:
        if not numbers:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Select at least one episode.")
        if output not in OUTPUT_MODES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown output format.")
        wanted = sorted(set(numbers))
        if len(wanted) > MAX_EPISODES:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"A batch can hold at most {MAX_EPISODES} episodes.")
        concurrency = self._concurrency(concurrency)
        with self._lock:
            active = [b for b in self._batches.values() if b.state in ACTIVE_BATCH]
            same = next((b for b in active if b.source == SOURCE_SHORTDRAMA and b.series_id == series_id and b.output == output
                         and [e.number for e in b.episodes] == wanted), None)
            if same is not None:
                raise AppError(ErrorCode.BATCH_IN_PROGRESS, "A batch for exactly these episodes is already running.",
                               details={"batch_id": same.batch_id})
            if len(active) >= MAX_ACTIVE_BATCHES:
                raise AppError(ErrorCode.TOO_MANY_JOBS, "Two batches are already active. Wait for one to finish or "
                               "cancel it.")
        info: SeriesInfo = self.provider.series(series_id)
        by_number = {e.number: e for e in info.episodes}
        missing = [n for n in wanted if n not in by_number]
        if missing:
            raise AppError(ErrorCode.EPISODE_NOT_IN_SERIES,
                           f"Episode(s) {', '.join(map(str, missing[:10]))} aren't in this series.",
                           details={"episodes": missing[:50]})
        episodes = []
        for n in wanted:
            e = by_number[n]
            ep = BatchEpisode(number=n, item_id=e.item_id, title=e.title, duration_seconds=e.duration_seconds,
                              available=e.available)
            if not e.available:
                ep.state = EpisodeState.SKIPPED
                ep.error = self._unavailable_error(e.availability)
            episodes.append(ep)
        batch = Batch(new_id(), series_id, info.title, info.episode_count,
                      frozenset(e.number for e in info.episodes), quality, strict, concurrency, episodes,
                      output=output, allow_partial=allow_partial)
        if output == "merge" and quality == BEST_OPTION_ID and sum(e.available for e in episodes) > 1:
            batch.state, batch.stage = BatchState.PLANNING, "Choosing one quality for all episodes"
        with self._lock:
            # Re-check under the lock: the series lookup above ran unlocked.
            same = next((b for b in self._batches.values() if b.state in ACTIVE_BATCH and b.source == SOURCE_SHORTDRAMA
                         and b.series_id == series_id and b.output == output and [e.number for e in b.episodes] == wanted), None)
            if same is not None:
                raise AppError(ErrorCode.BATCH_IN_PROGRESS, "A batch for exactly these episodes is already running.",
                               details={"batch_id": same.batch_id})
            self._batches[batch.batch_id] = batch
            self._start_worker(batch)
        log.info("Batch %s: series %s, %d episodes, output=%s quality=%s strict=%s partial=%s concurrency=%d",
                 batch.batch_id, series_id, len(episodes), output, quality, strict, allow_partial, concurrency)
        return self.get(batch.batch_id)

    def _concurrency(self, requested: int) -> int:
        return max(1, min(int(requested), MAX_CONCURRENCY, self.settings.max_concurrent_downloads))

    def create_from_urls(self, platform: str, analysis_ids: list[str], quality: str = "best", output: str = "zip",
                         concurrency: int = 2, allow_partial: bool = False) -> Batch:
        """A batch of analysed X or TikTok videos, downloaded in the given order."""
        if self.analyses is None:
            raise AppError(ErrorCode.UNSUPPORTED_URL, "Link batches aren't available in this configuration.")
        if platform not in URL_PLATFORMS:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Bulk downloads are available for X and TikTok videos only.")
        if output not in URL_OUTPUT_MODES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Bulk downloads can be saved as a ZIP or as separate files.")
        limit = self.settings.max_bulk_urls
        if not analysis_ids:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Select at least one video.")
        if len(analysis_ids) > limit:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"A bulk download can hold at most {limit} videos.")
        if len(set(analysis_ids)) != len(analysis_ids):
            raise AppError(ErrorCode.VALIDATION_ERROR, "The same video was selected twice.")
        stored = [self.analyses.get(a) for a in analysis_ids]  # analysis_expired if one is gone
        items, seen = [], set()
        for n, a in enumerate(stored, 1):
            if a.url.platform != platform:
                raise AppError(ErrorCode.WRONG_PLATFORM, f"Item {n} isn't {PLATFORM_LABELS[platform]} video.")
            index = a.url.video_index if a.url.video_index in [v.index for v in a.post.videos] else a.post.videos[0].index
            key = (a.url.canonical_url, index)
            if key in seen:
                raise AppError(ErrorCode.VALIDATION_ERROR, f"Item {n} is a duplicate of an earlier item.")
            seen.add(key)
            video = a.video(index)
            items.append(BatchEpisode(
                number=n, item_id=a.post.post_id, title=video.title or a.post.text or None,
                duration_seconds=video.duration_seconds, url=a.url, analysis_id=a.analysis_id, video_index=index,
                author=a.post.author_handle or a.post.author_name, thumbnail_url=video.thumbnail_url,
            ))
        label = PLATFORM_LABELS[platform]
        batch = Batch(new_id(), "", f"{label} bulk download", None, frozenset(), quality, False,
                      self._concurrency(concurrency), items, output=output, allow_partial=allow_partial,
                      source=SOURCE_URLS, platform=platform)
        keys = sorted(seen)
        with self._lock:
            active = [b for b in self._batches.values() if b.state in ACTIVE_BATCH]
            same = next((b for b in active if b.source == SOURCE_URLS and b.platform == platform and b.output == output
                         and sorted((e.url.canonical_url, e.video_index) for e in b.episodes) == keys), None)
            if same is not None:
                raise AppError(ErrorCode.BATCH_IN_PROGRESS, "A bulk download of exactly these videos is already running.",
                               action="Open Downloads to follow it, or cancel it first.",
                               details={"batch_id": same.batch_id})
            if len(active) >= MAX_ACTIVE_BATCHES:
                raise AppError(ErrorCode.TOO_MANY_JOBS, "Two batches are already active. Wait for one to finish or "
                               "cancel it.")
            self._batches[batch.batch_id] = batch
            self._start_worker(batch)
        log.info("Batch %s: %d %s links, output=%s quality=%s partial=%s concurrency=%d", batch.batch_id, len(items),
                 label, output, quality, allow_partial, batch.concurrency)
        return self.get(batch.batch_id)

    def get(self, batch_id: str) -> Batch:
        with self._lock:
            batch = self._require(batch_id)
            return replace(batch, episodes=[replace(e) for e in batch.episodes], worker=None,
                           result=replace(batch.result) if batch.result else None)

    def pause(self, batch_id: str) -> Batch:
        with self._lock:
            batch = self._require(batch_id)
            if batch.state == BatchState.RUNNING:
                batch.state = BatchState.PAUSED
                batch.updated_at = time.time()
        return self.get(batch_id)

    def resume(self, batch_id: str) -> Batch:
        with self._lock:
            batch = self._require(batch_id)
            if batch.state == BatchState.PAUSED:
                batch.state = BatchState.RUNNING
                batch.updated_at = time.time()
                self._start_worker(batch)
        return self.get(batch_id)

    def proceed(self, batch_id: str) -> Batch:
        """zip/merge: build the output without the failed episodes, or retry failed packaging."""
        with self._lock:
            batch = self._require(batch_id)
            if not batch.packaged or batch.state not in (BatchState.NEEDS_DECISION, BatchState.FAILED):
                raise AppError(ErrorCode.VALIDATION_ERROR, "There's nothing to continue in this batch.")
            if not any(e.state == EpisodeState.DOWNLOADED for e in batch.episodes):
                raise AppError(ErrorCode.VALIDATION_ERROR, "No episode was downloaded, so there's nothing to package.")
            batch.partial_approved = True
            batch.state, batch.error, batch.held_since = BatchState.RUNNING, None, None
            batch.cancel_event = threading.Event()  # a stopped packaging run keeps its own (set) event
            batch.updated_at = time.time()
            self._start_worker(batch)
        return self.get(batch_id)

    def cancel(self, batch_id: str) -> Batch:
        """Short Drama: stop everything and delete unsaved and collected files.

        Link batches (v1.9) keep what already finished: waiting and running videos are
        cancelled, finished ones stay available (``files``: saved as usual; ``zip``: the batch
        waits for a decision, so the user can build the ZIP from them or cancel again to
        delete them). A second cancel, or cancelling when nothing finished, discards as above.
        """
        reason = AppError(ErrorCode.BATCH_CANCELLED, "The batch was cancelled.", retryable=False)
        with self._lock:
            batch = self._require(batch_id)
            if batch.state in DONE_BATCH:
                return self.get(batch_id)
            if batch.source == SOURCE_URLS and self._stop_keeping_finished(batch):
                return self.get(batch_id)
            batch.state, batch.stage = BatchState.CANCELLED, "Cancelled"
            batch.cancel_event.set()
            for ep in batch.episodes:
                if ep.state in IN_FLIGHT or ep.state == EpisodeState.PENDING:
                    if ep.job_id:
                        self.jobs.cancel(ep.job_id, reason)
                    ep.state, ep.error, ep.stage = EpisodeState.CANCELLED, reason, "Cancelled"
                elif ep.state == EpisodeState.READY and ep.file_id:
                    self.deliveries.discard(ep.file_id)
                    ep.state, ep.error, ep.stage = EpisodeState.CANCELLED, reason, "Cancelled (unsaved file deleted)"
                elif ep.state == EpisodeState.DOWNLOADED:
                    ep.state, ep.error, ep.stage = EpisodeState.CANCELLED, reason, "Cancelled (collected file deleted)"
            if batch.result and batch.result.file_id:
                self.deliveries.discard(batch.result.file_id)
            batch.updated_at = time.time()
            self._start_worker(batch)  # finishes cleanup (incl. a transfer still in progress)
        return self.get(batch_id)

    def _stop_keeping_finished(self, batch: Batch) -> bool:
        """Links: cancel unfinished items but keep finished ones. False if there's nothing to keep."""
        if batch.state in (BatchState.READY, BatchState.SAVING):
            return True  # the output is finished: nothing to cancel, it expires normally
        if batch.stopped:
            return False  # second cancel: discard
        kept = [e for e in batch.episodes if e.state in WAITING or e.state == EpisodeState.DOWNLOADED]
        if not kept:
            return False
        reason = AppError(ErrorCode.DOWNLOAD_CANCELLED, "Cancelled with the rest of the batch.", retryable=True)
        for ep in batch.episodes:
            self._cancel_episode(ep, reason)
        batch.stopped = True
        if batch.packaged:
            batch.cancel_event.set()  # stops a ZIP being built; the collected videos stay
            batch.state, batch.stage, batch.held_since = BatchState.NEEDS_DECISION, "Stopped", time.time()
            batch.error = AppError(
                ErrorCode.BATCH_PARTIAL, f"Stopped. {len(kept)} {batch.noun}(s) finished before you cancelled.",
                action="Build the ZIP from the finished videos, or cancel again to delete them.",
                details={"downloaded": [e.number for e in kept]})
        else:
            batch.stage = "Stopped: saving the finished videos"
            if batch.state == BatchState.PAUSED:
                batch.state = BatchState.RUNNING
        batch.updated_at = time.time()
        self._start_worker(batch)
        log.info("Batch %s stopped; %d finished item(s) kept", batch.batch_id, len(kept))
        return True

    def _cancel_episode(self, ep: BatchEpisode, reason: AppError) -> bool:
        if ep.state not in IN_FLIGHT and ep.state != EpisodeState.PENDING:
            return False
        if ep.job_id:
            self.jobs.cancel(ep.job_id, reason)
        ep.state, ep.error, ep.stage, ep.percent = EpisodeState.CANCELLED, reason, "Cancelled", None
        return True

    def cancel_item(self, batch_id: str, number: int) -> Batch:
        """Cancel one waiting or running item; the rest of the batch continues."""
        with self._lock:
            batch = self._require(batch_id)
            ep = next((e for e in batch.episodes if e.number == number), None)
            if ep is None:
                raise AppError(ErrorCode.ITEM_NOT_FOUND, f"Item {number} isn't part of this batch.")
            if ep.state == EpisodeState.CANCELLED:
                return self.get(batch_id)  # idempotent
            reason = AppError(ErrorCode.DOWNLOAD_CANCELLED, "You cancelled this item.", retryable=True)
            if not self._cancel_episode(ep, reason):
                raise AppError(ErrorCode.VALIDATION_ERROR, f"Only waiting or downloading {batch.noun}s can be "
                               f"cancelled; this one is {ep.state.value}.")
            batch.updated_at = time.time()
            if batch.state not in DONE_BATCH:
                self._start_worker(batch)
        log.info("Batch %s: item %d cancelled", batch_id, number)
        return self.get(batch_id)

    def retry(self, batch_id: str, number: int) -> Batch:
        with self._lock:
            batch = self._require(batch_id)
            if batch.state in (BatchState.PACKAGING, BatchState.READY, BatchState.SAVING):
                raise AppError(ErrorCode.VALIDATION_ERROR, "The output is already being packaged or saved.")
            if batch.packaged and batch.state == BatchState.CANCELLED:
                raise AppError(ErrorCode.VALIDATION_ERROR, "This batch was cancelled; start a new one.")
            ep = next((e for e in batch.episodes if e.number == number), None)
            if ep is None:
                raise AppError(ErrorCode.EPISODE_NOT_IN_SERIES if batch.source == SOURCE_SHORTDRAMA
                               else ErrorCode.ITEM_NOT_FOUND, f"Item {number} isn't part of this batch.")
            if ep.state not in RETRYABLE_STATES:
                raise AppError(ErrorCode.VALIDATION_ERROR, f"{batch.noun.capitalize()} {number} is "
                               f"{ep.state.value}; only failed, skipped or cancelled ones can be retried.")
            self._reset(ep)
            batch.stopped = False
            if batch.state in (BatchState.COMPLETED, BatchState.PARTIAL, BatchState.CANCELLED,
                               BatchState.NEEDS_DECISION, BatchState.FAILED):
                batch.state, batch.error, batch.held_since = BatchState.RUNNING, None, None
            batch.updated_at = time.time()
            self._start_worker(batch)
        return self.get(batch_id)

    def active_dir_names(self) -> set[str]:
        with self._lock:
            return {self._dir(b).name for b in self._batches.values() if b.state not in DONE_BATCH}

    def prune(self, now: float | None = None) -> int:
        now = now or time.time()
        removed = 0
        with self._lock:
            for b in list(self._batches.values()):
                # Collected episodes waiting for a decision/retry expire like unsaved files.
                if b.held_since and now - b.held_since > self.settings.delivery_retention_seconds \
                        and b.state in (BatchState.NEEDS_DECISION, BatchState.FAILED):
                    self._drop_collected(b, "Not packaged in time; the downloaded episodes were deleted.")
                    b.state, b.stage = BatchState.CANCELLED, "Expired"
                    b.error = AppError(ErrorCode.BATCH_CANCELLED, "The batch waited too long for a decision, so its "
                                       "downloaded episodes were deleted.", action="Start the batch again.")
                    removed += 1
            old = [k for k, b in self._batches.items()
                   if b.state in DONE_BATCH and now - b.updated_at > self.settings.job_ttl_seconds]
            for k in old:
                del self._batches[k]
        return removed + len(old)

    def shutdown(self) -> None:
        self._stopping.set()
        with self._lock:
            for b in self._batches.values():
                b.cancel_event.set()

    # -------------------------------------------------------------- helpers
    def _require(self, batch_id: str) -> Batch:
        batch = self._batches.get(batch_id)
        if batch is None:
            raise AppError(ErrorCode.BATCH_NOT_FOUND, "This batch no longer exists.")
        return batch

    def _dir(self, batch: Batch) -> Path:
        return self.settings.temp_dir / f"{BATCH_DIR_PREFIX}{batch.batch_id}"

    @staticmethod
    def _reset(ep: BatchEpisode) -> None:
        if ep.local_path is not None:
            ep.local_path.unlink(missing_ok=True)
        ep.state = EpisodeState.PENDING
        ep.error = ep.job_id = ep.file_id = ep.note = ep.stage = ep.local_path = None
        ep.percent, ep.downloaded_bytes, ep.total_bytes = None, 0, None

    @staticmethod
    def _unavailable_error(availability: str) -> AppError:
        if availability == "login_required":
            return AppError(ErrorCode.LOGIN_REQUIRED, "TikTok only plays this episode to signed-in viewers. Link "
                            "your TikTok account in Settings.", retryable=False)
        return AppError(ErrorCode.ACCOUNT_ACCESS_UNAVAILABLE, "TikTok lists no playable video of this episode for "
                        "your account (it may need to be unlocked in TikTok).", retryable=False)

    def _drop_collected(self, batch: Batch, note: str) -> None:
        for ep in batch.episodes:
            if ep.state == EpisodeState.DOWNLOADED:
                ep.state, ep.stage, ep.local_path = EpisodeState.FAILED, note, None
                ep.error = AppError(ErrorCode.FILE_NOT_FOUND, note, action="Retry this episode.")
        remove_tree_within(self.settings.temp_dir, self._dir(batch))

    def _start_worker(self, batch: Batch) -> None:
        if batch.worker is not None and batch.worker.is_alive():
            return
        batch.worker = threading.Thread(target=self._work, args=(batch.batch_id,), daemon=True,
                                        name=f"medialab-batch-{batch.batch_id[:8]}")
        batch.worker.start()

    # --------------------------------------------------------------- worker
    def _work(self, batch_id: str) -> None:
        while not self._stopping.is_set():
            try:
                if not self._tick(batch_id):
                    return
            except Exception:  # noqa: BLE001
                log.exception("Batch %s tick failed", batch_id)
            time.sleep(TICK_SECONDS)

    def _tick(self, batch_id: str) -> bool:
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None:
                return False
            if batch.state == BatchState.PLANNING:
                plan_needed = True
            else:
                plan_needed = False
                self._refresh(batch)
                if batch.state == BatchState.CANCELLED:
                    return self._cleanup_cancelled(batch)
                if batch.state in (BatchState.READY, BatchState.SAVING):
                    return True
                if batch.state in DONE_BATCH or batch.state in (BatchState.NEEDS_DECISION, BatchState.FAILED):
                    return False
                if self._all_episodes_final(batch):
                    if not batch.packaged:
                        self._finish_files(batch)
                        return False
                    if not self._ready_to_package(batch):
                        return False
                    batch.state, batch.stage, batch.package_percent = BatchState.PACKAGING, "Verifying episodes", 0.0
                    package = True
                else:
                    package = False
                    if batch.state != BatchState.RUNNING:
                        return True
                    in_flight = sum(1 for e in batch.episodes if e.state in IN_FLIGHT)
                    waiting = sum(1 for e in batch.episodes if e.state in WAITING)
                    limit = batch.concurrency + (MAX_UNSAVED - 1 if not batch.packaged else 0)
                    if in_flight >= batch.concurrency or in_flight + waiting >= limit:
                        return True
                    ep = next((e for e in batch.episodes if e.state == EpisodeState.PENDING), None)
                    if ep is None:
                        return True
                    ep.attempts += 1
                    if batch.source == SOURCE_URLS:
                        ep.state, ep.stage = EpisodeState.RESOLVING, "Preparing the download"
                        make = self._url_plan(ep.analysis_id, ep.video_index, ep.url, batch.quality, ep.number)
                    else:
                        ep.state, ep.stage = EpisodeState.RESOLVING, "Looking up the episode"
                        make = self._episode_plan(batch.series_id, batch.series_title, batch.episode_count,
                                                  batch.quality, batch.strict, ep.planned, ep.number)
        if plan_needed:
            self._plan_merge(batch_id)
            return True
        if package:
            self._package(batch_id)
            return True
        self._launch(batch_id, ep.number, make)
        return True

    # ------------------------------------------------------------ planning
    def _plan_merge(self, batch_id: str) -> None:
        """Analyse every episode and pick the highest resolution all of them offer (stream-copyable)."""
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None or batch.state != BatchState.PLANNING:
                return
            targets = [(e.number) for e in batch.episodes if e.state == EpisodeState.PENDING]
            series_id = batch.series_id
        options: dict[int, list[ResolutionOption]] = {}
        for n in targets:
            if batch.cancel_event.is_set():
                return
            try:
                url = self.provider.episode_url(series_id, n)
                post = self.provider.extract(url)
                options[n] = build_options(post.videos[0], self.settings_store.get().max_file_size_bytes)
            except AppError as exc:
                with self._lock:
                    ep = self._episode(batch_id, n)
                    if ep is not None and ep.state == EpisodeState.PENDING:
                        ep.state, ep.error, ep.stage = EpisodeState.FAILED, exc, "Failed"
            with self._lock:
                ep = self._episode(batch_id, n)
                if ep is not None:
                    ep.stage = "Checked available qualities"
        # Renditions offered by every analysed episode: (short side, video codec family, audio conversion).
        def key(o: ResolutionOption):
            return (short_side(o.width, o.height), (o.vcodec or "").split(".")[0])
        common = None
        for opts in options.values():
            keys = {key(o) for o in opts if o.downloadable and not o.is_best and o.has_audio is not False}
            common = keys if common is None else common & keys
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None or batch.state != BatchState.PLANNING:
                return
            if common:
                best = max(common, key=lambda k: k[0] or 0)
                quality = f"{best[0]}p"
                for ep in batch.episodes:
                    if ep.number in options:
                        ep.planned = (quality, options[ep.number])
                        ep.stage = None
                batch.quality, batch.strict = quality, True
                batch.plan_note = (f"All episodes use {quality} ({best[1].upper() or 'video'}), the highest quality every "
                                   "selected episode offers, so they can be joined without re-encoding.")
            else:
                batch.plan_note = ("The selected episodes don't share one quality, so each uses its best and the "
                                   "merge re-encodes them to a common format.")
                for ep in batch.episodes:
                    if ep.number in options:
                        ep.planned = (BEST_OPTION_ID, options[ep.number])
                        ep.stage = None
            batch.state, batch.stage = BatchState.RUNNING, None
            log.info("Batch %s merge plan: %s", batch_id, batch.plan_note)

    # ------------------------------------------------------------ episodes
    def _episode_plan(self, series_id: str, title: str | None, count: int | None, quality: str, strict: bool,
                      planned, number: int):
        def make() -> tuple[DownloadPlan, ResolutionOption, str | None]:
            url = self.provider.episode_url(series_id, number)
            limit = self.settings_store.get().max_file_size_bytes
            if planned is not None:
                options = planned[1]
                video_formats = None
            else:
                post = self.provider.extract(url)
                options = build_options(post.videos[0], limit)
                video_formats = {f.format_id: f for f in post.videos[0].formats}
            option, note = choose_option(options, quality, strict)
            plan = DownloadPlan(
                url=url, video_index=1, option=option,
                filename=episode_filename(title, number, count),
                expected_sizes=({fid: (video_formats[fid].filesize or video_formats[fid].filesize_approx)
                                 if fid in video_formats else None for fid in option.format_ids}
                                if video_formats else {}),
                provider=self.provider.name, max_file_size_bytes=limit, platform_label="TikTok Short Drama",
            )
            return plan, option, note
        return make

    def _url_plan(self, analysis_id: str | None, video_index: int, url: ValidatedUrl | None, quality: str,
                  number: int):
        def make() -> tuple[DownloadPlan, ResolutionOption, str | None]:
            from .bulk import analyse_validated

            user = self.settings_store.get()
            try:
                analysis = self.analyses.get(analysis_id or "")
            except AppError as exc:
                # The analysis expired (e.g. a retry an hour later): analyse the same link once more.
                if exc.code != ErrorCode.ANALYSIS_EXPIRED or url is None or self.router is None:
                    raise
                analysis = analyse_validated(self.router, self.analyses, url, url.platform,
                                             self.settings.socket_timeout_seconds)
            if analysis.provider == "fxtwitter" and not user.fxtwitter_fallback:
                raise AppError(ErrorCode.FORBIDDEN, "This video was found through the FxTwitter fallback, which is "
                               "now turned off in Settings.", action="Turn the fallback on again, or remove this video.")
            video = analysis.video(video_index)
            options = apply_size_limit(analysis.options.get(video.index, []), user.max_file_size_bytes)
            option, note = choose_option(options, quality, strict=False, above="closest")
            formats = {f.format_id: f for f in video.formats}
            label = analysis.url.platform_label
            plan = DownloadPlan(
                url=analysis.url, video_index=video.index, option=option,
                filename=build_filename(analysis.post, video, option, len(analysis.post.videos), label),
                expected_sizes={fid: (formats[fid].filesize or formats[fid].filesize_approx) if fid in formats else None
                                for fid in option.format_ids},
                provider=analysis.provider, max_file_size_bytes=user.max_file_size_bytes, platform_label=label,
            )
            return plan, option, note
        return make

    def _launch(self, batch_id: str, number: int, make) -> None:
        try:
            plan, option, note = make()
            if option.known_size is not None:
                ensure_free_space(self.settings.temp_dir, option.known_size, self.settings.min_free_space_mb * 1024 * 1024)
            snap = self.jobs.submit(plan)
        except AppError as exc:
            with self._lock:
                ep = self._episode(batch_id, number)
                if ep is None or ep.state != EpisodeState.RESOLVING:
                    return
                if exc.code == ErrorCode.TOO_MANY_JOBS:
                    ep.state, ep.stage = EpisodeState.PENDING, "Waiting for a free download slot"
                    ep.attempts -= 1
                else:
                    ep.state, ep.error, ep.stage = EpisodeState.FAILED, exc, "Failed"
                    log.info("Batch %s item %d failed before download: %s %s", batch_id, number, exc.code.value,
                             exc.message)
            return
        except Exception:  # noqa: BLE001
            log.exception("Batch %s item %d crashed", batch_id, number)
            with self._lock:
                ep = self._episode(batch_id, number)
                if ep is not None and ep.state == EpisodeState.RESOLVING:
                    ep.state, ep.stage = EpisodeState.FAILED, "Failed"
                    ep.error = AppError(ErrorCode.DOWNLOAD_FAILED, "This item failed unexpectedly.")
            return
        with self._lock:
            ep = self._episode(batch_id, number)
            batch = self._batches.get(batch_id)
            if ep is None or batch is None or ep.state != EpisodeState.RESOLVING:
                self.jobs.cancel(snap.job_id, AppError(ErrorCode.BATCH_CANCELLED, "The batch was cancelled."))
                return
            ep.job_id, ep.option_label, ep.note = snap.job_id, option.label, note
            ep.expected_bytes = option.known_size
            ep.state, ep.stage = EpisodeState.DOWNLOADING, snap.stage or "Queued"

    def _episode(self, batch_id: str, number: int) -> BatchEpisode | None:
        batch = self._batches.get(batch_id)
        return next((e for e in batch.episodes if e.number == number), None) if batch else None

    def _refresh(self, batch: Batch) -> None:
        for ep in batch.episodes:
            if ep.state == EpisodeState.CANCELLED and ep.job_id:
                # A cancelled job may still finish before it notices; never leave its file behind.
                try:
                    snap = self.jobs.get(ep.job_id)
                except AppError:
                    ep.job_id = None
                    continue
                if snap.state == JobState.COMPLETED and snap.result:
                    self.deliveries.discard(snap.result.file_id)
                if snap.state in (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED):
                    ep.job_id = None
                continue
            if ep.state in (EpisodeState.DOWNLOADING, EpisodeState.PROCESSING) and ep.job_id:
                try:
                    snap = self.jobs.get(ep.job_id)
                except AppError:
                    ep.state, ep.stage = EpisodeState.FAILED, "Failed"
                    ep.error = AppError(ErrorCode.JOB_NOT_FOUND, "The download job disappeared.")
                    continue
                ep.stage, ep.percent = snap.stage, snap.percent
                ep.downloaded_bytes, ep.total_bytes = snap.downloaded_bytes, snap.total_bytes
                if snap.state == JobState.PROCESSING:
                    ep.state = EpisodeState.PROCESSING
                elif snap.state == JobState.COMPLETED and snap.result:
                    ep.file_id, ep.filename, ep.size_bytes = (snap.result.file_id, snap.result.filename,
                                                              snap.result.size_bytes)
                    if batch.packaged:
                        dest = self._dir(batch) / f"E{ep.number:04d}.mp4"
                        if self.deliveries.take(ep.file_id, dest) is None:
                            ep.state, ep.stage = EpisodeState.FAILED, "Failed"
                            ep.error = AppError(ErrorCode.FILE_NOT_FOUND, "The finished episode went missing.")
                        else:
                            ep.local_path, ep.file_id = dest, None
                            ep.state, ep.stage, ep.percent = EpisodeState.DOWNLOADED, "Downloaded", 100.0
                    else:
                        ep.state, ep.stage, ep.percent = EpisodeState.READY, "Ready to save", 100.0
                elif snap.state == JobState.FAILED:
                    ep.state, ep.stage = EpisodeState.FAILED, "Failed"
                    ep.error = snap.error or AppError(ErrorCode.DOWNLOAD_FAILED, snap.error_message or "Download failed.")
                elif snap.state == JobState.CANCELLED:  # cancelled outside the batch (e.g. /api/jobs/{id}/cancel)
                    ep.state, ep.stage, ep.job_id = EpisodeState.CANCELLED, "Cancelled", None
                    ep.error = snap.error or AppError(ErrorCode.DOWNLOAD_CANCELLED, "The download was cancelled.")
            elif ep.state in WAITING and ep.file_id:
                d = self.deliveries.status(ep.file_id)
                if d is None or d.state == DeliveryState.EXPIRED:
                    ep.state, ep.stage = EpisodeState.FAILED, "Not saved in time"
                    ep.error = AppError(ErrorCode.FILE_NOT_FOUND, "The finished episode wasn't saved before it "
                                        "expired, so MediaLab deleted it.", action="Retry this episode.")
                elif d.state == DeliveryState.DELIVERED:
                    ep.state, ep.stage = EpisodeState.SAVED, "Saved by your browser"
                elif d.state == DeliveryState.DELIVERING:
                    ep.state, ep.stage = EpisodeState.SAVING, "Your browser is saving it"
                elif d.state == DeliveryState.READY:
                    if ep.state == EpisodeState.SAVING:
                        ep.note = "The browser transfer was interrupted; save it again."
                    ep.state = EpisodeState.READY
                    if batch.state == BatchState.CANCELLED:
                        self.deliveries.discard(ep.file_id)
                        ep.state, ep.stage = EpisodeState.CANCELLED, "Cancelled (unsaved file deleted)"
        if batch.result is not None and batch.state in (BatchState.READY, BatchState.SAVING):
            d = self.deliveries.status(batch.result.file_id)
            if d is None or d.state == DeliveryState.EXPIRED:
                batch.state, batch.stage = BatchState.CANCELLED, "Not saved in time"
                batch.error = AppError(ErrorCode.FILE_NOT_FOUND, "The finished file wasn't saved before it expired, "
                                       "so MediaLab deleted it.", action="Start the batch again.")
                remove_tree_within(self.settings.temp_dir, self._dir(batch))
            elif d.state == DeliveryState.DELIVERING:
                batch.state, batch.stage = BatchState.SAVING, "Transferring to browser"
            elif d.state == DeliveryState.READY:
                if batch.state == BatchState.SAVING:
                    batch.stage = "The transfer was interrupted; click Save again"
                else:
                    batch.stage = "Ready to save"
                batch.state = BatchState.READY
            elif d.state == DeliveryState.DELIVERED:
                batch.stage = "Cleaning up"
                remove_tree_within(self.settings.temp_dir, self._dir(batch))
                batch.state = BatchState.PARTIAL if batch.result.omitted else BatchState.COMPLETED
                batch.stage = "Saved by your browser"
                log.info("Batch %s delivered: %s", batch.batch_id, batch.result.filename)
        batch.updated_at = time.time()

    def _all_episodes_final(self, batch: Batch) -> bool:
        done = NOT_OK | ({EpisodeState.DOWNLOADED} if batch.packaged else {EpisodeState.SAVED})
        return all(e.state in done for e in batch.episodes)

    def _finish_files(self, batch: Batch) -> None:
        ok = all(e.state == EpisodeState.SAVED for e in batch.episodes)
        batch.state = BatchState.COMPLETED if ok else BatchState.PARTIAL
        log.info("Batch %s finished: %s", batch.batch_id, batch.state.value)

    def _ready_to_package(self, batch: Batch) -> bool:
        failed = [e.number for e in batch.episodes if e.state in NOT_OK]
        got = [e for e in batch.episodes if e.state == EpisodeState.DOWNLOADED]
        if not got:
            batch.state, batch.stage = BatchState.PARTIAL, "Nothing to package"
            batch.error = AppError(ErrorCode.BATCH_PARTIAL, f"No selected {batch.noun} could be downloaded, so no "
                                   "ZIP was created.", action=f"Retry the failed {batch.noun}s.")
            return False
        if failed and not (batch.allow_partial or batch.partial_approved):
            batch.state, batch.stage, batch.held_since = BatchState.NEEDS_DECISION, "Waiting for your decision", time.time()
            batch.error = AppError(
                ErrorCode.BATCH_PARTIAL,
                f"{batch.noun.capitalize()}(s) {', '.join(map(str, failed))} couldn't be downloaded, so the "
                f"{'ZIP' if batch.output == 'zip' else 'merged video'} wasn't created yet.",
                action=f"Retry those {batch.noun}s, or continue with the {len(got)} downloaded {batch.noun}(s).",
                details={"failed": failed, "downloaded": [e.number for e in got]},
            )
            return False
        return True

    # ----------------------------------------------------------- packaging
    def _package(self, batch_id: str) -> None:
        from .packaging import build_zip, merge_mp4

        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None or batch.state != BatchState.PACKAGING:
                return
            got = sorted((e for e in batch.episodes if e.state == EpisodeState.DOWNLOADED), key=lambda e: e.number)
            omitted = [e.number for e in batch.episodes if e.state != EpisodeState.DOWNLOADED]
            suffix = f" (partial, {len(got)} of {len(batch.episodes)})" if omitted else ""
            if batch.source == SOURCE_URLS:
                # Input order, numbered so names never collide: "01 - <author> - <text> [<id>] 720p.mp4".
                width = max(2, len(str(len(batch.episodes))))
                items = [(e.local_path, f"{e.number:0{width}d} - {e.filename or 'video.mp4'}", e.number) for e in got]
                single_name = got[0].filename if got else None
                label = f"{len(items)} video{'s' if len(items) != 1 else ''}"
                title = f"MediaLab {PLATFORM_LABELS.get(batch.platform, 'video')} videos " \
                        f"{time.strftime('%Y-%m-%d %H%M', time.localtime(batch.created_at))}"
            else:
                items = [(e.local_path, episode_filename(batch.series_title, e.number, batch.episode_count), e.number)
                         for e in got]
                single_name = items[0][1] if items else None
                label = range_label([n for *_, n in items], batch.series_numbers, not omitted, batch.episode_count)
                title = sanitise_filename_part(batch.series_title, 120) or "Short Drama"
            output, cancel, workdir = batch.output, batch.cancel_event, self._dir(batch)
            limit = self.settings_store.get().batch_output_max_bytes
            manifest = self._manifest(batch, items, omitted) if omitted and output == "zip" else None

        def progress(p: float, stage: str | None = None) -> None:
            with self._lock:
                b = self._batches.get(batch_id)
                if b is not None and b.state == BatchState.PACKAGING:
                    b.package_percent = round(p, 1)
                    if stage:
                        b.stage = stage

        try:
            if any(not p or not p.is_file() for p, *_ in items):
                raise AppError(ErrorCode.FILE_NOT_FOUND, "A downloaded episode is missing from temporary storage.",
                               action="Retry the batch.")
            total = sum(p.stat().st_size for p, *_ in items)
            if total > limit:
                raise AppError(ErrorCode.BATCH_OUTPUT_TOO_LARGE,
                               f"The episodes add up to {total // 2**20:,} MB, above the {limit // 2**20:,} MB batch "
                               "output limit (change it in Settings).")
            reserve = self.settings.min_free_space_mb * 2**20
            free = free_bytes(self.settings.temp_dir)
            if free < total + reserve:
                raise AppError(ErrorCode.INSUFFICIENT_SPACE,
                               f"Packaging needs about {(total + reserve) // 2**20:,} MB of free temporary space, but "
                               f"only {free // 2**20:,} MB is free.", retryable=True)
            if len(items) == 1:
                # One episode: deliver it as a normal MP4 (no archive, no processing).
                final = items[0][0]
                filename = single_name or items[0][1]
                kind, method, reason, duration = "mp4", None, None, None
                progress(100, "Verifying final output")
                probe = self.processor.probe(final)
            elif output == "zip":
                progress(0, "Packaging ZIP")
                final = workdir / "output.zip"
                build_zip([(p, name) for p, name, _ in items], final, manifest=manifest, cancel=cancel,
                          progress=lambda p: progress(p, "Packaging ZIP" if p < 96 else "Verifying final output"),
                          delete_sources=False)
                filename = f"{title} - {label}{suffix}.zip"
                kind, method, reason, duration, probe = "zip", "stored", None, None, None
            else:
                progress(0, "Merging videos")
                final = workdir / "output.mp4"
                merged = merge_mp4(self.processor, [p for p, *_ in items], final, cancel=cancel,
                                   progress=lambda p: progress(p, "Merging videos" if p < 60 else "Verifying final output"))
                filename = f"{title} - {label}{suffix}.mp4"
                kind, method, reason, duration = "mp4", merged.method, merged.reason, merged.duration
                probe = self.processor.probe(final)
            size = final.stat().st_size
            if size > limit:
                raise AppError(ErrorCode.BATCH_OUTPUT_TOO_LARGE,
                               f"The finished file is {size // 2**20:,} MB, above the {limit // 2**20:,} MB batch "
                               "output limit (change it in Settings).")
            delivery = self.deliveries.add(final, filename)
        except AppError as exc:
            with self._lock:
                b = self._batches.get(batch_id)
                if b is None:
                    return
                if exc.code == ErrorCode.BATCH_CANCELLED or b.state == BatchState.CANCELLED:
                    return
                b.state, b.stage, b.error, b.held_since = BatchState.FAILED, "Packaging failed", exc, time.time()
                log.info("Batch %s packaging failed: %s %s", batch_id, exc.code.value, exc.message)
            return
        except Exception:  # noqa: BLE001
            log.exception("Batch %s packaging crashed", batch_id)
            with self._lock:
                b = self._batches.get(batch_id)
                if b is not None and b.state == BatchState.PACKAGING:
                    b.state, b.stage, b.held_since = BatchState.FAILED, "Packaging failed", time.time()
                    b.error = AppError(ErrorCode.MERGE_FAILED if output == "merge" else ErrorCode.ZIP_FAILED,
                                       "Packaging failed unexpectedly.", retryable=True)
            return
        with self._lock:
            b = self._batches.get(batch_id)
            if b is None or b.state != BatchState.PACKAGING:
                self.deliveries.discard(delivery.file_id)
                return
            b.result = BatchResult(
                file_id=delivery.file_id, filename=delivery.filename, size_bytes=delivery.size_bytes, kind=kind,
                method=method, reason=reason, duration_seconds=duration or (probe.duration_seconds if probe else None),
                included=[n for *_, n in items], omitted=omitted,
                width=probe.width if probe else None, height=probe.height if probe else None,
                video_codec=probe.video_codec if probe else None, audio_codec=probe.audio_codec if probe else None,
            )
            b.state, b.stage, b.package_percent = BatchState.READY, "Ready to save", 100.0
            if len(items) > 1:
                # Only now, with the output verified and handed over, are the collected videos
                # removed: a failed or stopped packaging run can always be retried from them.
                for p, *_ in items:
                    p.unlink(missing_ok=True)
            log.info("Batch %s packaged %s (%d bytes, %s)", batch_id, delivery.filename, delivery.size_bytes, method)

    @staticmethod
    def _manifest(batch: Batch, items, omitted: list[int]) -> str:
        if batch.source == SOURCE_URLS:
            # Titles and reasons only: no links, signed media URLs or account data.
            lines = [f"{batch.series_title}", "Created by MediaLab", "", "Included videos:"]
            lines += [f"  {name}" for _, name, _ in items]
            lines += ["", "Not included:"]
            for e in batch.episodes:
                if e.number in omitted:
                    reason = e.error.message if e.error else e.state.value
                    what = sanitise_filename_part(e.title or e.author, 60) or f"video {e.item_id}"
                    lines.append(f"  {e.number:02d}  {what}: {e.state.value}, {reason}")
            return "\n".join(lines) + "\n"
        lines = [f"Series: {batch.series_title or batch.series_id}", "Created by MediaLab", "",
                 "Included episodes:"]
        lines += [f"  E{n:02d}  {name}" for _, name, n in items]
        lines += ["", "Not included:"]
        for e in batch.episodes:
            if e.number in omitted:
                reason = e.error.message if e.error else e.state.value
                lines.append(f"  E{e.number:02d}  {e.state.value}: {reason}")
        return "\n".join(lines) + "\n"

    def _cleanup_cancelled(self, batch: Batch) -> bool:
        """Remove collected files once nothing is streaming. Returns True while waiting."""
        if any(e.state == EpisodeState.SAVING for e in batch.episodes):
            return True
        if any(e.state in IN_FLIGHT or (e.state == EpisodeState.CANCELLED and e.job_id) for e in batch.episodes):
            return True
        remove_tree_within(self.settings.temp_dir, self._dir(batch))
        return False
