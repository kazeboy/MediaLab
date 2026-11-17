"""Download job state machine, progress, errors and cleanup."""

import threading
import time

import pytest

from app.errors import AppError, ErrorCode
from app.jobs import ALLOWED_TRANSITIONS, DownloadPlan, InvalidTransition, Job, JobManager, JobState
from app.models import ResolutionOption
from app.storage import DeliveryState, DeliveryStore
from app.validation import validate_post_url

from .conftest import FakeProcessor, FakeProvider

URL = validate_post_url("https://x.com/a/status/1")


def _plan(audio: bool = False, sizes=None, limit_mb: int = 8192, url=None) -> DownloadPlan:
    option = ResolutionOption(
        option_id="720p", label="720p", width=1280, height=720, video_format_id="v",
        audio_format_id="a" if audio else None, requires_merge=audio,
    )
    return DownloadPlan(url or URL, 1, option, "out.mp4", sizes or {}, max_file_size_bytes=limit_mb * 1024 * 1024)


def _url(n: int):
    return validate_post_url(f"https://x.com/a/status/{n}")


def _manager(settings, provider=None, processor=None) -> JobManager:
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    manager = JobManager(settings, provider or FakeProvider(), processor or FakeProcessor(),
                         DeliveryStore(settings.temp_dir, 1800))
    return manager


def _wait(manager: JobManager, job_id: str, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = manager.get(job_id)
        if snap.state in (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED):
            return snap
        time.sleep(0.01)
    raise AssertionError("timeout")


def _record_states(manager: JobManager, job_id: str) -> list[JobState]:
    states: list[JobState] = []
    deadline = time.time() + 5
    while time.time() < deadline:
        state = manager.get(job_id).state
        if not states or states[-1] != state:
            states.append(state)
        if state in (JobState.COMPLETED, JobState.FAILED):
            return states
        time.sleep(0.001)
    raise AssertionError("timeout")


def test_transition_table():
    job = Job(job_id="x", plan=_plan())
    assert job.state == JobState.QUEUED
    with pytest.raises(InvalidTransition):
        job.transition(JobState.COMPLETED)
    job.transition(JobState.DOWNLOADING)
    job.transition(JobState.PROCESSING)
    job.transition(JobState.COMPLETED)
    for state in JobState:
        with pytest.raises(InvalidTransition):
            job.transition(state)
    assert ALLOWED_TRANSITIONS[JobState.FAILED] == frozenset()


def test_successful_job_moves_through_all_states(settings):
    provider = FakeProvider()
    provider.gate = threading.Event()
    manager = _manager(settings, provider)
    snap = manager.submit(_plan(audio=True))
    assert snap.state == JobState.QUEUED
    threading.Timer(0.05, provider.gate.set).start()
    states = _record_states(manager, snap.job_id)
    assert states[0] in (JobState.QUEUED, JobState.DOWNLOADING)
    assert states[-1] == JobState.COMPLETED
    assert JobState.DOWNLOADING in states
    order = [JobState.QUEUED, JobState.DOWNLOADING, JobState.PROCESSING, JobState.COMPLETED]
    assert [s for s in order if s in states] == states  # monotonic

    final = manager.get(snap.job_id)
    assert final.percent == 100.0
    assert final.downloaded_bytes == 2000  # video 1000 + audio 1000
    assert final.total_bytes == 2000 and final.total_is_estimate is False
    assert final.result.filename == "out.mp4" and final.result.size_bytes == 2000
    delivery = manager.deliveries.status(final.result.file_id)
    assert delivery.state == DeliveryState.READY and delivery.path.is_file() and delivery.filename == "out.mp4"
    assert delivery.path.parent == settings.temp_dir / "ready"  # temporary area, not a user folder
    assert provider.calls[0][2] == ["v", "a"]


def test_temp_dir_removed_after_success_and_failure(settings):
    manager = _manager(settings)
    _wait(manager, manager.submit(_plan()).job_id)
    provider = FakeProvider()
    provider.download_error = AppError(ErrorCode.DOWNLOAD_FAILED, "boom")
    manager2 = _manager(settings, provider)
    _wait(manager2, manager2.submit(_plan()).job_id)
    leftovers = [p.name for p in settings.temp_dir.iterdir() if p.name.startswith("job-")]
    assert leftovers == []  # job directories (incl. partial files) always removed


def test_job_dir_removed_before_completed_is_visible(settings, monkeypatch):
    """Regression: "completed" used to be published before the job folder was deleted, so a
    status poll could see a finished job with its temporary files still on disk."""
    seen: list[bool] = []
    original = Job.transition

    def recording_transition(self, new_state):
        if new_state == JobState.COMPLETED:
            seen.append((settings.temp_dir / f"job-{self.job_id}").exists())
        original(self, new_state)

    monkeypatch.setattr(Job, "transition", recording_transition)
    manager = _manager(settings)
    snap = _wait(manager, manager.submit(_plan(audio=True)).job_id)
    assert snap.state == JobState.COMPLETED
    assert seen == [False]  # folder already gone at the moment the job became "completed"
    assert manager.deliveries.status(snap.result.file_id).path.is_file()  # the MP4 itself was kept


def test_download_error_marks_job_failed(settings):
    provider = FakeProvider()
    provider.download_error = AppError(ErrorCode.FORMAT_UNAVAILABLE, "gone")
    manager = _manager(settings, provider)
    snap = _wait(manager, manager.submit(_plan()).job_id)
    assert snap.state == JobState.FAILED
    assert snap.error_code == "format_unavailable" and snap.error_message == "gone"
    assert snap.percent is None and snap.result is None


def test_processing_error_marks_job_failed(settings):
    processor = FakeProcessor()
    processor.error = AppError(ErrorCode.INCOMPATIBLE_FORMAT, "needs re-encode")
    manager = _manager(settings, processor=processor)
    snap = _wait(manager, manager.submit(_plan()).job_id)
    assert snap.state == JobState.FAILED and snap.error_code == "incompatible_format"
    assert not (settings.temp_dir / "ready").exists() or list((settings.temp_dir / "ready").iterdir()) == []


def test_unexpected_exception_is_contained(settings):
    class Broken(FakeProvider):
        def download(self, *a, **k):
            raise RuntimeError("secret /Users/me/path")

    manager = _manager(settings, Broken())
    snap = _wait(manager, manager.submit(_plan()).job_id)
    assert snap.state == JobState.FAILED and snap.error_code == "download_failed"
    assert "/Users" not in snap.error_message


def test_size_limit_aborts_download(settings):
    from dataclasses import replace

    provider = FakeProvider()
    provider.chunk_sizes = [600_000, 600_000]
    manager = _manager(settings, provider)
    snap = _wait(manager, manager.submit(_plan(limit_mb=1)).job_id)
    assert snap.state == JobState.FAILED and snap.error_code == "file_too_large"


def test_size_limit_reason_survives_wrapped_exception(settings):
    """Even if the downloader swallows our abort and raises something else."""
    from dataclasses import replace

    class Wrapping(FakeProvider):
        def download(self, url, video_index, format_ids, dest_dir, on_progress):
            try:
                return super().download(url, video_index, format_ids, dest_dir, on_progress)
            except AppError:
                raise AppError(ErrorCode.DOWNLOAD_FAILED, "wrapped")

    provider = Wrapping()
    provider.chunk_sizes = [2_000_000]
    manager = _manager(settings, provider)
    snap = _wait(manager, manager.submit(_plan(limit_mb=1)).job_id)
    assert snap.error_code == "file_too_large"


def test_queue_limit(settings):
    provider = FakeProvider()
    provider.gate = threading.Event()
    manager = _manager(settings, provider)
    ids = [manager.submit(_plan(url=_url(n))).job_id for n in range(1, settings.max_queued_jobs + 1)]
    with pytest.raises(AppError) as exc:
        manager.submit(_plan(url=_url(99)))
    assert exc.value.code == ErrorCode.TOO_MANY_JOBS
    provider.gate.set()
    for job_id in ids:
        assert _wait(manager, job_id).state == JobState.COMPLETED


def test_progress_uses_analysis_estimate_until_real_size_known(settings):
    manager = _manager(settings)
    job = Job(job_id="j", plan=_plan(audio=True, sizes={"v": 5000, "a": 1000}))
    assert job.total_bytes == (6000, True)
    job.plan = _plan(audio=True, sizes={"v": None})
    assert job.total_bytes == (None, True)
    manager.shutdown()


def test_unknown_job(settings):
    manager = _manager(settings)
    with pytest.raises(AppError) as exc:
        manager.get("0" * 32)
    assert exc.value.code == ErrorCode.JOB_NOT_FOUND


def test_prune_removes_only_finished_expired_jobs(settings):
    manager = _manager(settings)
    job_id = manager.submit(_plan()).job_id
    _wait(manager, job_id)
    assert manager.prune(now=time.time()) == 0
    assert manager.prune(now=time.time() + settings.job_ttl_seconds + 1) == 1
