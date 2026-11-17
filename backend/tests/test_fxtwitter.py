"""FxTwitter fallback provider, provider chain, validating HTTP client and large-file safeguards.

Everything is mocked: no request reaches X or FxTwitter.
"""

import io
import json
import urllib.request
from collections import namedtuple
from dataclasses import replace
from email.message import Message
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app import storage
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.net import BlockedRedirect, _ValidatingRedirectHandler, open_url
from app.providers import fxtwitter_provider as fxmod
from app.providers.chain import ProviderChain
from app.providers.fxtwitter_provider import FxTwitterProvider
from app.providers.ytdlp_provider import YtDlpProvider
from app.selection import build_options, resolve_option
from app.validation import is_allowed_media_url, validate_post_url

from .conftest import FakeProcessor, FakeProvider, wait_for_job

# The long-video post investigated earlier, used as a diagnostic example (mocked).
POST_ID = "2117302655580311799"
URL = validate_post_url(f"https://x.com/somebody/status/{POST_ID}")
CDN = "https://video.twimg.com/amplify_video/1/vid/avc1"
SIZES = {
    f"{CDN}/480x270/a.mp4": 78_719_806,
    f"{CDN}/1280x720/b.mp4": 695_602_502,
    f"{CDN}/1920x1080/c.mp4": 3_034_649_102,
}


def fx_status(**overrides):
    """Shape taken from the documented FxTwitter v2 /2/status/{id} response."""
    status = {
        "type": "status",
        "id": POST_ID,
        "text": "A long video",
        "author": {"name": "Some Author", "screen_name": "somebody"},
        "possibly_sensitive": False,
        "media": {
            "videos": [
                {
                    "id": "2117209835213062145",
                    "type": "video",
                    "url": f"{CDN}/1920x1080/top.mp4",
                    "thumbnail_url": "https://pbs.twimg.com/amplify_video_thumb/1/img/t.jpg",
                    "width": 1920,
                    "height": 1080,
                    "duration": 6145.5,
                    "formats": [
                        {"container": "m3u8", "url": "https://video.twimg.com/amplify_video/1/pl/m.m3u8"},
                        {"container": "mp4", "codec": "h264", "bitrate": 256000, "url": f"{CDN}/480x270/a.mp4"},
                        {"container": "mp4", "codec": "h264", "bitrate": 2176000, "url": f"{CDN}/1280x720/b.mp4"},
                        {"container": "mp4", "codec": "h264", "bitrate": 10368000, "url": f"{CDN}/1920x1080/c.mp4"},
                        {"container": "mp4", "codec": "h264", "bitrate": 99, "url": "https://evil.example/x.mp4"},
                        {"container": "mp4", "codec": "h264", "bitrate": 98, "url": "http://video.twimg.com/plain.mp4"},
                    ],
                }
            ]
        },
    }
    status.update(overrides)
    return {"code": 200, "message": "OK", "status": status}


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes = b"", status: int = 200, headers: dict | None = None, url: str = ""):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v
        self._url = url

    def getcode(self):
        return self.status

    def geturl(self):
        return self._url


@pytest.fixture
def fake_net(monkeypatch):
    """Route the provider's HTTP calls to canned responses; record every request."""
    state = {"api": fx_status(), "api_status": 200, "sizes": dict(SIZES), "media": b"\0" * 3000,
             "media_type": "video/mp4", "calls": []}

    def fake_open(url, allowed, *, timeout, method="GET", headers=None):
        assert allowed(url), f"provider tried a non-allowlisted URL: {url}"
        state["calls"].append((method, url))
        if url.startswith("https://api.fxtwitter.com/2/status/"):
            return FakeResponse(json.dumps(state["api"]).encode(), state["api_status"], url=url)
        if method == "HEAD":
            size = state["sizes"].get(url)
            return FakeResponse(b"", 200, {"Content-Length": str(size)} if size else {}, url=url)
        body = state["media"]
        return FakeResponse(body, 200, {"Content-Type": state["media_type"], "Content-Length": str(len(body))}, url=url)

    monkeypatch.setattr(fxmod, "open_url", fake_open)
    return state


@pytest.fixture
def fx(settings):
    return FxTwitterProvider(settings)


# ------------------------------------------------------------ normalisation
def test_normalises_documented_response(fx, fake_net):
    post = fx.extract(URL)
    assert post.provider == "fxtwitter" and post.post_id == POST_ID
    assert (post.author_handle, post.author_name, post.text) == ("somebody", "Some Author", "A long video")
    video = post.videos[0]
    assert video.duration_seconds == 6145.5
    assert video.thumbnail_url.startswith("https://pbs.twimg.com/")
    by_h = {f.height: f for f in video.formats}
    assert sorted(by_h) == [270, 720, 1080]  # HLS, foreign-host and plain-http variants dropped
    assert by_h[1080].width == 1920 and by_h[1080].vcodec == "avc1" and by_h[1080].tbr == 10368
    assert by_h[1080].filesize == 3_034_649_102 and by_h[1080].filesize_approx is None
    assert by_h[1080].has_audio is None  # not reported -> unknown; ffprobe verifies after download
    assert all(f.mp4_compatible for f in video.formats)


def test_estimated_size_when_cdn_gives_no_length(fx, fake_net):
    fake_net["sizes"].pop(f"{CDN}/480x270/a.mp4")
    fmt = next(f for f in fx.extract(URL).videos[0].formats if f.height == 270)
    assert fmt.filesize is None and fmt.filesize_approx == int(256 * 1000 / 8 * 6145.5)


def test_only_the_post_id_is_sent(fx, fake_net):
    fx.extract(validate_post_url(f"https://twitter.com/somebody/status/{POST_ID}?s=20&secret=1"))
    api_calls = [u for _, u in fake_net["calls"] if "fxtwitter" in u]
    assert api_calls == [f"https://api.fxtwitter.com/2/status/{POST_ID}"]
    assert all(u.startswith("https://video.twimg.com/") for m, u in fake_net["calls"] if "fxtwitter" not in u)


def test_mp4_option_selection(fx, fake_net):
    options = build_options(fx.extract(URL).videos[0])
    assert [o.option_id for o in options] == ["best", "1080p", "720p", "270p"]
    assert options[0].label == "Best Available (1080p)" and options[0].filesize == 3_034_649_102
    assert not any(o.requires_merge for o in options)


# ----------------------------------------------------- sensitivity vs access
@pytest.mark.parametrize("flag", [True, False, None])
def test_sensitivity_is_information_not_an_access_gate(fx, fake_net, flag):
    fake_net["api"] = fx_status(possibly_sensitive=flag)
    post = fx.extract(URL)
    assert post.videos  # never refused because of the classification
    assert post.possibly_sensitive is flag


@pytest.mark.parametrize(
    ("reason", "code"),
    [("private", ErrorCode.UNAVAILABLE), ("deleted", ErrorCode.NOT_FOUND), ("suspended", ErrorCode.UNAVAILABLE),
     ("blocked", ErrorCode.UNAVAILABLE), ("unavailable", ErrorCode.NOT_FOUND), ("something-new", ErrorCode.NOT_FOUND)],
)
def test_genuine_access_controls_are_respected(fx, fake_net, reason, code):
    fake_net["api"] = {"code": 200, "status": {"type": "tombstone", "reason": reason}}
    with pytest.raises(AppError) as exc:
        fx.extract(URL)
    assert exc.value.code == code


def test_protected_account_status_code(fx, fake_net):
    fake_net["api"] = {"code": 401, "message": "PRIVATE_TWEET"}
    with pytest.raises(AppError) as exc:
        fx.extract(URL)
    assert exc.value.code == ErrorCode.UNAVAILABLE and "protected" in exc.value.message


# --------------------------------------------------------- upstream errors
@pytest.mark.parametrize(
    ("api", "status", "code"),
    [
        ({"code": 404, "message": "NOT_FOUND"}, 404, ErrorCode.NOT_FOUND),
        ({"code": 429}, 429, ErrorCode.RATE_LIMITED),
        ({"code": 500, "message": "API_FAIL"}, 500, ErrorCode.EXTRACTION_FAILED),
        ({"code": 400}, 400, ErrorCode.EXTRACTION_FAILED),
        ({"code": 200}, 200, ErrorCode.EXTRACTION_FAILED),  # no status object
        ("not json", 200, ErrorCode.EXTRACTION_FAILED),
        (fx_status(media={"photos": [{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]}), 200, ErrorCode.NO_VIDEO),
    ],
)
def test_upstream_api_errors(fx, fake_net, api, status, code):
    fake_net["api"], fake_net["api_status"] = api, status
    with pytest.raises(AppError) as exc:
        fx.extract(URL)
    assert exc.value.code == code


def test_only_foreign_cdn_hosts_means_no_video(fx, fake_net):
    api = fx_status()
    for f in api["status"]["media"]["videos"][0]["formats"]:
        f["url"] = "https://cdn.example.com/x.mp4"
    fake_net["api"] = api
    with pytest.raises(AppError) as exc:
        fx.extract(URL)
    assert exc.value.code == ErrorCode.NO_VIDEO


# ------------------------------------------------------------------ download
def _fid(fx, height):
    return next(f.format_id for f in fx.extract(URL).videos[0].formats if f.height == height)


def test_download_streams_from_cdn_with_progress(fx, fake_net, tmp_path):
    fid = _fid(fx, 720)
    updates = []
    out = fx.download(URL, 1, [fid], tmp_path, updates.append)
    assert out[fid].read_bytes() == fake_net["media"]
    assert updates[-1].status == "finished" and updates[-1].downloaded_bytes == 3000
    assert not list(tmp_path.glob("*.part"))
    media_gets = [u for m, u in fake_net["calls"] if m == "GET" and "fxtwitter" not in u]
    assert media_gets == [f"{CDN}/1280x720/b.mp4"]  # bytes come from X's CDN, not FxTwitter


def test_download_rejects_non_video_content(fx, fake_net, tmp_path):
    fid = _fid(fx, 270)
    fake_net["media_type"] = "text/html"
    with pytest.raises(AppError) as exc:
        fx.download(URL, 1, [fid], tmp_path, lambda u: None)
    assert exc.value.code == ErrorCode.DOWNLOAD_FAILED


def test_download_unknown_format(fx, fake_net, tmp_path):
    with pytest.raises(AppError) as exc:
        fx.download(URL, 1, ["fx-mp4-9999-1"], tmp_path, lambda u: None)
    assert exc.value.code == ErrorCode.FORMAT_UNAVAILABLE


def test_download_detects_truncated_file(fx, fake_net, tmp_path, monkeypatch):
    fid = _fid(fx, 270)
    original = fxmod.open_url

    def short(url, allowed, **kw):
        resp = original(url, allowed, **kw)
        if urlsplit(url).hostname == "video.twimg.com" and kw.get("method", "GET") == "GET":
            resp.headers.replace_header("Content-Length", "999999")
        return resp

    monkeypatch.setattr(fxmod, "open_url", short)
    with pytest.raises(AppError) as exc:
        fx.download(URL, 1, [fid], tmp_path, lambda u: None)
    assert exc.value.code == ErrorCode.DOWNLOAD_FAILED


def test_download_rechecks_access_controls(fx, fake_net, tmp_path):
    fid = _fid(fx, 270)
    fake_net["api"] = {"code": 200, "status": {"type": "tombstone", "reason": "private"}}
    with pytest.raises(AppError) as exc:
        fx.download(URL, 1, [fid], tmp_path, lambda u: None)
    assert exc.value.code == ErrorCode.UNAVAILABLE


# --------------------------------------------------------------------- chain
class Failing(FakeProvider):
    name = "yt-dlp"

    def __init__(self, code):
        super().__init__(error=AppError(code, "primary says no"))


def _named(provider, name):
    provider.name = name
    return provider


def test_primary_success_never_contacts_fallback():
    second = _named(FakeProvider(), "fxtwitter")
    second.extract = lambda url: pytest.fail("fallback must not be contacted")
    assert ProviderChain(_named(FakeProvider(), "yt-dlp"), second).extract(URL).provider == "yt-dlp"


@pytest.mark.parametrize("code", [ErrorCode.NO_VIDEO, ErrorCode.NOT_FOUND])
def test_primary_failure_uses_fallback(code):
    assert ProviderChain(Failing(code), _named(FakeProvider(), "fxtwitter")).extract(URL).provider == "fxtwitter"


@pytest.mark.parametrize(
    "code",
    [ErrorCode.LOGIN_REQUIRED, ErrorCode.UNAVAILABLE, ErrorCode.RATE_LIMITED, ErrorCode.NETWORK_ERROR,
     ErrorCode.TIMEOUT, ErrorCode.EXTRACTION_FAILED],
)
def test_other_primary_errors_never_use_fallback(code):
    second = _named(FakeProvider(), "fxtwitter")
    second.extract = lambda url: pytest.fail("fallback must not be contacted")
    with pytest.raises(AppError) as exc:
        ProviderChain(Failing(code), second).extract(URL)
    assert exc.value.code == code


def test_chain_error_precedence():
    specific = _named(FakeProvider(error=AppError(ErrorCode.UNAVAILABLE, "protected")), "fxtwitter")
    with pytest.raises(AppError) as exc:
        ProviderChain(Failing(ErrorCode.NO_VIDEO), specific).extract(URL)
    assert exc.value.code == ErrorCode.UNAVAILABLE
    same = _named(FakeProvider(error=AppError(ErrorCode.NO_VIDEO, "none here either")), "fxtwitter")
    with pytest.raises(AppError) as exc:
        ProviderChain(Failing(ErrorCode.NO_VIDEO), same).extract(URL)
    assert exc.value.message == "primary says no"


def test_download_uses_the_provider_that_analysed(settings):
    primary, second = Failing(ErrorCode.NO_VIDEO), _named(FakeProvider(), "fxtwitter")
    settings = replace(settings, fxtwitter_fallback=True)
    app = create_app(settings, provider=ProviderChain(primary, second), processor=FakeProcessor())
    with TestClient(app, base_url="http://127.0.0.1") as c:
        a = c.post("/api/analyse", json={"url": URL.canonical_url}).json()
        assert a["provider"] == "fxtwitter"
        job = c.post("/api/download", json={"analysis_id": a["analysis_id"]}).json()
        assert wait_for_job(c, job["job_id"])["state"] == "completed"
    assert second.calls and not primary.calls


# ------------------------------------------- app wiring: fallback on / off
@pytest.fixture
def ytdlp_says_no_video(monkeypatch):
    def no_video(self, url):
        raise AppError(ErrorCode.NO_VIDEO, "No downloadable video was found.")

    monkeypatch.setattr(YtDlpProvider, "extract", no_video)


def test_fallback_disabled_by_default(settings, fake_net, ytdlp_says_no_video):
    assert settings.fxtwitter_fallback is False
    with TestClient(create_app(settings, processor=FakeProcessor()), base_url="http://127.0.0.1") as c:
        cfg = c.get("/api/settings").json()
        assert cfg["fxtwitter_fallback"] is False and cfg["max_file_size_mb"] == 8192 and cfg["saved"] is False
        res = c.post("/api/analyse", json={"url": URL.canonical_url})
    assert res.status_code == 422 and res.json()["error"]["code"] == "no_video"
    assert fake_net["calls"] == []  # nothing was sent to the third party


def test_fallback_enabled_end_to_end(settings, fake_net, ytdlp_says_no_video):
    with TestClient(create_app(settings, processor=FakeProcessor()), base_url="http://127.0.0.1") as c:
        # Enabled from the GUI at runtime: no restart.
        assert c.patch("/api/settings", json={"fxtwitter_fallback": True, "max_file_size_mb": 2048}).status_code == 200
        a = c.post("/api/analyse", json={"url": URL.canonical_url}).json()
        assert a["platform"] == "x" and a["provider"] == "fxtwitter" and a["post"]["possibly_sensitive"] is False
        labels = {o["option_id"]: o for o in a["videos"][0]["options"]}
        assert labels["1080p"]["too_large"] and labels["best"]["label"] == "Best Available (720p)"
        job = c.post("/api/download", json={"analysis_id": a["analysis_id"], "option_id": "270p"}).json()
        done = wait_for_job(c, job["job_id"])
    assert done["state"] == "completed" and done["file"]["size_bytes"] == 3000
    assert not [p for p in settings.temp_dir.iterdir() if p.name.startswith("job-")]


# ---------------------------------------------------------- large files
def test_raised_size_limit_allows_largest_quality(fx, fake_net):
    options = build_options(fx.extract(URL).videos[0], max_size_bytes=4096 * 1024 * 1024)
    assert options[0].label == "Best Available (1080p)" and options[0].downloadable


def test_default_limit_blocks_3gb_option(fx, fake_net):
    options = build_options(fx.extract(URL).videos[0], max_size_bytes=2048 * 1024 * 1024)
    with pytest.raises(AppError) as exc:
        resolve_option(options, "1080p")
    assert exc.value.code == ErrorCode.FILE_TOO_LARGE


Usage = namedtuple("Usage", "total used free")


def test_insufficient_disk_space_refused_before_download(settings, monkeypatch):
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda p: Usage(10**12, 0, 100 * 1024 * 1024))
    app = create_app(settings, provider=FakeProvider(), processor=FakeProcessor())
    with TestClient(app, base_url="http://127.0.0.1") as c:
        a = c.post("/api/analyse", json={"url": "https://x.com/a/status/1"}).json()
        res = c.post("/api/download", json={"analysis_id": a["analysis_id"], "option_id": "720p"})
    assert res.status_code == 507 and res.json()["error"]["code"] == "insufficient_space"


def test_disk_space_needs_room_for_remux_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda p: Usage(10**12, 0, 2_500))
    storage.ensure_free_space(tmp_path, 1_000, 0)  # 2x fits
    with pytest.raises(AppError):
        storage.ensure_free_space(tmp_path, 1_300, 0)  # 2x does not
    with pytest.raises(AppError):
        storage.ensure_free_space(tmp_path, 1_000, 1_000)  # reserve counts


# ----------------------------------------------------------------- net layer
def test_redirect_validation():
    handler = _ValidatingRedirectHandler(lambda u: is_allowed_media_url(u, ("twimg.com",)))
    req = urllib.request.Request("https://video.twimg.com/a.mp4")
    for target in ("https://evil.example/a.mp4", "http://video.twimg.com/a.mp4", "https://169.254.169.254/",
                   "https://twimg.com.evil.example/a.mp4"):
        with pytest.raises(BlockedRedirect):
            handler.redirect_request(req, None, 302, "Found", {}, target)
    assert handler.redirect_request(req, None, 302, "Found", {}, "https://cdn.video.twimg.com/b.mp4") is not None


def test_open_url_refuses_disallowed_initial_url():
    with pytest.raises(BlockedRedirect):
        open_url("https://evil.example/", lambda u: False, timeout=1)


def test_api_host_check():
    assert fxmod._api_host_only("https://api.fxtwitter.com/2/status/1")
    for bad in ("http://api.fxtwitter.com/2/status/1", "https://api.fxtwitter.com.evil.example/",
                "https://u:p@api.fxtwitter.com/", "https://api.fxtwitter.com:8443/"):
        assert not fxmod._api_host_only(bad)
