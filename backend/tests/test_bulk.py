"""v1.9 bulk downloads for X and TikTok: analysis, queue, output, cancellation (all mocked).

Downloads are held with per-post gates so tests can observe the queue while it runs:
concurrency, ordering, cancelling waiting and running items, cancelling the whole batch,
and races between cancellation and completion.
"""

from __future__ import annotations

import dataclasses
import io
import threading
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.errors import AppError, ErrorCode
from app.jobs import JobManager, JobState
from app.main import create_app
from app.media import MediaProcessor
from app.models import ResolutionOption
from app.providers.base import ProgressUpdate
from app.providers.router import PlatformRouter
from app.selection import choose_option
from app.storage import DeliveryStore
from app.validation import PLATFORM_SHORTDRAMA

from .conftest import FakeProcessor, FakeProvider


def x_url(n: int, host: str = "x.com", user: str = "alice") -> str:
    return f"https://{host}/{user}/status/{1790637656616940000 + n}"


def tt_url(n: int) -> str:
    return f"https://www.tiktok.com/@someone/video/{7047596209028070000 + n}"


class BulkProvider(FakeProvider):
    """Per-post gates and failures; records extraction calls and download concurrency."""

    def __init__(self) -> None:
        super().__init__()
        self.extract_calls: list[str] = []
        self.fail_extract: set[str] = set()
        self.fail_download: set[str] = set()
        self.gates: dict[str, threading.Event] = {}
        self.extract_gate: threading.Event | None = None
        self.active = 0
        self.max_active = 0
        self.started: list[str] = []
        self._lock = threading.Lock()

    def extract(self, url):
        self.extract_calls.append(url.post_id)
        if self.extract_gate is not None:
            self.extract_gate.wait(5)
        if url.post_id in self.fail_extract:
            raise AppError(ErrorCode.NOT_FOUND, "This post doesn't exist.")
        return super().extract(url)

    def download(self, url, video_index, format_ids, dest_dir, on_progress):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.started.append(url.post_id)
        try:
            gate = self.gates.get(url.post_id)
            if gate is not None:
                while not gate.wait(0.02):  # keep reporting progress so cancellation is noticed
                    on_progress(ProgressUpdate(format_ids[0], "downloading", 1, 1000, False))
            if url.post_id in self.fail_download:
                raise AppError(ErrorCode.DOWNLOAD_INTERRUPTED, "The connection dropped.", retryable=True)
            return super().download(url, video_index, format_ids, dest_dir, on_progress)
        finally:
            with self._lock:
                self.active -= 1


@pytest.fixture
def bulk_settings(settings):
    return dataclasses.replace(settings, max_concurrent_downloads=2, max_queued_jobs=10)


@pytest.fixture
def prov() -> BulkProvider:
    return BulkProvider()


def make_client(settings, prov):
    router = PlatformRouter({"x": prov, "tiktok": prov, PLATFORM_SHORTDRAMA: FakeProvider()})
    return TestClient(create_app(settings, provider=router, processor=FakeProcessor()), base_url="http://127.0.0.1")


@pytest.fixture
def api(bulk_settings, prov):
    with make_client(bulk_settings, prov) as c:
        yield c


def wait(fn, timeout: float = 5.0, every: float = 0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(every)
    raise AssertionError("condition not reached in time")


def analysed(api, urls: list[str], platform: str = "x") -> dict:
    res = api.post("/api/bulk-analyses", json={"platform": platform, "urls": urls})
    assert res.status_code == 202, res.text
    bulk_id = res.json()["bulk_id"]
    return wait(lambda: (b := api.get(f"/api/bulk-analyses/{bulk_id}").json())["state"] != "running" and b)


def ready_ids(bulk: dict) -> list[str]:
    return [i["analysis_id"] for i in bulk["items"] if i["state"] == "ready"]


def start_batch(api, ids, **kw) -> dict:
    body = {"platform": "x", "analysis_ids": ids, "output": "zip", "concurrency": 2, **kw}
    res = api.post("/api/batches", json=body)
    assert res.status_code == 202, res.text
    return res.json()


def batch(api, batch_id: str) -> dict:
    return api.get(f"/api/batches/{batch_id}").json()


def item(b: dict, n: int) -> dict:
    return b["episodes"][n - 1]


def wait_batch(api, batch_id, predicate, timeout=6.0) -> dict:
    def check():
        b = batch(api, batch_id)
        return b if predicate(b) else None
    return wait(check, timeout)


def fetch_zip(api, b: dict) -> zipfile.ZipFile:
    res = api.get(b["result"]["download_url"])
    assert res.status_code == 200
    return zipfile.ZipFile(io.BytesIO(res.content))


# ------------------------------------------------------------- input / analysis
def test_bulk_analysis_classifies_every_line(api, prov):
    lines = [x_url(1), "", "   ", f"  {x_url(2)}  ", x_url(1, host="twitter.com", user="bob"), "not a link",
             tt_url(1), x_url(3)]
    prov.fail_extract.add(str(1790637656616940003))
    res = api.post("/api/bulk-analyses", json={"platform": "x", "urls": lines})
    assert res.status_code == 202
    first = res.json()
    states = [i["state"] for i in first["items"]]
    # Blank lines are dropped; the duplicate and the invalid lines are known before any network work.
    assert len(first["items"]) == 6
    assert states[2] == "duplicate" and first["items"][2]["duplicate_of"] == 1
    assert states[3] == "invalid" and first["items"][3]["error"]["code"] == "invalid_url"
    wrong = first["items"][4]
    assert wrong["state"] == "invalid" and wrong["error"]["code"] == "wrong_platform"
    assert wrong["error"]["details"]["detected_platform"] == "tiktok" and "TikTok" in wrong["error"]["action"]

    done = analysed(api, lines)
    c = done["counts"]
    assert (c["ready"], c["failed"], c["duplicate"], c["invalid"]) == (2, 1, 1, 2)
    failed = next(i for i in done["items"] if i["state"] == "failed")
    assert failed["error"]["code"] == "not_found"  # one failure doesn't stop the others
    ok = next(i for i in done["items"] if i["state"] == "ready")
    assert ok["title"] and ok["author"] and ok["duration_seconds"] and ok["qualities"]
    assert set(ok["estimates"]) == {"best", "1080p", "720p", "480p"}
    assert ok["estimates"]["480p"]["label"] == "360p" and "isn't available" in ok["estimates"]["480p"]["note"]


def test_each_distinct_link_is_extracted_once(api, prov):
    analysed(api, [x_url(1), x_url(1, host="twitter.com"), x_url(2)])
    assert sorted(prov.extract_calls) == [str(1790637656616940001), str(1790637656616940002)]


@pytest.mark.parametrize("body, code", [
    ({"platform": "x", "urls": ["", "  "]}, "validation_error"),
    ({"platform": "x", "urls": ["nope", "also nope"]}, "invalid_url"),
    ({"platform": "x", "urls": [x_url(n) for n in range(1, 52)]}, "validation_error"),
])
def test_bulk_analysis_rejects_empty_invalid_and_oversized_input(api, body, code):
    res = api.post("/api/bulk-analyses", json=body)
    assert res.status_code in (400, 422) and res.json()["error"]["code"] == code, res.text


def test_bulk_limit_counts_distinct_links_only(api):
    lines = [x_url(n) for n in range(1, 51)] + [x_url(1)] * 20  # 50 distinct + duplicates
    assert api.post("/api/bulk-analyses", json={"platform": "x", "urls": lines}).status_code == 202


def test_bulk_analysis_request_validation_and_origin(api):
    for bad in ({"platform": "tiktok_shortdrama", "urls": [x_url(1)]}, {"platform": "x", "urls": []},
                {"platform": "x", "urls": [x_url(1)], "extra": 1}):
        assert api.post("/api/bulk-analyses", json=bad).status_code == 422
    res = api.post("/api/bulk-analyses", json={"platform": "x", "urls": [x_url(1)]},
                   headers={"Origin": "https://evil.example"})
    assert res.status_code == 403
    assert api.get("/api/bulk-analyses/" + "0" * 32).json()["error"]["code"] == "bulk_not_found"


def test_cancel_during_analysis_discards_late_results(api, prov):
    prov.extract_gate = threading.Event()
    bulk_id = api.post("/api/bulk-analyses", json={"platform": "x", "urls": [x_url(n) for n in (1, 2, 3)]}).json()["bulk_id"]
    res = api.post(f"/api/bulk-analyses/{bulk_id}/cancel").json()
    assert res["state"] == "cancelled" and res["counts"]["cancelled"] == 3
    prov.extract_gate.set()
    time.sleep(0.3)
    after = api.get(f"/api/bulk-analyses/{bulk_id}").json()
    assert after["counts"]["cancelled"] == 3 and after["counts"]["ready"] == 0


def test_tiktok_bulk_rejects_x_links(api):
    done = analysed(api, [tt_url(1), tt_url(2), x_url(1)], platform="tiktok")
    assert done["counts"]["ready"] == 2
    bad = done["items"][2]
    assert bad["error"]["code"] == "wrong_platform" and bad["error"]["details"]["detected_platform"] == "x"


# ----------------------------------------------------------------- queue / output
def test_zip_keeps_input_order_and_safe_unique_names(api, prov, bulk_settings):
    done = analysed(api, [x_url(3), x_url(1), x_url(2)])
    b = start_batch(api, ready_ids(done))
    assert b["source"] == "urls" and b["platform"] == "x" and b["output"] == "zip"
    b = wait_batch(api, b["batch_id"], lambda b: b["state"] == "ready")
    assert b["result"]["kind"] == "zip" and b["result"]["filename"].startswith("MediaLab X videos ")
    assert b["result"]["filename"].endswith(" - 3 videos.zip") and b["percent"] < 100
    with fetch_zip(api, b) as zf:
        assert zf.testzip() is None
        names = zf.namelist()
    assert [n[:5] for n in names] == ["01 - ", "02 - ", "03 - "]
    assert [n.split("[")[1][:19] for n in names] == [str(1790637656616940000 + k) for k in (3, 1, 2)]
    assert all(n.endswith(".mp4") and "/" not in n for n in names)
    b = wait_batch(api, b["batch_id"], lambda b: b["state"] == "completed")
    assert b["percent"] == 100.0
    wait(lambda: not any(p.name.startswith("job-") for p in bulk_settings.temp_dir.iterdir()))


def test_two_concurrent_downloads_in_order(api, prov):
    done = analysed(api, [x_url(n) for n in (1, 2, 3, 4)])
    for n in (1, 2, 3, 4):
        prov.gates[str(1790637656616940000 + n)] = threading.Event()
    b = start_batch(api, ready_ids(done), concurrency=2)
    b = wait_batch(api, b["batch_id"], lambda b: b["counts"]["downloading"] == 2)
    assert [item(b, n)["state"] for n in (1, 2, 3, 4)] == ["downloading", "downloading", "pending", "pending"]
    assert prov.started == [str(1790637656616940001), str(1790637656616940002)]
    for gate in prov.gates.values():
        gate.set()
    wait_batch(api, b["batch_id"], lambda b: b["state"] == "ready")
    assert prov.max_active == 2


def test_concurrency_is_capped_by_the_server(settings, prov):
    with make_client(dataclasses.replace(settings, max_concurrent_downloads=1, max_queued_jobs=10), prov) as api:
        done = analysed(api, [x_url(1), x_url(2)])
        b = start_batch(api, ready_ids(done), concurrency=4)
        assert b["concurrency"] == 1
        wait_batch(api, b["batch_id"], lambda b: b["state"] == "ready")
    assert prov.max_active == 1


def test_separate_files_are_delivered_one_by_one(api, prov, bulk_settings):
    done = analysed(api, [x_url(1), x_url(2)])
    b = start_batch(api, ready_ids(done), output="files")
    b = wait_batch(api, b["batch_id"], lambda b: b["counts"]["ready"] == 2)
    for e in b["episodes"]:
        assert e["filename"].endswith(".mp4") and "[1790637656616940" in e["filename"]
        assert api.get(e["download_url"]).status_code == 200
    b = wait_batch(api, b["batch_id"], lambda b: b["state"] == "completed")
    assert b["counts"]["saved"] == 2
    assert list((bulk_settings.temp_dir / "ready").iterdir()) == []


def test_unsaved_separate_file_expires_and_can_be_retried(api, prov):
    done = analysed(api, [x_url(1)])
    b = start_batch(api, ready_ids(done), output="files")
    b = wait_batch(api, b["batch_id"], lambda b: b["counts"]["ready"] == 1)
    services = api.app.state.services
    services.deliveries.prune(now=time.time() + 10 * 3600)
    b = wait_batch(api, b["batch_id"], lambda b: b["counts"]["failed"] == 1)
    assert item(b, 1)["error"]["code"] == "file_not_found" and item(b, 1)["stage"] == "Not saved in time"
    api.post(f"/api/batches/{b['batch_id']}/items/1/retry")
    wait_batch(api, b["batch_id"], lambda b: b["counts"]["ready"] == 1)


def test_partial_failure_is_explicit_before_packaging(api, prov):
    done = analysed(api, [x_url(1), x_url(2), x_url(3)])
    prov.fail_download.add(str(1790637656616940002))
    b = start_batch(api, ready_ids(done))
    b = wait_batch(api, b["batch_id"], lambda b: b["state"] == "needs_decision")
    assert b["error"]["details"]["failed"] == [2] and "Video(s) 2" in b["error"]["message"]
    assert item(b, 2)["error"]["code"] == "download_interrupted"
    assert [item(b, n)["state"] for n in (1, 3)] == ["downloaded", "downloaded"]  # completed work is kept
    b = api.post(f"/api/batches/{b['batch_id']}/continue").json()
    b = wait_batch(api, b["batch_id"], lambda b: b["state"] == "ready")
    assert "(partial, 2 of 3)" in b["result"]["filename"] and b["result"]["omitted"] == [2]
    with fetch_zip(api, b) as zf:
        names = zf.namelist()
        manifest = zf.read("MediaLab manifest.txt").decode()
    assert [n[:2] for n in names if n.endswith(".mp4")] == ["01", "03"]
    assert "Not included" in manifest and "connection dropped" in manifest
    assert "http" not in manifest  # no links or signed URLs in the archive


def test_retry_a_failed_item_completes_the_batch(api, prov):
    done = analysed(api, [x_url(1), x_url(2)])
    prov.fail_download.add(str(1790637656616940002))
    b = start_batch(api, ready_ids(done))
    b = wait_batch(api, b["batch_id"], lambda b: b["state"] == "needs_decision")
    prov.fail_download.clear()
    b = api.post(f"/api/batches/{b['batch_id']}/items/2/retry").json()
    assert item(b, 2)["state"] == "pending"
    b = wait_batch(api, b["batch_id"], lambda b: b["state"] == "ready")
    assert b["result"]["omitted"] == []
    with fetch_zip(api, b) as zf:
        assert len(zf.namelist()) == 2


def test_nothing_downloaded_gives_no_archive(api, prov):
    done = analysed(api, [x_url(1), x_url(2)])
    prov.fail_download |= {str(1790637656616940001), str(1790637656616940002)}
    b = start_batch(api, ready_ids(done))
    b = wait_batch(api, b["batch_id"], lambda b: b["state"] == "partial")
    assert b["result"] is None and "no ZIP was created" in b["error"]["message"]


def test_batch_output_limit_is_enforced_server_side(api, prov, monkeypatch):
    store = api.app.state.services.settings_store
    small = store.get().model_copy(update={"batch_output_max_mb": 0})
    monkeypatch.setattr(store, "get", lambda: small)
    done = analysed(api, [x_url(1), x_url(2)])
    b = start_batch(api, ready_ids(done))
    b = wait_batch(api, b["batch_id"], lambda b: b["state"] == "failed")
    assert b["error"]["code"] == "batch_output_too_large"


def test_url_batch_request_validation(api, prov):
    done = analysed(api, [x_url(1), x_url(2)])
    ids = ready_ids(done)
    tt = ready_ids(analysed(api, [tt_url(1)], platform="tiktok"))
    cases = [
        ({"platform": "x", "analysis_ids": ids, "output": "merge"}, 422, "validation_error"),
        ({"platform": "x", "analysis_ids": ["f" * 32]}, 410, "analysis_expired"),
        ({"platform": "x", "analysis_ids": [ids[0], ids[0]]}, 422, "validation_error"),
        ({"platform": "x", "analysis_ids": tt}, 400, "wrong_platform"),
        ({"platform": "x", "analysis_ids": ["../etc"]}, 422, "validation_error"),
        ({"platform": "x", "analysis_ids": ids, "concurrency": 9}, 422, "validation_error"),
    ]
    for body, status, code in cases:
        res = api.post("/api/batches", json=body)
        assert res.status_code == status and res.json()["error"]["code"] == code, (body, res.text)


def test_identical_batches_and_jobs_are_not_started_twice(api, prov):
    done = analysed(api, [x_url(1), x_url(2)])
    prov.gates[str(1790637656616940001)] = threading.Event()
    first = start_batch(api, ready_ids(done))
    again = api.post("/api/batches", json={"platform": "x", "analysis_ids": ready_ids(done), "output": "zip"})
    assert again.status_code == 409 and again.json()["error"]["details"]["batch_id"] == first["batch_id"]
    # A single download of the video the batch is downloading right now is refused too.
    wait_batch(api, first["batch_id"], lambda b: item(b, 1)["state"] == "downloading")
    single = api.post("/api/download", json={"analysis_id": ready_ids(done)[0], "option_id": "best"})
    assert single.status_code == 409 and single.json()["error"]["code"] == "already_downloading"
    prov.gates[str(1790637656616940001)].set()


def test_double_click_on_download_returns_the_running_job(api, prov):
    analysis = api.post("/api/analyse", json={"url": x_url(7), "platform": "x"}).json()
    prov.gates[str(1790637656616940007)] = threading.Event()
    body = {"analysis_id": analysis["analysis_id"], "option_id": "best"}
    first = api.post("/api/download", json=body).json()
    second = api.post("/api/download", json=body)
    assert second.status_code == 409 and second.json()["error"]["details"]["job_id"] == first["job_id"]
    prov.gates[str(1790637656616940007)].set()


# --------------------------------------------------------------------- cancellation
def test_cancel_a_waiting_item_and_a_running_item(api, prov):
    done = analysed(api, [x_url(1), x_url(2), x_url(3)])
    prov.gates[str(1790637656616940001)] = threading.Event()
    b = start_batch(api, ready_ids(done), concurrency=1)
    bid = b["batch_id"]
    wait_batch(api, bid, lambda b: item(b, 1)["state"] == "downloading")
    b = api.post(f"/api/batches/{bid}/items/2/cancel").json()
    assert item(b, 2)["state"] == "cancelled"  # removed from the queue at once
    b = api.post(f"/api/batches/{bid}/items/1/cancel").json()
    assert item(b, 1)["state"] == "cancelled"
    assert api.post(f"/api/batches/{bid}/items/1/cancel").status_code == 200  # idempotent
    b = wait_batch(api, bid, lambda b: item(b, 3)["state"] == "downloaded")  # the rest continues
    assert str(1790637656616940002) not in prov.started
    assert b["state"] == "needs_decision" and b["error"]["details"]["failed"] == [1, 2]
    res = api.post(f"/api/batches/{bid}/items/3/cancel")
    assert res.status_code == 422  # a finished item can't be cancelled


def test_cancel_batch_keeps_finished_videos_for_a_zip(api, prov, bulk_settings):
    done = analysed(api, [x_url(1), x_url(2), x_url(3)])
    prov.gates[str(1790637656616940002)] = threading.Event()
    b = start_batch(api, ready_ids(done), concurrency=1)
    bid = b["batch_id"]
    wait_batch(api, bid, lambda b: item(b, 1)["state"] == "downloaded" and item(b, 2)["state"] == "downloading")
    b = api.post(f"/api/batches/{bid}/cancel").json()
    assert b["state"] == "needs_decision" and b["stopped"] is True
    assert [item(b, n)["state"] for n in (1, 2, 3)] == ["downloaded", "cancelled", "cancelled"]
    assert "Build the ZIP" in b["error"]["action"]
    prov.gates[str(1790637656616940002)].set()
    time.sleep(0.3)
    assert item(batch(api, bid), 2)["state"] == "cancelled"  # a late finish can't revive it
    # Building from what finished: one video is delivered as a plain MP4.
    b = api.post(f"/api/batches/{bid}/continue").json()
    b = wait_batch(api, bid, lambda b: b["state"] == "ready")
    assert b["result"]["kind"] == "mp4" and b["result"]["included"] == [1]
    assert b["result"]["filename"].endswith(".mp4") and not b["result"]["filename"].startswith("01 - ")


def test_second_cancel_discards_kept_videos(api, prov, bulk_settings):
    done = analysed(api, [x_url(1), x_url(2)])
    prov.gates[str(1790637656616940002)] = threading.Event()
    b = start_batch(api, ready_ids(done), concurrency=1)
    bid = b["batch_id"]
    wait_batch(api, bid, lambda b: item(b, 1)["state"] == "downloaded")
    api.post(f"/api/batches/{bid}/cancel")
    b = api.post(f"/api/batches/{bid}/cancel").json()
    assert b["state"] == "cancelled"
    prov.gates[str(1790637656616940002)].set()
    batch_dir = bulk_settings.temp_dir / f"job-batch-{bid}"
    wait(lambda: not batch_dir.exists())


def test_cancel_batch_in_files_mode_keeps_ready_files(api, prov):
    done = analysed(api, [x_url(1), x_url(2)])
    prov.gates[str(1790637656616940002)] = threading.Event()
    b = start_batch(api, ready_ids(done), output="files", concurrency=1)
    bid = b["batch_id"]
    b = wait_batch(api, bid, lambda b: item(b, 1)["state"] == "ready" and item(b, 2)["state"] == "downloading")
    b = api.post(f"/api/batches/{bid}/cancel").json()
    assert b["stopped"] and item(b, 1)["state"] == "ready" and item(b, 1)["download_url"]
    assert item(b, 2)["state"] == "cancelled"
    prov.gates[str(1790637656616940002)].set()
    assert api.get(item(b, 1)["download_url"]).status_code == 200  # still saveable
    b = wait_batch(api, bid, lambda b: b["state"] == "partial")
    assert b["counts"]["saved"] == 1 and b["counts"]["cancelled"] == 1


def test_cancel_during_zip_packaging_keeps_the_videos(api, prov, monkeypatch, bulk_settings):
    from app import packaging

    real = packaging.build_zip
    entered = threading.Event()

    def stalled(items, out, *, manifest, cancel, progress, delete_sources=True):
        entered.set()
        while not cancel.wait(0.02):
            progress(10)
        raise packaging._cancelled()

    monkeypatch.setattr(packaging, "build_zip", stalled)
    done = analysed(api, [x_url(1), x_url(2)])
    b = start_batch(api, ready_ids(done))
    bid = b["batch_id"]
    wait(entered.is_set)
    b = api.post(f"/api/batches/{bid}/cancel").json()
    assert b["state"] == "needs_decision" and b["stopped"]
    time.sleep(0.2)
    collected = list((bulk_settings.temp_dir / f"job-batch-{bid}").glob("E*.mp4"))
    assert len(collected) == 2  # nothing was lost
    monkeypatch.setattr(packaging, "build_zip", real)
    api.post(f"/api/batches/{bid}/continue")
    b = wait_batch(api, bid, lambda b: b["state"] == "ready")
    with fetch_zip(api, b) as zf:
        assert zf.testzip() is None and len(zf.namelist()) == 2


# ------------------------------------------------------------ job-level cancellation
class BlockingProcessor(FakeProcessor):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def assemble_mp4(self, video_path, audio_path, output_path, expect_audio=False):
        self.entered.set()
        self.release.wait(5)
        return super().assemble_mp4(video_path, audio_path, output_path, expect_audio)


def _job_manager(settings, processor):
    from app.jobs import DownloadPlan
    from app.validation import validate_post_url

    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    deliveries = DeliveryStore(settings.temp_dir, 1800)
    manager = JobManager(settings, FakeProvider(), processor, deliveries)
    option = ResolutionOption(option_id="720p", label="720p", width=1280, height=720, video_format_id="v")
    plan = DownloadPlan(validate_post_url("https://x.com/a/status/5"), 1, option, "out.mp4")
    return manager, deliveries, plan


def test_cancel_during_processing_never_completes(settings):
    processor = BlockingProcessor()
    manager, deliveries, plan = _job_manager(settings, processor)
    job_id = manager.submit(plan).job_id
    assert processor.entered.wait(5)
    assert manager.get(job_id).state == JobState.PROCESSING
    assert manager.cancel(job_id, AppError(ErrorCode.DOWNLOAD_CANCELLED, "Cancelled.")) is True
    assert manager.cancel(job_id, AppError(ErrorCode.DOWNLOAD_CANCELLED, "Cancelled.")) is False  # double cancel
    processor.release.set()  # the delayed "completion" arrives after the cancellation
    wait(lambda: not manager.active_dir_names())
    snap = manager.get(job_id)
    assert snap.state == JobState.CANCELLED and snap.result is None and snap.error_code == "download_cancelled"
    assert not (deliveries.root.exists() and any(deliveries.root.iterdir()))
    assert not list(settings.temp_dir.glob("job-*"))


def test_cancel_queued_job_never_starts(settings):
    processor = BlockingProcessor()
    settings = dataclasses.replace(settings, max_concurrent_downloads=1)
    manager, _deliveries, plan = _job_manager(settings, processor)
    first = manager.submit(plan).job_id
    assert processor.entered.wait(5)
    from dataclasses import replace

    from app.validation import validate_post_url
    second = manager.submit(replace(plan, url=validate_post_url("https://x.com/a/status/6"))).job_id
    manager.cancel(second, AppError(ErrorCode.DOWNLOAD_CANCELLED, "Cancelled."))
    processor.release.set()
    wait(lambda: manager.get(first).state == JobState.COMPLETED)
    time.sleep(0.1)
    assert manager.get(second).state == JobState.CANCELLED
    assert len(processor.calls) == 1  # the cancelled job never reached FFmpeg


def test_cancellation_kills_a_running_subprocess():
    """A stalled FFmpeg/FFprobe is killed within the polling interval (here `sleep` stands in)."""
    processor = MediaProcessor(timeout_seconds=60)
    event = threading.Event()
    threading.Timer(0.3, event.set).start()
    started = time.monotonic()
    with processor.cancellable(event), pytest.raises(AppError) as exc:
        processor.run(["sleep", "30"], "Checking the audio")
    assert exc.value.code == ErrorCode.DOWNLOAD_CANCELLED
    assert time.monotonic() - started < 3


def test_already_cancelled_scope_never_starts_a_process():
    processor = MediaProcessor()
    event = threading.Event()
    event.set()
    with processor.cancellable(event), pytest.raises(AppError):
        processor.run(["sleep", "30"], "x")


# ---------------------------------------------------------------------- selection
def _opt(side: int, audio: bool = True) -> ResolutionOption:
    return ResolutionOption(option_id=f"{side}p", label=f"{side}p", width=side * 16 // 9, height=side,
                            video_format_id=f"v{side}", has_audio=audio)


def test_quality_fallback_never_upscales_and_prefers_audio():
    from app.selection import apply_size_limit

    opts = apply_size_limit([_opt(1080), _opt(720, audio=False), _opt(720), _opt(360)], None)
    assert choose_option(opts, "720p", above="closest")[0].height == 720
    pick, note = choose_option(opts, "480p", above="closest")
    assert pick.height == 360 and "next lower" in note  # lower first: never upscaled
    tall_only = apply_size_limit([_opt(1080), _opt(720)], None)
    pick, note = choose_option(tall_only, "480p", above="closest")
    assert pick.height == 720 and "closest" in note  # nothing lower: the closest real resolution
    assert choose_option(tall_only, "best", above="closest")[0].height == 1080


def test_unknown_batch_explains_restarts(api):
    body = api.get("/api/batches/" + "0" * 32).json()["error"]
    assert body["code"] == "batch_not_found" and "restarts" in body["action"]
