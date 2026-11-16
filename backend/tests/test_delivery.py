"""Temporary delivery storage: one browser download, then MediaLab deletes its copy."""

import asyncio
import os
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.delivery import CHUNK_BYTES, DeliveryResponse
from app.errors import AppError, ErrorCode
from app.main import create_app, run_cleanup
from app.storage import DeliveryState, DeliveryStore

from .conftest import FakeProcessor, FakeProvider, wait_for_job

URL = "https://x.com/medialab_test/status/1800000000000000001"


def _ready_file(store: DeliveryStore, tmp: Path, data: bytes = b"\0" * 5000, name="My video.mp4"):
    src = tmp / "output.mp4"
    src.write_bytes(data)
    return store.add(src, name)


@pytest.fixture
def store(tmp_path):
    s = DeliveryStore(tmp_path / "temp", retention_seconds=60)
    s.reset()
    return s


# ------------------------------------------------------------------ store
def test_add_moves_file_into_private_area_with_random_name(store, tmp_path):
    item = _ready_file(store, tmp_path)
    assert item.path.parent == store.root and item.path.name == f"{item.file_id}.mp4"
    assert item.filename == "My video.mp4"  # display name only used in Content-Disposition
    assert not (tmp_path / "output.mp4").exists()
    assert item.state == DeliveryState.READY


def test_full_transfer_deletes_copy(store, tmp_path):
    item = _ready_file(store, tmp_path)
    store.begin(item.file_id)
    store.finish(item.file_id, completed=True)
    assert not item.path.exists() and store.status(item.file_id).state == DeliveryState.DELIVERED
    with pytest.raises(AppError) as exc:
        store.begin(item.file_id)
    assert exc.value.code == ErrorCode.FILE_NOT_FOUND and "already saved" in exc.value.message


def test_interrupted_transfer_can_be_retried(store, tmp_path):
    item = _ready_file(store, tmp_path)
    store.begin(item.file_id)
    store.finish(item.file_id, completed=False)
    assert item.path.exists() and store.status(item.file_id).state == DeliveryState.READY
    assert store.begin(item.file_id).attempts == 2


def test_duplicate_requests_are_refused_while_streaming(store, tmp_path):
    item = _ready_file(store, tmp_path)
    results = []

    def attempt():
        try:
            store.begin(item.file_id)
            results.append("ok")
        except AppError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1 and results.count(ErrorCode.DELIVERY_IN_PROGRESS) == 7


def test_expired_file_is_deleted_but_never_while_streaming(store, tmp_path):
    idle = _ready_file(store, tmp_path)
    busy = _ready_file(store, tmp_path)
    store.begin(busy.file_id)
    later = time.time() + 3600
    assert store.prune(now=later) >= 1
    assert not idle.path.exists() and store.status(idle.file_id).state == DeliveryState.EXPIRED
    assert busy.path.exists()  # still streaming: untouched
    store._items[busy.file_id].expires_at = time.time() - 1
    store.finish(busy.file_id, completed=False)  # interrupted after its expiry ...
    with pytest.raises(AppError):
        store.begin(busy.file_id)
    assert busy.path.exists() is False  # ... so it is deleted then


def test_expired_on_request(store, tmp_path):
    item = _ready_file(store, tmp_path)
    store._items[item.file_id].expires_at = time.time() - 1
    with pytest.raises(AppError) as exc:
        store.begin(item.file_id)
    assert "expired" in exc.value.message and not item.path.exists()


def test_orphans_and_reset(store, tmp_path):
    orphan = store.root / "leftover.mp4"
    orphan.write_bytes(b"x")
    os.utime(orphan, (time.time() - 3600, time.time() - 3600))
    store.prune()
    assert not orphan.exists()
    _ready_file(store, tmp_path)
    store.reset()
    assert list(store.root.iterdir()) == []


@pytest.mark.parametrize("bad", ["../../etc/passwd", "0" * 31, "Z" * 32, "", "%2e%2e"])
def test_arbitrary_ids_rejected(store, bad):
    with pytest.raises(AppError) as exc:
        store.begin(bad)
    assert exc.value.code == ErrorCode.FILE_NOT_FOUND


# ------------------------------------------------------- streaming response
def _asgi_scope(spec="2.4"):
    return {"type": "http", "asgi": {"spec_version": spec}, "method": "GET", "path": "/", "headers": []}


def test_large_file_is_streamed_in_bounded_chunks(store, tmp_path):
    big = tmp_path / "output.mp4"
    with open(big, "wb") as fh:
        fh.truncate(64 * 1024 * 1024 + 123)  # sparse 64 MiB file
    item = store.add(big, "big.mp4")
    done = []
    response = DeliveryResponse(store.begin(item.file_id), done.append)
    sizes = []

    async def send(message):
        if message["type"] == "http.response.body":
            sizes.append(len(message["body"]))

    async def receive():
        await asyncio.sleep(3600)

    asyncio.run(response(_asgi_scope(), receive, send))
    assert max(sizes) <= CHUNK_BYTES and sum(sizes) == item.size_bytes
    assert done == [True]


def test_client_disconnect_keeps_file_for_retry(store, tmp_path):
    item = _ready_file(store, tmp_path, data=b"\1" * (3 * CHUNK_BYTES))
    response = DeliveryResponse(store.begin(item.file_id), lambda ok: store.finish(item.file_id, ok))
    sent = []

    async def send(message):
        if message["type"] == "http.response.body" and sent:
            raise OSError("connection reset by peer")  # browser cancelled mid-transfer
        sent.append(message)

    async def receive():
        await asyncio.sleep(3600)

    with pytest.raises(Exception):  # ClientDisconnect surfaces to the server
        asyncio.run(response(_asgi_scope("2.4"), receive, send))
    assert item.path.exists() and store.status(item.file_id).state == DeliveryState.READY


def test_disconnect_on_older_asgi_servers(store, tmp_path):
    item = _ready_file(store, tmp_path, data=b"\1" * (8 * CHUNK_BYTES))
    response = DeliveryResponse(store.begin(item.file_id), lambda ok: store.finish(item.file_id, ok))

    async def send(message):
        await asyncio.sleep(0.01)

    async def receive():
        return {"type": "http.disconnect"}  # client gone immediately

    asyncio.run(response(_asgi_scope("2.0"), receive, send))
    assert item.path.exists() and store.status(item.file_id).state == DeliveryState.READY


def test_failure_opening_file_releases_delivery(store, tmp_path):
    item = _ready_file(store, tmp_path)
    started = store.begin(item.file_id)
    started.path.unlink()  # vanished underneath us
    response = DeliveryResponse(started, lambda ok: store.finish(item.file_id, ok))

    async def send(message):
        pass

    async def receive():
        await asyncio.sleep(3600)

    with pytest.raises(Exception):  # Starlette reports OSErrors while streaming as ClientDisconnect
        asyncio.run(response(_asgi_scope(), receive, send))
    assert store.status(item.file_id).state == DeliveryState.READY  # released, not stuck "delivering"
    with pytest.raises(AppError):
        store.begin(item.file_id)  # and a retry reports the missing file cleanly
    assert store.status(item.file_id).state == DeliveryState.EXPIRED


# ------------------------------------------------------------- end to end
@pytest.fixture
def client(settings):
    app = create_app(settings, provider=FakeProvider(), processor=FakeProcessor())
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def _completed_job(client):
    a = client.post("/api/analyse", json={"url": URL}).json()
    job = client.post("/api/download", json={"analysis_id": a["analysis_id"], "option_id": "720p"}).json()
    return wait_for_job(client, job["job_id"])


def test_save_video_flow_leaves_no_copy(client, settings):
    done = _completed_job(client)
    file = done["file"]
    assert file["delivery_state"] == "ready" and file["available_until"]
    ready_dir = settings.temp_dir / "ready"
    assert len(list(ready_dir.iterdir())) == 1

    res = client.get(file["download_url"])
    assert res.status_code == 200 and len(res.content) == file["size_bytes"]
    assert res.headers["content-type"] == "video/mp4"
    assert res.headers["content-length"] == str(file["size_bytes"])
    assert res.headers["content-disposition"].startswith("attachment;")
    assert "1080p" not in res.headers["content-disposition"] and "720p.mp4" in res.headers["content-disposition"]
    assert res.headers["cache-control"] == "no-store"

    assert list(ready_dir.iterdir()) == []  # MediaLab's temporary copy is gone
    after = client.get(f"/api/jobs/{done['job_id']}").json()["file"]
    assert after["delivery_state"] == "delivered" and after["available_until"] is None
    again = client.get(file["download_url"])
    assert again.status_code == 404 and "already saved" in again.json()["error"]["message"]
    # Nothing anywhere else on disk either.
    leftovers = [p for p in settings.temp_dir.rglob("*") if p.is_file()]
    assert leftovers == []


def test_duplicate_request_while_streaming_gets_409(client):
    file = _completed_job(client)["file"]
    services = client.app.state.services
    services.deliveries.begin(file["file_id"])  # simulate a transfer in progress
    res = client.get(file["download_url"])
    assert res.status_code == 409 and res.json()["error"]["code"] == "delivery_in_progress"


def test_unretrieved_file_expires_via_cleanup(client, settings):
    file = _completed_job(client)["file"]
    services = client.app.state.services
    services.deliveries._items[file["file_id"]].expires_at = time.time() - 1
    run_cleanup(services)
    assert list((settings.temp_dir / "ready").iterdir()) == []
    res = client.get(file["download_url"])
    assert res.status_code == 404 and "expired" in res.json()["error"]["message"]


def test_partial_files_never_reach_delivery_area(settings):
    class Partial(FakeProvider):
        def download(self, url, video_index, format_ids, dest_dir, on_progress):
            (dest_dir / f"{format_ids[0]}.mp4.part").write_bytes(b"half")
            raise AppError(ErrorCode.DOWNLOAD_FAILED, "connection dropped")

    app = create_app(settings, provider=Partial(), processor=FakeProcessor())
    with TestClient(app, base_url="http://127.0.0.1") as c:
        a = c.post("/api/analyse", json={"url": URL}).json()
        job = c.post("/api/download", json={"analysis_id": a["analysis_id"]}).json()
        assert wait_for_job(c, job["job_id"])["state"] == "failed"
    files = [p for p in settings.temp_dir.rglob("*") if p.is_file()]
    assert files == []


def test_concurrent_jobs_get_separate_files(settings):
    from dataclasses import replace

    settings = replace(settings, max_concurrent_downloads=2)
    app = create_app(settings, provider=FakeProvider(), processor=FakeProcessor())
    with TestClient(app, base_url="http://127.0.0.1") as c:
        a = c.post("/api/analyse", json={"url": URL}).json()
        ids = [c.post("/api/download", json={"analysis_id": a["analysis_id"], "option_id": o}).json()["job_id"]
               for o in ("720p", "360p", "270p")]
        files = [wait_for_job(c, i)["file"] for i in ids]
        assert len({f["file_id"] for f in files}) == 3
        for f in files:
            assert c.get(f["download_url"]).status_code == 200
    assert list((settings.temp_dir / "ready").iterdir()) == []


def test_temp_usage_reported(client):
    _completed_job(client)
    usage = client.get("/api/settings").json()["temp_storage"]["usage_bytes"]
    assert usage > 0
