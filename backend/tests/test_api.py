"""API validation and responses (FastAPI TestClient, mocked provider)."""

import pytest
from fastapi.testclient import TestClient

from app.errors import AppError, ErrorCode
from app.main import create_app

from . import fixtures
from .conftest import FakeProvider, wait_for_job

URL = "https://x.com/medialab_test/status/1800000000000000001"


def analyse(client, url=URL):
    return client.post("/api/analyse", json={"url": url})


def test_analyse_returns_normalised_metadata(client):
    res = analyse(client)
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["analysis_id"]) == 32
    assert body["post"] == {
        "url": URL,
        "post_id": "1800000000000000001",
        "author_name": "Test Author",
        "author_handle": "medialab_test",
        "text": "A test post with a video https://t.co/abc",
        "possibly_sensitive": None,
        "drama": None,
    }
    assert body["provider"] == "fake"
    video = body["videos"][0]
    assert video["duration_seconds"] == 15.5
    assert [o["option_id"] for o in video["options"]] == ["best", "1080p", "720p", "360p", "270p"]
    assert video["options"][0]["is_best"] is True
    assert any(f["format_id"] == "hls-4500" and f["vcodec"] == "avc1.64001F" for f in video["formats"])
    assert body["selected_video_index"] == 1


def test_analyse_selects_video_from_url_suffix(settings, processor):
    app = create_app(settings, provider=FakeProvider(fixtures.multi_video_info()), processor=processor)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        body = analyse(c, URL + "/video/2").json()
    assert [v["index"] for v in body["videos"]] == [1, 2]
    assert body["selected_video_index"] == 2


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"url": "https://youtube.com/watch?v=1"}, 400, "invalid_url"),
        ({"url": "not a url"}, 400, "invalid_url"),
        ({"url": ""}, 422, "validation_error"),
        ({}, 422, "validation_error"),
        ({"url": URL, "extra": 1}, 422, "validation_error"),
        ({"url": 5}, 422, "validation_error"),
    ],
)
def test_analyse_validation(client, payload, status, code):
    res = client.post("/api/analyse", json=payload)
    assert res.status_code == status
    assert res.json()["error"]["code"] == code


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (ErrorCode.NOT_FOUND, 404),
        (ErrorCode.NO_VIDEO, 422),
        (ErrorCode.LOGIN_REQUIRED, 403),
        (ErrorCode.RATE_LIMITED, 429),
        (ErrorCode.EXTRACTION_FAILED, 502),
    ],
)
def test_analyse_extraction_errors(settings, processor, code, status):
    provider = FakeProvider(error=AppError(code, "nope"))
    with TestClient(create_app(settings, provider=provider, processor=processor), base_url="http://127.0.0.1") as c:
        res = analyse(c)
    assert res.status_code == status
    err = res.json()["error"]
    assert (err["code"], err["message"]) == (code.value, "nope")
    assert isinstance(err["retryable"], bool)
    assert err["retryable"] is (code in (ErrorCode.RATE_LIMITED, ErrorCode.EXTRACTION_FAILED))


def test_full_download_flow(client, provider, settings):
    analysis = analyse(client).json()
    res = client.post("/api/download", json={"analysis_id": analysis["analysis_id"], "option_id": "1080p"})
    assert res.status_code == 202, res.text
    job = res.json()
    assert job["state"] in ("queued", "downloading", "processing", "completed")
    assert job["option_label"] == "1080p"

    done = wait_for_job(client, job["job_id"])
    assert done["state"] == "completed"
    assert done["progress"]["percent"] == 100.0
    file = done["file"]
    assert file["filename"].endswith("[1800000000000000001] 1080p.mp4")
    assert file["download_url"] == f"/api/files/{file['file_id']}"
    raw = client.get(f"/api/jobs/{job['job_id']}").text
    assert str(settings.config_dir) not in raw and str(settings.temp_dir) not in raw  # no local paths leak
    assert provider.calls[0] == (URL, 1, ["hls-4500", "hls-audio-128000-Audio"])

    got = client.get(file["download_url"])
    assert got.status_code == 200
    assert got.headers["content-type"] == "video/mp4"
    assert "attachment" in got.headers["content-disposition"]
    assert len(got.content) == file["size_bytes"]


def test_download_best_default(client, provider):
    analysis = analyse(client).json()
    job = client.post("/api/download", json={"analysis_id": analysis["analysis_id"]}).json()
    assert job["option_id"] == "best" and job["option_label"] == "Best Available (1080p)"
    assert wait_for_job(client, job["job_id"])["state"] == "completed"


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"analysis_id": "f" * 32}, 410, "analysis_expired"),
        ({"analysis_id": "../../etc"}, 422, "validation_error"),
        ({"analysis_id": "A" * 32}, 422, "validation_error"),
        ({"option_id": "4320p"}, 400, "invalid_selection"),
        ({"option_id": "best; rm -rf /"}, 422, "validation_error"),
        ({"video_index": 5}, 400, "invalid_selection"),
        ({"video_index": 0}, 422, "validation_error"),
    ],
)
def test_download_validation(client, payload, status, code):
    analysis = analyse(client).json()
    res = client.post("/api/download", json={"analysis_id": analysis["analysis_id"], **payload})
    assert res.status_code == status, res.text
    assert res.json()["error"]["code"] == code


def test_download_incompatible_option_rejected(settings, processor):
    provider = FakeProvider(fixtures.vp9_only_info())
    with TestClient(create_app(settings, provider=provider, processor=processor), base_url="http://127.0.0.1") as c:
        analysis = analyse(c).json()
        res = c.post("/api/download", json={"analysis_id": analysis["analysis_id"]})
    assert res.status_code == 422 and res.json()["error"]["code"] == "incompatible_format"


def test_failed_job_reports_error(client, provider):
    provider.download_error = AppError(ErrorCode.NETWORK_ERROR, "Could not reach X.")
    analysis = analyse(client).json()
    job = client.post("/api/download", json={"analysis_id": analysis["analysis_id"]}).json()
    done = wait_for_job(client, job["job_id"])
    assert done["state"] == "failed"
    assert done["error"]["code"] == "network_error" and done["error"]["message"] == "Could not reach X."
    assert done["error"]["retryable"] is True and done["error"]["action"]
    assert done["file"] is None


def test_unknown_job_and_file(client):
    assert client.get("/api/jobs/" + "0" * 32).json()["error"]["code"] == "job_not_found"
    assert client.get("/api/jobs/nope").status_code == 404
    res = client.get("/api/files/" + "0" * 32)
    assert res.status_code == 404 and res.json()["error"]["code"] == "file_not_found"
    assert client.get("/api/files/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_cross_origin_post_rejected(client):
    res = client.post("/api/analyse", json={"url": URL}, headers={"Origin": "https://evil.example"})
    assert res.status_code == 403 and res.json()["error"]["code"] == "forbidden"
    ok = client.post("/api/analyse", json={"url": URL}, headers={"Origin": "http://localhost:5173"})
    assert ok.status_code == 200


def test_non_local_host_header_rejected(settings, provider, processor):
    app = create_app(settings, provider=provider, processor=processor)
    with TestClient(app, base_url="http://attacker.example") as c:
        assert c.post("/api/analyse", json={"url": URL}).status_code == 400


def test_non_json_body_rejected(client):
    res = client.post("/api/analyse", content=b"url=" + URL.encode(), headers={"Content-Type": "text/plain"})
    assert res.status_code == 422


def test_temp_dir_cleaned_on_startup(settings, provider, processor):
    stale = settings.temp_dir / "job-stale"
    stale.mkdir(parents=True)
    (stale / "x.part").write_bytes(b"x")
    with TestClient(create_app(settings, provider=provider, processor=processor), base_url="http://127.0.0.1"):
        assert not stale.exists()


# ------------------------------------------- SEC-1: cross-site requests of any method
@pytest.mark.parametrize("path", ["/api/settings", "/api/tiktok-account", "/api/shortdrama/series/7100000000000000101",
                                  "/api/files/" + "a" * 32])
@pytest.mark.parametrize("headers", [{"Sec-Fetch-Site": "cross-site"}, {"Origin": "https://evil.example"}])
def test_cross_site_get_requests_are_refused(client, path, headers):
    res = client.get(path, headers=headers)
    assert res.status_code == 403 and res.json()["error"]["code"] == "forbidden"


def test_same_origin_and_headerless_get_requests_still_work(client):
    assert client.get("/api/settings", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert client.get("/api/settings", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 200
    assert client.get("/api/settings").status_code == 200


def test_cancel_a_running_job(client, provider):
    """POST /api/jobs/{id}/cancel marks the job cancelled at once; its worker stops at the next update."""
    import threading
    import time as _t

    provider.gate = threading.Event()  # hold the download until we've cancelled
    analysed = analyse(client).json()
    job = client.post("/api/download", json={"analysis_id": analysed["analysis_id"], "video_index": 1,
                                             "option_id": "best"}).json()
    res = client.post(f"/api/jobs/{job['job_id']}/cancel")
    assert res.status_code == 200
    assert res.json()["state"] == "cancelled" and res.json()["error"]["code"] == "download_cancelled"
    provider.gate.set()
    _t.sleep(0.3)  # the worker notices the cancellation and stops; the job must stay cancelled
    body = client.get(f"/api/jobs/{job['job_id']}").json()
    assert body["state"] == "cancelled" and body["error"]["code"] == "download_cancelled" and body["file"] is None
    assert client.post(f"/api/jobs/{job['job_id']}/cancel").status_code == 200  # idempotent
    assert client.post("/api/jobs/" + "0" * 32 + "/cancel").json()["error"]["code"] == "job_not_found"
    assert client.post(f"/api/jobs/{job['job_id']}/cancel", headers={"Origin": "https://evil.example"}).status_code == 403
