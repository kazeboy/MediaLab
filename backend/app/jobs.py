"""Download job manager.

Jobs run on a bounded thread pool (``MAX_CONCURRENT_DOWNLOADS`` workers); extra
jobs wait in the ``queued`` state. Every job moves through an explicit state
machine:

    queued -> downloading -> processing -> completed
       \\-----------\\--------------\\------> failed
       \\-----------\\--------------\\------> cancelled

Each job gets its own temporary directory, which is always removed when the
job ends, whether it succeeded, failed or was cancelled.

Cancellation (v1.9) is immediate and final: :meth:`JobManager.cancel` moves the job
to ``cancelled`` under the manager lock and sets its cancel event. The worker then
stops at its next download progress update, and any FFmpeg/FFprobe process it is
running is killed (:meth:`MediaProcessor.cancellable`). Completing a job happens
under the same lock, after a state check, so a cancelled job can never become
``completed`` and its output is never handed to the browser.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from enum import Enum

from .config import Settings
from .errors import AppError, ErrorCode
from .media import MediaProcessor, ProbeResult
from .models import ResolutionOption
from .providers.base import ProgressUpdate, VideoProvider
from .storage import JOB_DIR_PREFIX, DeliveryStore, new_id, remove_tree_within
from .validation import ValidatedUrl

log = logging.getLogger(__name__)


class JobState(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.DOWNLOADING, JobState.FAILED, JobState.CANCELLED}),
    JobState.DOWNLOADING: frozenset({JobState.PROCESSING, JobState.FAILED, JobState.CANCELLED}),
    JobState.PROCESSING: frozenset({JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}),
    JobState.COMPLETED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.CANCELLED: frozenset(),
}

ACTIVE_STATES = frozenset({JobState.QUEUED, JobState.DOWNLOADING, JobState.PROCESSING})
TERMINAL_STATES = frozenset({JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED})


class _Stopped(Exception):
    """The job was cancelled while its worker was still running."""


class InvalidTransition(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadPlan:
    url: ValidatedUrl
    video_index: int
    option: ResolutionOption
    filename: str
    # Sizes known from analysis, used until the downloader reports real totals.
    expected_sizes: dict[str, int | None] = field(default_factory=dict)
    # Provider that produced the analysis; the same one must download it.
    provider: str | None = None
    # Size limit in force when the job was submitted. Later settings changes
    # apply to new jobs only, never to a running one.
    max_file_size_bytes: int = 8192 * 1024 * 1024
    platform_label: str = "X"


@dataclass(frozen=True)
class StreamProgress:
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    total_is_estimate: bool = True


@dataclass(frozen=True)
class CompletedFile:
    file_id: str
    filename: str
    size_bytes: int
    probe: ProbeResult


@dataclass
class Job:
    job_id: str
    plan: DownloadPlan
    state: JobState = JobState.QUEUED
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: float | None = None
    stage: str | None = "Waiting for a free download slot"
    streams: dict[str, StreamProgress] = field(default_factory=dict)
    speed_bytes_per_second: float | None = None
    eta_seconds: float | None = None
    result: CompletedFile | None = None
    error: AppError | None = None
    # Set when MediaLab itself aborts a download (size/time limit, cancellation), so the
    # real reason survives even if the downloader wraps the exception.
    abort_reason: AppError | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    worker_running: bool = False  # its temporary folder may still be in use

    def transition(self, new_state: JobState) -> None:
        if new_state not in ALLOWED_TRANSITIONS[self.state]:
            raise InvalidTransition(f"{self.state.value} -> {new_state.value} is not allowed")
        self.state = new_state
        self.updated_at = time.time()

    # Aggregated progress across the video (+ audio) streams.
    @property
    def downloaded_bytes(self) -> int:
        return sum(s.downloaded_bytes for s in self.streams.values())

    @property
    def total_bytes(self) -> tuple[int | None, bool]:
        """(total, is_estimate). None if any stream's size is unknown."""
        total, estimate = 0, False
        for fid in self.plan.option.format_ids:
            stream = self.streams.get(fid)
            if stream is not None and stream.total_bytes is not None:
                total += stream.total_bytes
                estimate = estimate or stream.total_is_estimate
            elif self.plan.expected_sizes.get(fid) is not None:
                total += self.plan.expected_sizes[fid]  # type: ignore[operator]
                estimate = True
            else:
                return None, True
        return total, estimate

    @property
    def percent(self) -> float | None:
        if self.state == JobState.COMPLETED:
            return 100.0
        if self.state in (JobState.QUEUED, JobState.FAILED, JobState.CANCELLED):
            return 0.0 if self.state == JobState.QUEUED else None
        total, _ = self.total_bytes
        if not total:
            return None
        # Never show 100% before the file is actually finished and verified.
        return round(min(self.downloaded_bytes / total * 100, 99.9), 1)


@dataclass(frozen=True)
class JobSnapshot:
    """Immutable copy of a job, safe to hand to the API layer."""

    job_id: str
    state: JobState
    option: ResolutionOption
    video_index: int
    created_at: float
    updated_at: float
    stage: str | None
    downloaded_bytes: int
    total_bytes: int | None
    total_is_estimate: bool
    percent: float | None
    speed_bytes_per_second: float | None
    eta_seconds: float | None
    result: CompletedFile | None
    error_code: str | None
    error_message: str | None
    error: AppError | None = None


class JobManager:
    def __init__(
        self,
        settings: Settings,
        provider: VideoProvider,
        processor: MediaProcessor,
        deliveries: DeliveryStore,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.processor = processor
        self.deliveries = deliveries
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_downloads, thread_name_prefix="medialab-download"
        )

    # --------------------------------------------------------------- public
    @staticmethod
    def _identity(plan: DownloadPlan) -> tuple:
        return (plan.url.canonical_url, plan.video_index, tuple(plan.option.format_ids))

    def submit(self, plan: DownloadPlan) -> JobSnapshot:
        with self._lock:
            # The same video in the same quality is never downloaded twice at once (double clicks,
            # a second browser tab, a bulk item that is also running as a single download).
            same = next((j for j in self._jobs.values()
                         if j.state in ACTIVE_STATES and self._identity(j.plan) == self._identity(plan)), None)
            if same is not None:
                raise AppError(ErrorCode.ALREADY_DOWNLOADING, "This video is already downloading in that quality.",
                               details={"job_id": same.job_id})
            active = sum(1 for j in self._jobs.values() if j.state in ACTIVE_STATES)
            if active >= self.settings.max_queued_jobs:
                raise AppError(
                    ErrorCode.TOO_MANY_JOBS,
                    f"Too many downloads in progress ({active}). Wait for some to finish and try again.",
                )
            job = Job(job_id=new_id(), plan=plan)
            self._jobs[job.job_id] = job
            snapshot = self._snapshot(job)
        self._executor.submit(self._run, job.job_id)
        return snapshot

    def get(self, job_id: str) -> JobSnapshot:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise AppError(ErrorCode.JOB_NOT_FOUND, "Download job not found. It may have expired.")
            return self._snapshot(job)

    def cancel(self, job_id: str, reason: AppError) -> bool:
        """Cancel a queued, downloading or processing job now. Idempotent; returns True if it changed.

        The job is ``cancelled`` immediately. Its worker stops at the next download progress
        update, a running FFmpeg/FFprobe is killed, and the temporary folder is removed.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state not in ACTIVE_STATES:
                return False
            job.abort_reason = job.abort_reason or reason
            job.cancel_event.set()
            job.transition(JobState.CANCELLED)
            job.error = reason
            job.stage = "Cancelled"
            job.speed_bytes_per_second = job.eta_seconds = None
        log.info("Job %s cancelled: %s", job_id, reason.message)
        return True

    def active_dir_names(self) -> set[str]:
        with self._lock:
            return {self._job_dir_name(j.job_id) for j in self._jobs.values()
                    if j.state in ACTIVE_STATES or j.worker_running}

    def prune(self, now: float | None = None) -> int:
        now = now or time.time()
        with self._lock:
            expired = [
                k
                for k, j in self._jobs.items()
                if j.state in TERMINAL_STATES and not j.worker_running and now - j.updated_at > self.settings.job_ttl_seconds
            ]
            for key in expired:
                del self._jobs[key]
        return len(expired)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _job_dir_name(job_id: str) -> str:
        return f"{JOB_DIR_PREFIX}{job_id}"

    def _snapshot(self, job: Job) -> JobSnapshot:
        total, estimate = job.total_bytes
        return JobSnapshot(
            job_id=job.job_id,
            state=job.state,
            option=job.plan.option,
            video_index=job.plan.video_index,
            created_at=job.created_at,
            updated_at=job.updated_at,
            stage=job.stage,
            downloaded_bytes=job.downloaded_bytes,
            total_bytes=total,
            total_is_estimate=estimate,
            percent=job.percent,
            speed_bytes_per_second=job.speed_bytes_per_second,
            eta_seconds=job.eta_seconds,
            result=job.result,
            error_code=job.error.code.value if job.error else None,
            error_message=job.error.message if job.error else None,
            error=job.error,
        )

    def _update(self, job_id: str, **changes) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            if job.state == JobState.CANCELLED:
                raise _Stopped()
            state = changes.pop("state", None)
            if state is not None:
                job.transition(state)
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = time.time()
            return job

    def _on_progress(self, job_id: str, update: ProgressUpdate) -> None:
        """Record progress and enforce the size and time limits.

        Raising here aborts the download inside the provider.
        """
        with self._lock:
            job = self._jobs[job_id]
            if job.abort_reason is not None or job.cancel_event.is_set():
                raise job.abort_reason or AppError(ErrorCode.DOWNLOAD_CANCELLED, "The download was cancelled.")
            if update.status == "retrying":
                # A provider is retrying (fresh links / interrupted transfer): restart the byte count.
                job.streams.clear()
                job.stage = update.note or "Retrying…"
                job.speed_bytes_per_second = job.eta_seconds = None
                job.updated_at = time.time()
                return
            option = job.plan.option
            known = set(option.format_ids) | ({option.fallback_audio_format_id} if option.fallback_audio_format_id else set())
            fid = update.format_id if update.format_id in known else option.video_format_id
            previous = job.streams.get(fid, StreamProgress())
            total = update.total_bytes
            if update.status == "finished":
                total, estimate = update.downloaded_bytes or total, False
            else:
                estimate = update.total_is_estimate
            job.streams[fid] = replace(
                previous,
                downloaded_bytes=max(update.downloaded_bytes, 0),
                total_bytes=total,
                total_is_estimate=estimate,
            )
            job.speed_bytes_per_second = update.speed_bytes_per_second
            job.eta_seconds = update.eta_seconds
            is_audio = fid in (option.audio_format_id, option.fallback_audio_format_id)
            job.stage = "Downloading audio stream" if is_audio else (
                "Downloading video stream" if option.requires_merge else "Downloading video"
            )
            job.updated_at = time.time()

            limit = job.plan.max_file_size_bytes
            projected, projected_is_estimate = job.total_bytes
            if job.downloaded_bytes > limit or (
                projected is not None and not projected_is_estimate and projected > limit
            ):
                job.abort_reason = AppError(
                    ErrorCode.FILE_TOO_LARGE,
                    f"The video exceeds the {limit // (1024 * 1024)} MB size limit (change it in Settings).",
                )
                raise job.abort_reason
            if job.started_at and time.time() - job.started_at > self.settings.download_timeout_seconds:
                job.abort_reason = AppError(ErrorCode.TIMEOUT, "The download took too long and was stopped.")
                raise job.abort_reason

    # ------------------------------------------------------------------ run
    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state != JobState.QUEUED:  # cancelled while queued: nothing to do
                return
            job.worker_running = True
            cancel_event = job.cancel_event
        scope = getattr(self.processor, "cancellable", None)
        try:
            with scope(cancel_event) if scope else contextlib.nullcontext():
                self._work(job_id)
        finally:
            with self._lock:
                self._jobs[job_id].worker_running = False

    def _work(self, job_id: str) -> None:
        job_dir = self.settings.temp_dir / self._job_dir_name(job_id)
        try:
            with self._lock:
                label = self._jobs[job_id].plan.platform_label
            job = self._update(job_id, state=JobState.DOWNLOADING, started_at=time.time(), stage=f"Connecting to {label}")
            plan = job.plan
            job_dir.mkdir(mode=0o700, parents=True, exist_ok=False)

            outputs = self.provider.provider_for(plan.provider, plan.url.platform).download(
                plan.url,
                plan.video_index,
                plan.option.format_ids,
                job_dir,
                lambda update: self._on_progress(job_id, update),
            )

            if plan.option.audio_converted:
                stage = "Converting audio to AAC and finalising MP4 (video not re-encoded)"
            elif plan.option.requires_merge:
                stage = "Combining video and audio (lossless)"
            else:
                stage = "Finalising MP4"
            self._update(job_id, state=JobState.PROCESSING, stage=stage, speed_bytes_per_second=None, eta_seconds=None)
            video_path = outputs[plan.option.video_format_id]
            audio_path = outputs.get(plan.option.audio_format_id) if plan.option.audio_format_id else None
            fallback = plan.option.fallback_audio_format_id
            if audio_path is None and fallback and not self.processor.probe(video_path).has_audio:
                # The source said this video carries audio, but the file has none: use its separate audio.
                log.info("Job %s: %s has no audio track despite its metadata; adding %s", job_id,
                         plan.option.video_format_id, fallback)
                self._update(job_id, stage="The video has no audio track; downloading the separate audio")
                extra = self.provider.provider_for(plan.provider, plan.url.platform).download(
                    plan.url, plan.video_index, [fallback], job_dir / "audio",
                    lambda update: self._on_progress(job_id, update),
                )
                audio_path = extra[fallback]
                self._update(job_id, stage="Converting audio and finalising MP4")
            output = job_dir / "output.mp4"
            # Audio is required when the source promised it (explicit codec) or a separate track exists.
            expect_audio = bool(fallback) or plan.option.has_audio is True
            probe = self.processor.assemble_mp4(video_path, audio_path, output, expect_audio=expect_audio)

            size = output.stat().st_size
            if size > plan.max_file_size_bytes:
                raise AppError(
                    ErrorCode.FILE_TOO_LARGE,
                    f"The video exceeds the {plan.max_file_size_bytes // (1024 * 1024)} MB size limit.",
                )

            # The source streams are no longer needed. Remove them now (outside the lock) so the
            # job folder is gone before "completed" becomes visible, not just after.
            for entry in job_dir.iterdir():
                if entry != output:
                    remove_tree_within(self.settings.temp_dir, entry)

            # Hand the verified MP4 to the temporary delivery area; the browser saves it. Done under
            # the lock after a state check, so a cancellation can't race with completion.
            with self._lock:
                job = self._jobs[job_id]
                if job.state != JobState.PROCESSING:
                    raise _Stopped()
                delivery = self.deliveries.add(output, plan.filename)
                remove_tree_within(self.settings.temp_dir, job_dir)  # empty now that the MP4 has moved
                job.result = CompletedFile(delivery.file_id, delivery.filename, delivery.size_bytes, probe)
                job.transition(JobState.COMPLETED)
                job.stage = "Ready to save"
            log.info("Job %s completed: %s (%d bytes) ready for delivery", job_id, delivery.filename, delivery.size_bytes)
        except _Stopped:
            log.info("Job %s stopped after cancellation", job_id)
        except AppError as exc:
            self._fail(job_id, exc)
        except Exception:  # noqa: BLE001 - last-resort guard so jobs never hang
            log.exception("Job %s crashed", job_id)
            self._fail(job_id, AppError(ErrorCode.DOWNLOAD_FAILED, "The download failed unexpectedly."))
        finally:
            if job_dir.exists():
                remove_tree_within(self.settings.temp_dir, job_dir)

    def _fail(self, job_id: str, error: AppError) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state in TERMINAL_STATES:
                return
            job.transition(JobState.FAILED)
            job.error = job.abort_reason or error
            job.stage = "Failed"
            job.speed_bytes_per_second = None
            job.eta_seconds = None
            final = job.error
        log.info("Job %s failed: %s %s", job_id, final.code.value, final.message)
