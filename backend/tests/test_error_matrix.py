"""Error-scenario matrix for X, TikTok videos and TikTok Short Drama (all mocked).

Every failure must reach the client as a specific code with a message, a
recommended action and a retryable flag, never a generic "no video".
"""

from collections import namedtuple

import pytest
from fastapi.testclient import TestClient

from app import resolve as resolve_mod
from app import storage
from app.errors import RETRYABLE, AppError, ErrorCode
from app.main import create_app
from app.providers.router import PlatformRouter
from app.providers.tiktok_shortdrama import TikTokShortDramaProvider
from app.providers.ytdlp_provider import YtDlpProvider, map_ytdlp_error
from app.retry import with_retries
from app.tiktok_account import TikTokAccountStore
from app.validation import PLATFORM_SHORTDRAMA, check_platform, validate_post_url

from .conftest import FakeProcessor, FakeProvider, wait_for_job

X_URL = "https://x.com/medialab_test/status/1800000000000000001"
TT_URL = "https://www.tiktok.com/@someone/video/7100000000000003001"
SD_URL = "https://www.tiktok.com/shortdrama/episode/7100000000000000101/2"
PLATFORM_URLS = {"x": X_URL, "tiktok": TT_URL}


def router_with(settings, x=None, tiktok=None):
    return PlatformRouter({"x": x or FakeProvider(), "tiktok": tiktok or FakeProvider(),
                           PLATFORM_SHORTDRAMA: FakeProvider()})  # real Short Drama provider: see test_shortdrama.py


def client_for(settings, **kw):
    return TestClient(create_app(settings, provider=router_with(settings, **kw), processor=FakeProcessor()),
                      base_url="http://127.0.0.1")


def assert_error_shape(err, code):
    assert err["code"] == code
    assert err["message"] and isinstance(err["retryable"], bool)
    assert err.get("action"), f"{code} should recommend an action"


# ------------------------------------------------------------ Short Drama
@pytest.mark.parametrize(
    ("raw", "canonical", "episode"),
    [
        (SD_URL, SD_URL, 2),
        ("tiktok.com/shortdrama/episode/7100000000000000101/2?lang=en&is_from_webapp=1", SD_URL, 2),
        ("https://m.tiktok.com/shortdrama/episode/7100000000000000101/12/",
         "https://www.tiktok.com/shortdrama/episode/7100000000000000101/12", 12),
    ],
)
def test_short_drama_urls(raw, canonical, episode):
    v = validate_post_url(raw)
    assert v.platform == PLATFORM_SHORTDRAMA and v.canonical_url == canonical and v.episode == episode
    assert v.post_id == "7100000000000000101"


@pytest.mark.parametrize("raw", [
    "https://www.tiktok.com/shortdrama",
    "https://www.tiktok.com/shortdrama/7100000000000000101",
    "https://www.tiktok.com/shortdrama/episode/7100000000000000101",
    "https://www.tiktok.com/shortdrama/episode/7100000000000000101/0",
    "https://www.tiktok.com/shortdrama/episode/abc/2",
    "https://www.tiktok.com/shortdrama/series/7100000000000000101/2",
])
def test_unsupported_short_drama_link_formats(raw):
    with pytest.raises(AppError) as exc:
        validate_post_url(raw)
    assert exc.value.code == ErrorCode.UNSUPPORTED_EPISODE_URL
    assert "isn't supported yet" in exc.value.message


def test_default_wiring_has_three_platforms(settings):
    from app.main import build_default_provider, build_settings_store

    router = build_default_provider(settings, build_settings_store(settings), TikTokAccountStore(settings.config_dir))
    assert set(router.providers) == {"x", "tiktok", PLATFORM_SHORTDRAMA}
    assert isinstance(router.providers[PLATFORM_SHORTDRAMA], TikTokShortDramaProvider)


# ------------------------------------------------------------- wrong tab
@pytest.mark.parametrize(
    ("url", "tab", "detected"),
    [
        (TT_URL, "x", "tiktok"),
        (SD_URL, "tiktok", PLATFORM_SHORTDRAMA),
        (X_URL, "tiktok", "x"),
        ("https://vm.tiktok.com/ZMabc123/", "x", "tiktok"),
    ],
)
def test_wrong_tab_is_detected_with_switch_suggestion(settings, url, tab, detected):
    with client_for(settings) as c:
        res = c.post("/api/analyse", json={"url": url, "platform": tab})
    assert res.status_code == 400
    err = res.json()["error"]
    assert_error_shape(err, "wrong_platform")
    assert err["details"]["detected_platform"] == detected
    assert "Switch to the" in err["action"]


@pytest.mark.parametrize("tab", ["tiktok", PLATFORM_SHORTDRAMA])
def test_short_links_are_accepted_in_both_tiktok_tabs(tab):
    assert validate_post_url("https://vt.tiktok.com/ZSabc123/", tab).short_link


def test_short_link_classified_after_resolution(settings, monkeypatch):
    monkeypatch.setattr(resolve_mod, "resolve_tiktok_short_link", lambda url, timeout: validate_post_url(SD_URL))
    with client_for(settings) as c:
        wrong = c.post("/api/analyse", json={"url": "https://vm.tiktok.com/ZMabc123/", "platform": "tiktok"})
        right = c.post("/api/analyse", json={"url": "https://vm.tiktok.com/ZMabc123/", "platform": PLATFORM_SHORTDRAMA})
    assert wrong.json()["error"]["code"] == "wrong_platform"
    assert wrong.json()["error"]["details"]["detected_platform"] == PLATFORM_SHORTDRAMA
    assert right.status_code == 200 and right.json()["platform"] == PLATFORM_SHORTDRAMA


def test_no_tab_given_keeps_auto_detection(settings):
    with client_for(settings) as c:
        assert c.post("/api/analyse", json={"url": X_URL}).status_code == 200


def test_check_platform_passes_matching_tab():
    check_platform(validate_post_url(TT_URL), "tiktok")


# ------------------------------------------------------- analysis matrix
ANALYSE_CASES = [
    ("unrecognised URL", None, "https://example.com/watch?v=1", "invalid_url", 400),
    ("unsupported X path", None, "https://x.com/someone", "unsupported_url", 400),
    ("expired short link", "short_link_expired", None, "short_link_expired", 404),
    ("not found", "not_found", None, "not_found", 404),
    ("login required", "login_required", None, "login_required", 403),
    ("DRM / protected", "protected_content", None, "protected_content", 403),
    ("region", "region_restricted", None, "region_restricted", 451),
    ("rate limited", "rate_limited", None, "rate_limited", 429),
    ("network", "network_error", None, "network_error", 502),
    ("unexpected response", "extraction_failed", None, "extraction_failed", 502),
    ("foreign media host", "media_host_blocked", None, "media_host_blocked", 422),
    ("no video", "no_video", None, "no_video", 422),
]


@pytest.mark.parametrize("platform", ["x", "tiktok"])
@pytest.mark.parametrize(("name", "inject", "url", "code", "status"), ANALYSE_CASES, ids=[c[0] for c in ANALYSE_CASES])
def test_analysis_error_matrix(settings, platform, name, inject, url, code, status):
    provider = FakeProvider(error=AppError(ErrorCode(inject), f"{name} happened")) if inject else FakeProvider()
    with client_for(settings, **{platform: provider}) as c:
        res = c.post("/api/analyse", json={"url": url or PLATFORM_URLS[platform], "platform": platform})
    assert res.status_code == status, res.text
    err = res.json()["error"]
    assert_error_shape(err, code)
    assert err["retryable"] is (ErrorCode(code) in RETRYABLE)


# ---------------------------------------------------- download matrix
Usage = namedtuple("Usage", "total used free")


@pytest.mark.parametrize("platform", ["x", "tiktok"])
@pytest.mark.parametrize(
    ("name", "inject_download", "processing", "expected"),
    [
        ("expired CDN URL", "cdn_url_expired", None, "cdn_url_expired"),
        ("network interruption", "download_interrupted", None, "download_interrupted"),
        ("download failure", "download_failed", None, "download_failed"),
        ("processing failure", None, "processing_failed", "processing_failed"),
        ("incompatible codec", None, "incompatible_format", "incompatible_format"),
    ],
)
def test_job_error_matrix(settings, platform, name, inject_download, processing, expected):
    provider = FakeProvider()
    if inject_download:
        provider.download_error = AppError(ErrorCode(inject_download), f"{name}")
    app = create_app(settings, provider=router_with(settings, **{platform: provider}), processor=FakeProcessor())
    if processing:
        app.state.services.processor.error = AppError(ErrorCode(processing), f"{name}")
    with TestClient(app, base_url="http://127.0.0.1") as c:
        a = c.post("/api/analyse", json={"url": PLATFORM_URLS[platform]}).json()
        job = c.post("/api/download", json={"analysis_id": a["analysis_id"]}).json()
        done = wait_for_job(c, job["job_id"])
    assert done["state"] == "failed"
    assert_error_shape(done["error"], expected)
    assert not [p for p in settings.temp_dir.rglob("*") if p.is_file()]  # cleanup after failure


def test_file_too_large_and_disk_space(settings, monkeypatch):
    with client_for(settings) as c:
        a = c.post("/api/analyse", json={"url": X_URL}).json()
        c.patch("/api/settings", json={"max_file_size_mb": 256})
        services = c.app.state.services
        stored = services.analyses.get(a["analysis_id"])
        stored.options[1] = [o.model_copy(update={"filesize": 300 * 1024 * 1024}) if o.option_id == "720p" else o
                             for o in stored.options[1]]
        too_big = c.post("/api/download", json={"analysis_id": a["analysis_id"], "option_id": "720p"})
        assert too_big.status_code == 413
        assert_error_shape(too_big.json()["error"], "file_too_large")
        assert "Settings" in too_big.json()["error"]["message"]
        monkeypatch.setattr(storage.shutil, "disk_usage", lambda p: Usage(10**12, 0, 1024))
        no_space = c.post("/api/download", json={"analysis_id": a["analysis_id"], "option_id": "360p"})
    assert no_space.status_code == 507
    assert_error_shape(no_space.json()["error"], "insufficient_space")


def test_delivery_errors_have_actions(settings):
    with client_for(settings) as c:
        assert_error_shape(c.get("/api/files/" + "0" * 32).json()["error"], "file_not_found")


def test_validation_errors_still_structured(settings):
    with client_for(settings) as c:
        err = c.post("/api/analyse", json={"url": X_URL, "platform": "youtube"}).json()["error"]
    assert err["code"] == "validation_error" and err["retryable"] is False


# ---------------------------------------------------- yt-dlp mapping
@pytest.mark.parametrize(
    ("message", "during_download", "code"),
    [
        ("ERROR: This video is DRM protected", False, ErrorCode.PROTECTED_CONTENT),
        ("ERROR: [twitter] 1: This video is not available in your country", False, ErrorCode.REGION_RESTRICTED),
        ("ERROR: unable to download video data: HTTP Error 403: Forbidden", True, ErrorCode.CDN_URL_EXPIRED),
        ("ERROR: unable to download video data: <urlopen error [Errno 54] Connection reset by peer>", True,
         ErrorCode.DOWNLOAD_INTERRUPTED),
        ("ERROR: Read timed out.", True, ErrorCode.DOWNLOAD_INTERRUPTED),
        ("ERROR: Read timed out.", False, ErrorCode.TIMEOUT),
        ("ERROR: [twitter] 1: Something unexpected", False, ErrorCode.EXTRACTION_FAILED),
    ],
)
def test_ytdlp_mapping(message, during_download, code):
    from yt_dlp.utils import DownloadError

    err = map_ytdlp_error(DownloadError(message), during_download=during_download)
    assert err.code == code
    if code == ErrorCode.EXTRACTION_FAILED:
        assert "Something unexpected" in err.message  # original reason kept, not replaced by "no video"


# ------------------------------------------------------------- retries
def test_with_retries_backoff_and_limits():
    calls, sleeps = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise AppError(ErrorCode.NETWORK_ERROR, "down")
        return "ok"

    assert with_retries(flaky, what="t", sleep=sleeps.append) == "ok"
    assert sleeps == [1.0, 2.0]

    calls.clear()
    def always():
        calls.append(1)
        raise AppError(ErrorCode.TIMEOUT, "slow")
    with pytest.raises(AppError) as exc:
        with_retries(always, what="t", attempts=3, sleep=lambda s: None)
    assert len(calls) == 3 and exc.value.code == ErrorCode.TIMEOUT  # bounded, original error kept

    calls.clear()
    def denied():
        calls.append(1)
        raise AppError(ErrorCode.LOGIN_REQUIRED, "no")
    with pytest.raises(AppError):
        with_retries(denied, what="t", sleep=lambda s: None)
    assert len(calls) == 1  # non-transient errors are never retried


def test_analysis_retries_transient_failures(settings, monkeypatch):
    provider = YtDlpProvider(settings, "x")
    provider.retry_sleep = lambda s: None
    attempts = []

    def once(url):
        attempts.append(1)
        if len(attempts) == 1:
            raise AppError(ErrorCode.NETWORK_ERROR, "blip")
        return "metadata"

    monkeypatch.setattr(provider, "_extract_once", once)
    assert provider.extract(validate_post_url(X_URL)) == "metadata" and len(attempts) == 2


def test_download_retry_after_interruption_reports_stage(settings, monkeypatch, tmp_path):
    provider = YtDlpProvider(settings, "x")
    sleeps, updates, attempts = [], [], []
    provider.retry_sleep = sleeps.append

    def once(url, video_index, ids, work, on_progress):
        attempts.append(list(ids))
        if len(attempts) == 1:
            raise AppError(ErrorCode.DOWNLOAD_INTERRUPTED, "reset")
        path = work / "v.mp4"
        path.write_bytes(b"x")
        return {ids[0]: path}

    monkeypatch.setattr(provider, "_download_once", once)
    out = provider.download(validate_post_url(X_URL), 1, ["http-2176"], tmp_path, updates.append)
    assert out["http-2176"].is_file() and sleeps == [2.0]
    assert updates[0].status == "retrying" and "interrupted" in updates[0].note and "attempt 2 of 3" in updates[0].note


def test_job_stage_shows_retry_reason(settings):
    class Retrying(FakeProvider):
        def download(self, url, video_index, format_ids, dest_dir, on_progress):
            from app.providers.base import ProgressUpdate

            on_progress(ProgressUpdate(format_ids[0], "retrying", 0, None, True,
                                       note="The video link expired. Refreshing the download information…"))
            self.stage_seen = c.app.state.services.jobs._jobs[job_id[0]].stage
            return super().download(url, video_index, format_ids, dest_dir, on_progress)

    provider = Retrying()
    job_id = []
    with client_for(settings, x=provider) as c:
        a = c.post("/api/analyse", json={"url": X_URL}).json()
        services = c.app.state.services
        original_submit = services.jobs.submit

        def submit(plan):
            snap = original_submit(plan)
            job_id.append(snap.job_id)
            return snap

        services.jobs.submit = submit
        job = c.post("/api/download", json={"analysis_id": a["analysis_id"]}).json()
        assert wait_for_job(c, job["job_id"])["state"] == "completed"
    assert "Refreshing the download information" in provider.stage_seen


def test_wrong_platform_wording():
    with pytest.raises(AppError) as exc:
        validate_post_url(TT_URL, "x")
    assert exc.value.message == "This is a TikTok link, not an X link."
    assert exc.value.action == "Switch to the TikTok Videos tab."
    with pytest.raises(AppError) as exc:
        validate_post_url(X_URL, "tiktok")
    assert exc.value.message == "This is an X link, not a TikTok link."
    assert exc.value.action == "Switch to the X tab."
