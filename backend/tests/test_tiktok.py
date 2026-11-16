"""TikTok: URL validation, short links, provider normalisation, selection, download, errors (all mocked)."""

import copy
import io
from email.message import Message
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import resolve as resolve_mod
from app.config import Settings
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.net import BlockedRedirect
from app.providers.chain import ProviderChain
from app.providers.router import PlatformRouter
from app.providers.ytdlp_provider import YtDlpProvider, map_ytdlp_error
from app.resolve import resolve_tiktok_short_link
from app.selection import build_options
from app.validation import (
    PLATFORM_TIKTOK,
    is_allowed_tiktok_media_url,
    is_tiktok_redirect_hop,
    validate_post_url,
)

from .conftest import FakeProcessor, FakeProvider, wait_for_job

VIDEO_ID = "7100000000000003001"
TT_URL = f"https://www.tiktok.com/@example_creator1/video/{VIDEO_ID}"
EDGE = "https://v16-webapp-prime.tiktok.com/video/tos/x"


def tt_info():
    """Shape of yt-dlp's (processed) TikTok result, modelled on a real public video."""
    def fmt(fid, vcodec, w, h, tbr, size, host=EDGE, note=None):
        return {"format_id": fid, "url": f"{host}/{fid}.mp4", "ext": "mp4", "protocol": "https",
                "vcodec": vcodec, "acodec": "aac", "width": w, "height": h, "tbr": tbr, "filesize": size,
                "format_note": note}

    return copy.deepcopy({
        "id": VIDEO_ID,
        "title": "TikTok video #7100000000000003001",
        "description": "Science is cool #science",
        "uploader": "example_creator1",
        "uploader_id": "100000000000000001",
        "channel": "Hank Green",
        "duration": 21,
        "thumbnail": "https://p16-common-sign.tiktokcdn-eu.com/obj/cover.jpeg",
        "extractor": "TikTok",
        "extractor_key": "TikTok",
        "webpage_url": TT_URL,
        "formats": [
            {"format_id": "audio", "url": "https://v45.tiktokcdn-eu.com/a.mp3", "ext": "mp3", "protocol": "https",
             "vcodec": "none", "acodec": "mp3"},
            fmt("download", "h264", None, None, None, None, note="Download video, watermarked"),
            fmt("h264_540p_815015-0", "h264", 576, 1024, 815, 2183224),
            fmt("h264_540p_1895168-0", "h264", 576, 1024, 1895, 5076682),
            fmt("h264_540p_1895168-1", "h264", 576, 1024, 1895, 5076682,
                host="https://v19-webapp-prime.tiktok.com/video/tos/x"),
            fmt("bytevc1_540p_668450-0", "h265", 576, 1024, 668, 1790611),
            fmt("bytevc1_720p_1200000-0", "h265", 720, 1280, 1200, 3200000),
            fmt("h264_1080p_3000000-0", "h264", 1080, 1920, 3000, 8000000),
            fmt("bytevc2_1080p-0", "bytevc2", 1080, 1920, 900, 2000000, note="UNPLAYABLE"),
            fmt("evil_1080p", "h264", 1080, 1920, 99999, 1, host="https://cdn.evil.example/x"),
            fmt("www_1080p", "h264", 1080, 1920, 99998, 1, host="https://www.tiktok.com/x"),
        ],
    })


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL; records calls, never touches the network."""

    instances: list["FakeYDL"] = []

    def __init__(self, params, info, error=None):
        self.params, self.info, self.error = params, info, error
        self.extracted: list[str] = []
        FakeYDL.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False, process=True):
        self.extracted.append(url)
        if self.error:
            from yt_dlp.utils import DownloadError

            raise DownloadError(self.error)
        return copy.deepcopy(self.info)

    def urlopen(self, req):
        raise OSError("no network in tests")

    fail_403: list[str] = []  # format IDs whose next download attempt gets HTTP 403

    def process_ie_result(self, info, download=False):
        if not download:
            return info
        for fid in self.params["format"].split(","):
            if fid in FakeYDL.fail_403:
                FakeYDL.fail_403.remove(fid)
                from yt_dlp.utils import DownloadError

                raise DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")
        home = Path(self.params["paths"]["home"])
        downloads = []
        for fid in self.params["format"].split(","):
            fmt = next(f for f in info["formats"] if f["format_id"] == fid)
            path = home / f"{fid}.{fmt['ext']}"
            data = b"\0" * 4096
            for hook in self.params["progress_hooks"]:
                hook({"status": "downloading", "downloaded_bytes": 2048, "total_bytes": 4096, "info_dict": {"format_id": fid}})
            path.write_bytes(data)
            for hook in self.params["progress_hooks"]:
                hook({"status": "finished", "downloaded_bytes": 4096, "total_bytes": 4096, "info_dict": {"format_id": fid}})
            downloads.append({"format_id": fid, "filepath": str(path)})
        return {**info, "requested_downloads": downloads}


@pytest.fixture
def tt_provider(settings, monkeypatch):
    FakeYDL.instances.clear()
    FakeYDL.fail_403 = []
    provider = YtDlpProvider(settings, PLATFORM_TIKTOK)
    state = {"info": tt_info(), "error": None}
    monkeypatch.setattr(provider, "_ydl", lambda extra=None: FakeYDL({**provider._base_params(), **(extra or {})},
                                                                     state["info"], state["error"]))
    provider.state = state
    return provider


# ------------------------------------------------------------- validation
@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        (TT_URL, TT_URL),
        (f"https://tiktok.com/@example_creator1/video/{VIDEO_ID}", TT_URL),
        (f"tiktok.com/@example_creator1/video/{VIDEO_ID}?is_from_webapp=1&sender_device=pc", TT_URL),
        (f"https://WWW.TikTok.com/@example_creator1/video/{VIDEO_ID}/", TT_URL),
        (f"http://m.tiktok.com/@example_creator1/video/{VIDEO_ID}#x", TT_URL),
        (f"https://m.tiktok.com/v/{VIDEO_ID}.html", f"https://www.tiktok.com/@/video/{VIDEO_ID}"),
        (f"https://www.tiktok.com/@user.name_1/video/{VIDEO_ID}", f"https://www.tiktok.com/@user.name_1/video/{VIDEO_ID}"),
    ],
)
def test_valid_tiktok_urls(raw, canonical):
    v = validate_post_url(raw)
    assert v.platform == "tiktok" and v.canonical_url == canonical and v.post_id == VIDEO_ID and not v.short_link


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("https://vm.tiktok.com/ZMhvqjqjY/", "https://vm.tiktok.com/ZMhvqjqjY/"),
        ("vt.tiktok.com/ZSe4FqkKd", "https://vt.tiktok.com/ZSe4FqkKd/"),
        ("https://www.tiktok.com/t/ZTRC5xgJp/?k=1", "https://www.tiktok.com/t/ZTRC5xgJp/"),
    ],
)
def test_short_links_are_marked_for_resolution(raw, canonical):
    v = validate_post_url(raw)
    assert v.platform == "tiktok" and v.short_link and v.canonical_url == canonical and v.post_id == ""


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("https://www.tiktok.com/@user/photo/7100000000000003001", "slideshows"),
        ("https://www.tiktok.com/@user/live", "Live"),
        ("https://www.tiktok.com/@user", "profiles"),
        ("https://www.tiktok.com/music/song-123456789", "not a TikTok video"),
        ("https://www.tiktok.com/tag/cats", "not a TikTok video"),
        ("https://vm.tiktok.com/ZMh/extra/path", "not a TikTok video"),
        ("https://www.tiktok.com/@user/video/abc", "not a TikTok video"),
    ],
)
def test_unsupported_tiktok_urls(raw, fragment):
    with pytest.raises(AppError) as exc:
        validate_post_url(raw)
    assert exc.value.code == ErrorCode.UNSUPPORTED_URL and fragment in exc.value.message


@pytest.mark.parametrize(
    "raw",
    ["https://tiktok.com.evil.example/@u/video/7100000000000003001", "https://faketiktok.com/@u/video/7100000000000003001",
     "https://api.tiktok.com/@u/video/7100000000000003001", "https://u:p@www.tiktok.com/@u/video/7100000000000003001",
     "https://www.tiktok.com:8443/@u/video/7100000000000003001", "https://www.douyin.com/video/7100000000000003001"],
)
def test_lookalike_hosts_rejected(raw):
    with pytest.raises(AppError) as exc:
        validate_post_url(raw)
    assert exc.value.code in (ErrorCode.UNSUPPORTED_URL, ErrorCode.INVALID_URL)


def test_x_urls_unchanged():
    v = validate_post_url("https://twitter.com/example_user/status/123/video/2")
    assert v.platform == "x" and v.canonical_url == "https://x.com/example_user/status/123" and v.video_index == 2


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://v16-webapp-prime.tiktok.com/video/a.mp4", True),
        ("https://v19-webapp-prime.tiktok.com/video/a.mp4", True),
        ("https://v45.tiktokcdn-eu.com/a.mp3", True),
        ("https://p16-common-sign.tiktokcdn-eu.com/c.jpeg", True),
        ("https://v77.tiktokcdn.com/a.mp4", True),
        ("https://v1.tiktokcdn-us.com/a.mp4", True),
        ("https://www.tiktok.com/a.mp4", False),          # page host, not a CDN
        ("https://vm.tiktok.com/a.mp4", False),
        ("https://m.tiktok.com/a.mp4", False),
        ("https://video.tiktok.com.evil.example/a.mp4", False),
        ("https://tiktokcdn.com.evil.example/a.mp4", False),
        ("https://evil-tiktokcdn.com/a.mp4", False),
        ("http://v16-webapp-prime.tiktok.com/a.mp4", False),  # https only
        ("https://v16-webapp-prime.tiktok.com:8443/a.mp4", False),
        ("https://video.twimg.com/a.mp4", False),            # other platform's CDN
    ],
)
def test_tiktok_cdn_host_validation(url, ok):
    assert is_allowed_tiktok_media_url(url) is ok


# ------------------------------------------------------------ short links
class Resp(io.BytesIO):
    def __init__(self, status, location=None):
        super().__init__(b"")
        self.status = status
        self.headers = Message()
        if location:
            self.headers["Location"] = location

    def getcode(self):
        return self.status


@pytest.fixture
def hops(monkeypatch):
    state = {"map": {}, "calls": []}

    def fake_open(url, allowed, *, timeout, method="GET", headers=None, follow_redirects=True):
        assert method == "HEAD" and follow_redirects is False  # no page bodies, manual hops
        if not allowed(url):
            raise BlockedRedirect(ErrorCode.FORBIDDEN, "blocked")
        state["calls"].append(url)
        status, location = state["map"].get(url, (404, None))
        return Resp(status, location)

    monkeypatch.setattr(resolve_mod, "open_url", fake_open)
    return state


def test_short_link_resolves_to_canonical_video(hops):
    hops["map"]["https://vm.tiktok.com/ZMabc123/"] = (301, f"https://www.tiktok.com/@example_creator1/video/{VIDEO_ID}?_r=1&u_code=x")
    v = resolve_tiktok_short_link(validate_post_url("https://vm.tiktok.com/ZMabc123/"), timeout=5)
    assert v.canonical_url == TT_URL and v.post_id == VIDEO_ID and not v.short_link


def test_short_link_multi_hop_and_relative_location(hops):
    hops["map"]["https://vt.tiktok.com/ZSabc123/"] = (302, "https://www.tiktok.com/t/ZTdef456/")
    hops["map"]["https://www.tiktok.com/t/ZTdef456/"] = (302, f"/@example_creator1/video/{VIDEO_ID}")
    assert resolve_tiktok_short_link(validate_post_url("https://vt.tiktok.com/ZSabc123/"), 5).canonical_url == TT_URL


def test_expired_short_link_redirecting_home(hops):
    hops["map"]["https://vm.tiktok.com/ZMold000/"] = (302, "https://www.tiktok.com/?_r=1")
    with pytest.raises(AppError) as exc:
        resolve_tiktok_short_link(validate_post_url("https://vm.tiktok.com/ZMold000/"), 5)
    assert exc.value.code == ErrorCode.SHORT_LINK_EXPIRED and "expired" in exc.value.message


@pytest.mark.parametrize("target", ["https://evil.example/@u/video/1", "http://www.tiktok.com/@u/video/7100000000000003001",
                                    "https://169.254.169.254/latest", "https://www.tiktok.com.evil.example/x"])
def test_short_link_never_follows_foreign_redirects(hops, target):
    hops["map"]["https://vm.tiktok.com/ZMbad000/"] = (302, target)
    with pytest.raises(AppError) as exc:
        resolve_tiktok_short_link(validate_post_url("https://vm.tiktok.com/ZMbad000/"), 5)
    assert exc.value.code == ErrorCode.UNSUPPORTED_URL
    assert hops["calls"] == ["https://vm.tiktok.com/ZMbad000/"]  # the foreign hop was never requested


def test_short_link_redirect_loop(hops):
    hops["map"]["https://vm.tiktok.com/ZMloop00/"] = (302, "https://www.tiktok.com/t/ZTloop00/")
    hops["map"]["https://www.tiktok.com/t/ZTloop00/"] = (302, "https://vm.tiktok.com/ZMloop00/")
    with pytest.raises(AppError) as exc:
        resolve_tiktok_short_link(validate_post_url("https://vm.tiktok.com/ZMloop00/"), 5)
    assert "too many" in exc.value.message


def test_redirect_hop_predicate():
    assert is_tiktok_redirect_hop("https://www.tiktok.com/@u/video/1")
    assert is_tiktok_redirect_hop("https://vm.tiktok.com/x/")
    assert not is_tiktok_redirect_hop("https://v16-webapp-prime.tiktok.com/x")
    assert not is_tiktok_redirect_hop("http://www.tiktok.com/x")


# ------------------------------------------------------- provider (mocked)
def test_provider_loads_only_the_tiktok_extractor(tt_provider):
    params = tt_provider._base_params()
    assert params["allowed_extractors"] == ["tiktok"]
    assert params["cookiefile"] is None and params["cookiesfrombrowser"] is None and params["usenetrc"] is False


def test_metadata_normalisation(tt_provider):
    post = tt_provider.extract(validate_post_url(TT_URL))
    assert (post.post_id, post.author_handle, post.author_name) == (VIDEO_ID, "example_creator1", "Hank Green")
    assert post.text == "Science is cool #science" and post.url == TT_URL
    video = post.videos[0]
    assert video.duration_seconds == 21 and video.thumbnail_url.startswith("https://p16-common-sign.tiktokcdn-eu.com/")
    ids = {f.format_id for f in video.formats}
    assert "download" not in ids                 # watermarked variant dropped (clean streams exist)
    assert "bytevc2_1080p-0" not in ids          # yt-dlp marks these unplayable
    assert "evil_1080p" not in ids and "www_1080p" not in ids  # foreign / page hosts dropped
    by_id = {f.format_id: f for f in video.formats}
    assert by_id["bytevc1_540p_668450-0"].vcodec == "h265" and by_id["bytevc1_540p_668450-0"].mp4_compatible
    assert by_id["h264_540p_1895168-0"].filesize == 5076682 and by_id["h264_540p_1895168-0"].has_audio


def test_resolution_selection(tt_provider):
    options = build_options(tt_provider.extract(validate_post_url(TT_URL)).videos[0])
    assert [o.option_id for o in options] == ["best", "1080p", "720p", "576p"]
    best = options[0]
    assert best.label == "Best Available (1080p)" and best.video_format_id == "h264_1080p_3000000-0"
    assert not best.requires_merge and best.filesize == 8000000
    p576 = next(o for o in options if o.option_id == "576p")
    assert p576.video_format_id == "h264_540p_1895168-0"  # highest-bitrate H.264 at that size, not HEVC
    assert all(o.downloadable for o in options)


def test_watermarked_kept_only_when_it_is_the_sole_video(tt_provider):
    info = tt_info()
    info["formats"] = [f for f in info["formats"] if f["format_id"] in ("download", "audio")]
    info["formats"][1].update(width=576, height=1024)
    tt_provider.state["info"] = info
    video = tt_provider.extract(validate_post_url(TT_URL)).videos[0]
    assert [f.format_id for f in video.formats if f.has_video] == ["download"]


@pytest.mark.parametrize(
    ("formats_filter", "kind"),
    [
        (lambda f: f["vcodec"] == "none", "audio-only slideshow"),
        (lambda f: False, "no formats"),
        (lambda f: "evil" in f["url"], "only foreign hosts"),
    ],
)
def test_unsupported_content_is_reported(tt_provider, formats_filter, kind):
    info = tt_info()
    info["formats"] = [f for f in info["formats"] if formats_filter(f)]
    tt_provider.state["info"] = info
    with pytest.raises(AppError) as exc:
        tt_provider.extract(validate_post_url(TT_URL))
    expected = ErrorCode.MEDIA_HOST_BLOCKED if kind == "only foreign hosts" else ErrorCode.NO_VIDEO
    assert exc.value.code == expected, kind


def test_external_link_result_rejected(tt_provider):
    tt_provider.state["info"] = {"_type": "url", "url": "https://example.com/"}
    with pytest.raises(AppError) as exc:
        tt_provider.extract(validate_post_url(TT_URL))
    assert exc.value.code == ErrorCode.NO_VIDEO and "TikTok" in exc.value.message


@pytest.mark.parametrize(
    ("message", "code", "fragment"),
    [
        ("ERROR: [TikTok] 1: Your IP address is blocked from accessing this post", ErrorCode.REGION_RESTRICTED, "region"),
        ("ERROR: [TikTok] 1: Unexpected response from webpage request; please report this issue", ErrorCode.EXTRACTION_FAILED, "curl-cffi"),
        ("ERROR: [TikTok] 1: This post may not be comfortable for some audiences. Log in for access", ErrorCode.LOGIN_REQUIRED, "public videos"),
        ("ERROR: [TikTok] 1: This video is private", ErrorCode.LOGIN_REQUIRED, "public videos"),
        ("ERROR: [TikTok] 1: Video not available, status code 10204", ErrorCode.NOT_FOUND, "could not be found"),
        ("ERROR: [TikTok] 1: HTTP Error 429: Too Many Requests", ErrorCode.RATE_LIMITED, "TikTok is rate-limiting"),
        ("ERROR: [TikTok] 1: Read timed out", ErrorCode.TIMEOUT, "TikTok timed out"),
        ("ERROR: [TikTok] 1: something odd", ErrorCode.EXTRACTION_FAILED, "something odd"),
    ],
)
def test_tiktok_specific_failures(message, code, fragment):
    from yt_dlp.utils import DownloadError

    err = map_ytdlp_error(DownloadError(message), platform=PLATFORM_TIKTOK)
    assert err.code == code and fragment in err.message
    assert "X " not in err.message and "X." not in err.message  # no X wording for TikTok errors


def test_provider_failure_surfaces_through_api(settings, tt_provider):
    tt_provider.state["error"] = "ERROR: [TikTok] 1: Your IP address is blocked from accessing this post"
    router = PlatformRouter({"x": FakeProvider(), "tiktok": tt_provider})
    with TestClient(create_app(settings, provider=router, processor=FakeProcessor()), base_url="http://127.0.0.1") as c:
        res = c.post("/api/analyse", json={"url": TT_URL})
    err = res.json()["error"]
    assert res.status_code == 451 and err["code"] == "region_restricted" and err["retryable"] is False and err["action"]


# --------------------------------------------------- end-to-end (mocked)
def test_tiktok_mp4_download_end_to_end(settings, tt_provider):
    router = PlatformRouter({"x": FakeProvider(), "tiktok": tt_provider})
    with TestClient(create_app(settings, provider=router, processor=FakeProcessor()), base_url="http://127.0.0.1") as c:
        a = c.post("/api/analyse", json={"url": f"tiktok.com/@example_creator1/video/{VIDEO_ID}?lang=en"}).json()
        assert a["platform"] == "tiktok" and a["provider"] == "yt-dlp"
        assert a["post"]["url"] == TT_URL and a["post"]["author_handle"] == "example_creator1"
        job = c.post("/api/download", json={"analysis_id": a["analysis_id"], "option_id": "best"}).json()
        done = wait_for_job(c, job["job_id"])
        assert done["state"] == "completed", done
        assert done["file"]["filename"] == "example_creator1 - Science is cool #science [7100000000000003001] 1080p.mp4"
        assert c.get(done["file"]["download_url"]).status_code == 200
    # yt-dlp was asked for exactly the chosen format, on the canonical URL only
    dl = FakeYDL.instances[-1]
    assert dl.params["format"] == "h264_1080p_3000000-0" and dl.extracted == [TT_URL]


def test_short_link_analysis_stores_canonical_url(settings, tt_provider, monkeypatch):
    def fake_resolve(url, timeout):
        return validate_post_url(TT_URL)

    monkeypatch.setattr(resolve_mod, "resolve_tiktok_short_link", fake_resolve)
    router = PlatformRouter({"x": FakeProvider(), "tiktok": tt_provider})
    with TestClient(create_app(settings, provider=router, processor=FakeProcessor()), base_url="http://127.0.0.1") as c:
        a = c.post("/api/analyse", json={"url": "https://vm.tiktok.com/ZMabc123/"}).json()
        assert a["platform"] == "tiktok" and a["post"]["url"] == TT_URL
        stored = c.app.state.services.analyses.get(a["analysis_id"])
        assert stored.url.canonical_url == TT_URL and not stored.url.short_link


def test_fxtwitter_is_never_used_for_tiktok(settings, tt_provider):
    from dataclasses import replace

    tt_provider.state["info"] = {"_type": "url", "url": "https://example.com/"}  # TikTok: no video
    fx = FakeProvider()
    fx.name = "fxtwitter"
    fx.extract = lambda url: pytest.fail("FxTwitter must never be contacted for TikTok")
    x_chain = ProviderChain(FakeProvider(), fx, enabled=lambda: True)
    router = PlatformRouter({"x": x_chain, "tiktok": tt_provider})
    app = create_app(replace(settings, fxtwitter_fallback=True), provider=router, processor=FakeProcessor())
    with TestClient(app, base_url="http://127.0.0.1") as c:
        res = c.post("/api/analyse", json={"url": TT_URL})
    assert res.status_code == 422 and res.json()["error"]["code"] == "no_video"


def test_default_wiring_routes_platforms(settings):
    from app.main import build_default_provider, build_settings_store

    from app.tiktok_account import TikTokAccountStore

    router = build_default_provider(settings, build_settings_store(settings), TikTokAccountStore(settings.config_dir))
    assert isinstance(router, PlatformRouter)
    assert isinstance(router.providers["x"], ProviderChain)
    assert router.providers["x"].fallback.name == "fxtwitter"
    tiktok = router.providers["tiktok"]
    assert isinstance(tiktok, YtDlpProvider) and tiktok.spec.extractor == "tiktok"
    assert router.provider_for("fxtwitter", "tiktok") is tiktok  # no fallback path exists for TikTok


def test_mirrored_duplicate_format_ids_are_stable_between_analysis_and_download(settings, tt_provider):
    """Real TikTok responses repeat IDs for CDN mirrors (unprocessed); MediaLab must disambiguate
    exactly like yt-dlp so the ID chosen at analysis is found again at download time."""
    info = tt_info()
    for f in info["formats"]:
        f["format_id"] = f["format_id"].rsplit("-", 1)[0] if f["format_id"][-2:] in ("-0", "-1") else f["format_id"]
    tt_provider.state["info"] = info
    router = PlatformRouter({"x": FakeProvider(), "tiktok": tt_provider})
    with TestClient(create_app(settings, provider=router, processor=FakeProcessor()), base_url="http://127.0.0.1") as c:
        a = c.post("/api/analyse", json={"url": TT_URL}).json()
        ids = {f["format_id"] for f in a["videos"][0]["formats"]}
        assert {"h264_540p_1895168-0", "h264_540p_1895168-1"} <= ids
        p576 = next(o for o in a["videos"][0]["options"] if o["option_id"] == "576p")
        job = c.post("/api/download", json={"analysis_id": a["analysis_id"], "option_id": "576p"}).json()
        assert wait_for_job(c, job["job_id"])["state"] == "completed"
    assert FakeYDL.instances[-1].params["format"] == p576["video_format_id"]


def test_intermittent_cdn_403_retries_on_the_mirror(tt_provider, tmp_path):
    FakeYDL.fail_403 = ["h264_540p_1895168-0"]
    progress = []
    out = tt_provider.download(validate_post_url(TT_URL), 1, ["h264_540p_1895168-0"], tmp_path, progress.append)
    assert set(out) == {"h264_540p_1895168-0"} and out["h264_540p_1895168-0"].is_file()
    assert FakeYDL.instances[-1].params["format"] == "h264_540p_1895168-1"  # the other mirror
    assert out["h264_540p_1895168-0"].parent == tmp_path / "attempt-1"  # clean folder per attempt


def test_persistent_403_reports_refusal_not_network_error(tt_provider, tmp_path):
    FakeYDL.fail_403 = ["h264_540p_1895168-0", "h264_540p_1895168-1", "h264_540p_1895168-0"]
    with pytest.raises(AppError) as exc:
        tt_provider.download(validate_post_url(TT_URL), 1, ["h264_540p_1895168-0"], tmp_path, lambda u: None)
    assert exc.value.code == ErrorCode.CDN_URL_EXPIRED and "HTTP 403" in exc.value.message and exc.value.retryable
    assert len([i for i in FakeYDL.instances if "format" in i.params]) == 3  # bounded: 3 attempts


def test_non_403_errors_are_not_retried(tt_provider, tmp_path):
    with pytest.raises(AppError) as exc:
        tt_provider.download(validate_post_url(TT_URL), 1, ["no-such-format"], tmp_path, lambda u: None)
    assert exc.value.code == ErrorCode.FORMAT_UNAVAILABLE
    assert len([i for i in FakeYDL.instances if "format" in i.params]) == 1


# ------------------------------------- MED-1: TikTok's separate "music" track
def test_tiktok_videos_never_pair_the_separate_music_track(tt_provider):
    """On ordinary TikTok videos the item's music can be a licensed song or differ from the video's
    audio (measured), so it must never be used as the soundtrack of a video-only stream."""
    info = tt_info()
    info["formats"].append({"format_id": "bytevc1_1080p_9-0", "url": f"{EDGE}/vo.mp4", "ext": "mp4",
                            "protocol": "https", "vcodec": "h265", "acodec": "none", "width": 1080,
                            "height": 1920, "tbr": 5000, "filesize": 9000000})
    tt_provider.state["info"] = info
    post = tt_provider.extract(validate_post_url(TT_URL))
    ids = {f.format_id for f in post.videos[0].formats}
    assert "audio" not in ids
    options = build_options(post.videos[0])
    video_only = next(o for o in options if o.video_format_id == "bytevc1_1080p_9-0" and not o.is_best)
    assert video_only.has_audio is False and video_only.audio_format_id is None
    assert video_only.fallback_audio_format_id is None and "No audio track" in video_only.note
    assert options[0].is_best and options[0].has_audio is not False  # Best keeps a resolution with audio
