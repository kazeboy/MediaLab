"""TikTok Short Drama: account linking, episode extraction, errors, download (all mocked).

The fake pages reproduce the structure TikTok returned on 2026-11-12 for real
episodes (logged out: locked preview without a stream; signed in: the same
item with progressive MP4 ``bitrateInfo``). yt-dlp's real TikTok parser and
format processing run on them; only the network is replaced.
"""

from __future__ import annotations

import copy
import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from yt_dlp import YoutubeDL

from app import resolve as resolve_mod
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.providers.router import PlatformRouter
from app.providers.tiktok_shortdrama import TikTokShortDramaProvider
from app.providers.ytdlp_provider import YtDlpProvider
from app.tiktok_account import COOKIE_FILENAME, TikTokAccountStore, parse_tiktok_cookies
from app.validation import PLATFORM_SHORTDRAMA, PLATFORM_TIKTOK, validate_post_url

from .conftest import FakeProcessor, FakeProvider, wait_for_job

SERIES_A = "7100000000000000101"  # "Harbor & Crown Example 2" (52 episodes)
SERIES_B = "7100000000000000202"
EP2 = "7100000000000001002"  # what https://vm.tiktok.com/ZNExample7/ resolves to
EP1 = "7100000000000001001"
EP2_LINKED = "7100000000000001902"  # TikTok's internal episode record (status 203008)
OTHER_SERIES_EP = "7100000000000002001"
ORDINARY = "7100000000000003001"
SHORT = "https://vm.tiktok.com/ZNExample7/"

EDGE16 = "https://v16-webapp-prime.tiktok.com/video/tos/alisg/tos-example/path/"
EDGE19 = "https://v19-webapp-prime.tiktok.com/video/tos/alisg/tos-example/path/"

SESSION_COOKIES = (
    "# Netscape HTTP Cookie File\n"
    ".tiktok.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\tSECRET-SESSION\n"
    "#HttpOnly_.tiktok.com\tTRUE\t/\tTRUE\t1999999999\tsid_tt\tSECRET-SID\n"
    "www.tiktok.com\tFALSE\t/\tTRUE\t1999999999\ttt_csrf_token\tabc\n"
    ".google.com\tTRUE\t/\tTRUE\t1999999999\tSID\tGOOGLE-SECRET\n"
    ".example.com\tTRUE\t/\tFALSE\t0\tother\tvalue\n"
)


def url_for(item_id: str, user: str = "example.studio.a") -> str:
    return f"https://www.tiktok.com/@{user}/video/{item_id}"


def bitrate(gear, codec, key, w, h, size):
    return {"GearName": gear, "CodecType": codec, "PlayAddr": {
        "Width": w, "Height": h, "DataSize": size, "UrlKey": key,
        "UrlList": [EDGE16 + key, EDGE19 + key, "https://www.tiktok.com/aweme/v1/play/?file_id=x"]}}


def item(item_id, *, episode, series=SERIES_A, title="Harbor & Crown Example 2", count=52, stream=True,
         drama=True, user="example.studio.a"):
    video = {"id": item_id, "duration": 115, "width": 0, "height": 0, "playAddr": "", "downloadAddr": "",
             "cover": "https://p16-common-sign.tiktokcdn-eu.com/tos/cover.image"}
    if stream:
        video.update({"width": 576, "height": 1024, "playAddr": EDGE16 + "play", "bitrateInfo": [
            bitrate("normal_540_0", "h264", "v12025gd_h264_540p_1043300", 576, 1024, 15021086),
            bitrate("adapt_lower_720_1", "h265_hvc1", "v12025gd_bytevc1_720p_610784", 720, 1280, 8779825),
            bitrate("adapt_540_1", "h265_hvc1", "v12025gd_bytevc1_540p_470540", 576, 1024, 6763533),
        ]})
    data = {"id": item_id, "desc": f"{title} EP{episode}", "createTime": 1793768631, "video": video,
            "author": {"uniqueId": user, "nickname": "Example Studio-Short Dramas", "id": "7100000000000009001"},
            "stats": {}, "music": {}}
    if drama:
        data["dramaInfo"] = {"dramaID": series, "dramaName": title, "numVideos": count, "isLimitedFree": True,
                             "DramaVideoData": {"EpisodeNumber": episode, "IsPreview": True, "PreviewType": 4,
                                                "LinkedEpisodeID": EP2_LINKED}}
    return data


class Pages:
    """What TikTok answers per item ID, depending on whether session cookies were sent."""

    def __init__(self):
        self.signed_in: dict[str, tuple] = {}
        self.anonymous: dict[str, tuple] = {}
        self.requests: list[tuple[str, bool]] = []
        self.fail_403: list[str] = []
        self.errors: list[Exception] = []

    def add(self, item_id, *, anon, signed=None):
        self.anonymous[item_id] = anon
        self.signed_in[item_id] = signed if signed is not None else anon


def make_ydl_class(pages: Pages):
    class FakeTikTokYDL(YoutubeDL):
        def get_info_extractor(self, ie_key):
            ie = super().get_info_extractor(ie_key)

            def web(url, video_id, fatal=True):
                signed = any(c.name == "sessionid" for c in self.cookiejar)
                pages.requests.append((video_id, signed))
                if pages.errors:
                    raise pages.errors.pop(0)
                table = pages.signed_in if signed else pages.anonymous
                data, status = table.get(video_id, ({}, 10204))
                return copy.deepcopy(data), status

            ie._extract_web_data_and_status = web
            return ie

        def urlopen(self, req):
            raise OSError("no network in tests")

        def process_ie_result(self, info, download=True, extra_info=None):
            if not download:
                return super().process_ie_result(info, download=False)
            fids = self.params["format"].split(",")
            for fid in fids:
                if fid in pages.fail_403:
                    pages.fail_403.remove(fid)
                    from yt_dlp.utils import DownloadError

                    raise DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")
            home = Path(self.params["paths"]["home"])
            downloads = []
            for fid in fids:
                assert any(f["format_id"] == fid for f in info["formats"]), fid
                path = home / f"{fid}.mp4"
                path.write_bytes(b"\0" * 4096)
                for hook in self.params["progress_hooks"]:
                    hook({"status": "finished", "downloaded_bytes": 4096, "total_bytes": 4096,
                          "info_dict": {"format_id": fid}})
                downloads.append({"format_id": fid, "filepath": str(path)})
            return {**info, "requested_downloads": downloads}

    return FakeTikTokYDL


@pytest.fixture
def pages():
    p = Pages()
    # Logged out: locked preview without a stream. Signed in: the full episode.
    p.add(EP2, anon=(item(EP2, episode=2, stream=False), 0), signed=(item(EP2, episode=2), 0))
    p.add(EP1, anon=(item(EP1, episode=1, stream=False), 0), signed=(item(EP1, episode=1), 0))
    p.add(OTHER_SERIES_EP, anon=(item(OTHER_SERIES_EP, episode=8, series=SERIES_B, title="Another Series",
                                      count=60, stream=False, user="muffindrama_us"), 0),
          signed=(item(OTHER_SERIES_EP, episode=8, series=SERIES_B, title="Another Series", count=60,
                       user="muffindrama_us"), 0))
    p.add(EP2_LINKED, anon=({}, 203008))
    p.add(ORDINARY, anon=(item(ORDINARY, episode=0, drama=False), 0))
    return p


@pytest.fixture
def account(settings):
    return TikTokAccountStore(settings.config_dir)


@pytest.fixture
def sd_provider(settings, account, pages, monkeypatch):
    provider = TikTokShortDramaProvider(settings, account)
    cls = make_ydl_class(pages)
    monkeypatch.setattr("yt_dlp.YoutubeDL", cls)  # used by YtDlpProvider._ydl and the probe
    provider.retry_sleep = lambda s: None
    return provider


def sd_url(item_id, user="example.studio.a"):
    return validate_post_url(url_for(item_id, user), PLATFORM_SHORTDRAMA)


@pytest.fixture
def app_client(settings, sd_provider, account, monkeypatch):
    tiktok = YtDlpProvider(settings, PLATFORM_TIKTOK)
    tiktok.drama_probe = sd_provider.is_drama_episode
    tiktok.retry_sleep = lambda s: None
    router = PlatformRouter({"x": FakeProvider(), "tiktok": tiktok, PLATFORM_SHORTDRAMA: sd_provider})
    monkeypatch.setattr(resolve_mod, "resolve_tiktok_short_link",
                        lambda url, timeout: validate_post_url(url_for(EP2)))
    app = create_app(settings, provider=router, processor=FakeProcessor())
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def link(account):
    account.save(SESSION_COOKIES)


# ------------------------------------------------------------- account store
def test_cookie_parser_keeps_only_tiktok_cookies():
    rows = parse_tiktok_cookies(SESSION_COOKIES)
    assert {r[5] for r in rows} == {"sessionid", "sid_tt", "tt_csrf_token"}
    assert not any("GOOGLE" in v for r in rows for v in r)
    assert rows[1][0] == "#HttpOnly_.tiktok.com"


@pytest.mark.parametrize(("text", "fragment"), [
    ("", "empty"),
    ("just some text\nnot cookies", "isn't a cookies.txt"),
    (".tiktok.com\tTRUE\t/\tTRUE\t1999999999\tmsToken\tx\n", "No signed-in TikTok session"),
    (".google.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\tx\n", "No signed-in TikTok session"),
    ("x" * 1_000_001, "too large"),
])
def test_cookie_parser_rejects_unusable_files(text, fragment):
    with pytest.raises(AppError) as exc:
        parse_tiktok_cookies(text)
    assert exc.value.code == ErrorCode.VALIDATION_ERROR and fragment in exc.value.message


def test_account_file_is_private_and_filtered(account, settings):
    status = account.save(SESSION_COOKIES)
    path = settings.config_dir / COOKIE_FILENAME
    assert status.linked and status.cookie_count == 3 and not status.expired
    assert status.session_expires_at == 1999999999
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert "GOOGLE-SECRET" not in path.read_text() and "SECRET-SESSION" in path.read_text()
    assert not account.remove().linked and not path.exists()


def test_expired_session_is_reported(account):
    account.save(SESSION_COOKIES.replace("1999999999", "1000000000"))
    assert account.status().expired


def test_account_api_never_returns_cookie_values(settings, app_client):
    assert app_client.get("/api/tiktok-account").json()["linked"] is False
    res = app_client.put("/api/tiktok-account", json={"cookies_txt": SESSION_COOKIES})
    assert res.status_code == 200 and res.json()["linked"] is True and res.json()["cookie_count"] == 3
    for body in (res.text, app_client.get("/api/tiktok-account").text):
        assert "SECRET" not in body and "sessionid" not in body and str(settings.config_dir) not in body
    bad = app_client.put("/api/tiktok-account", json={"cookies_txt": "nope"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"
    assert app_client.get("/api/tiktok-account").json()["linked"] is True  # a bad upload keeps the old one
    assert app_client.delete("/api/tiktok-account").json()["linked"] is False


def test_account_api_rejects_cross_site_and_extra_fields(app_client):
    res = app_client.put("/api/tiktok-account", json={"cookies_txt": SESSION_COOKIES},
                         headers={"Origin": "https://evil.example"})
    assert res.status_code == 403
    res = app_client.put("/api/tiktok-account", json={"cookies_txt": SESSION_COOKIES, "path": "/etc/passwd"})
    assert res.status_code == 422
    assert app_client.get("/api/tiktok-account").json()["linked"] is False


# ---------------------------------------------------------------- analysis
def test_supplied_short_link_anonymous_reports_login_requirement(app_client, pages):
    res = app_client.post("/api/analyse", json={"url": SHORT, "platform": PLATFORM_SHORTDRAMA})
    assert res.status_code == 403
    err = res.json()["error"]
    assert err["code"] == "login_required" and err["retryable"] is False
    assert "signed-in viewers" in err["message"] and "Settings" in err["action"]
    assert err["details"] == {"platform": PLATFORM_SHORTDRAMA, "series_id": SERIES_A, "episode": 2, "preview_type": 4}
    assert pages.requests == [(EP2, False)]


def test_supplied_short_link_with_account_lists_episode_formats(app_client, account, pages):
    link(account)
    res = app_client.post("/api/analyse", json={"url": SHORT, "platform": PLATFORM_SHORTDRAMA})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["platform"] == PLATFORM_SHORTDRAMA and body["provider"] == "tiktok-shortdrama"
    assert body["post"]["drama"] == {"series_id": SERIES_A, "series_title": "Harbor & Crown Example 2",
                                     "episode": 2, "episode_count": 52, "account_used": True}
    assert body["post"]["url"] == url_for(EP2)
    video = body["videos"][0]
    assert video["title"] == "Harbor & Crown Example 2 EP2"
    best = video["options"][0]
    assert best["is_best"] and best["height"] == 1280 and best["width"] == 720
    heights = {o["height"] for o in video["options"]}
    assert heights <= {1280, 1024}  # nothing above the source: no upscaling
    hosts = {f["format_id"] for f in video["formats"]}
    assert not any("play/?" in h for h in hosts)
    assert pages.requests == [(EP2, True)]


def test_another_episode_of_the_same_series(sd_provider, account):
    link(account)
    post = sd_provider.extract(sd_url(EP1))
    assert post.drama.episode == 1 and post.drama.series_id == SERIES_A
    assert post.videos[0].title.endswith("EP1")


def test_episode_of_a_different_series(sd_provider, account):
    link(account)
    post = sd_provider.extract(sd_url(OTHER_SERIES_EP, "muffindrama_us"))
    assert post.drama.series_id == SERIES_B and post.drama.series_title == "Another Series"
    assert post.drama.episode == 8 and post.drama.episode_count == 60
    assert post.author_handle == "muffindrama_us"


def test_signed_in_but_still_locked_is_account_access_unavailable(sd_provider, account, pages):
    link(account)
    pages.signed_in[EP2] = (item(EP2, episode=2, stream=False), 0)  # e.g. episode needs unlocking
    with pytest.raises(AppError) as exc:
        sd_provider.extract(sd_url(EP2))
    assert exc.value.code == ErrorCode.ACCOUNT_ACCESS_UNAVAILABLE
    assert "linked account" in exc.value.message and exc.value.status_code == 403


def test_internal_episode_record_is_not_found_not_login(sd_provider, account):
    link(account)
    with pytest.raises(AppError) as exc:
        sd_provider.extract(sd_url(EP2_LINKED))
    assert exc.value.code == ErrorCode.NOT_FOUND and "203008" in exc.value.message


def test_missing_metadata_is_extraction_failed(sd_provider, pages):
    pages.add("7000000000000000001", anon=({}, 0))
    with pytest.raises(AppError) as exc:
        sd_provider.extract(sd_url("7000000000000000001"))
    assert exc.value.code == ErrorCode.EXTRACTION_FAILED and exc.value.code != ErrorCode.LOGIN_REQUIRED


def test_deleted_item(sd_provider):
    with pytest.raises(AppError) as exc:
        sd_provider.extract(sd_url("7000000000000000002"))  # unknown -> status 10204
    assert exc.value.code == ErrorCode.NOT_FOUND


def test_network_failure_is_retried_then_reported(sd_provider, pages, account):
    from yt_dlp.utils import ExtractorError

    link(account)
    pages.errors = [ExtractorError("Unable to download webpage: <urlopen error timed out>")] * 3
    with pytest.raises(AppError) as exc:
        sd_provider.extract(sd_url(EP2))
    assert exc.value.code == ErrorCode.TIMEOUT
    assert len(pages.requests) == 3


def test_transient_failure_then_success(sd_provider, pages, account):
    from yt_dlp.utils import ExtractorError

    link(account)
    pages.errors = [ExtractorError("Unable to download webpage: Connection reset by peer")]
    assert sd_provider.extract(sd_url(EP2)).drama.episode == 2


def test_ordinary_video_in_short_drama_tab_suggests_tiktok_tab(app_client):
    res = app_client.post("/api/analyse", json={"url": url_for(ORDINARY), "platform": PLATFORM_SHORTDRAMA})
    err = res.json()["error"]
    assert res.status_code == 400 and err["code"] == "wrong_platform"
    assert err["details"]["detected_platform"] == PLATFORM_TIKTOK


def test_episode_in_tiktok_videos_tab_suggests_short_drama_tab(app_client, pages, account):
    link(account)  # the TikTok Videos tab must stay anonymous even when an account is linked
    res = app_client.post("/api/analyse", json={"url": url_for(EP2), "platform": PLATFORM_TIKTOK})
    err = res.json()["error"]
    assert err["code"] == "wrong_platform" and err["details"]["detected_platform"] == PLATFORM_SHORTDRAMA
    assert all(signed is False for _, signed in pages.requests)


def test_account_cookies_are_never_used_by_the_tiktok_videos_provider(settings, account):
    link(account)
    plain = YtDlpProvider(settings, PLATFORM_TIKTOK)
    params = plain._base_params()
    assert params["cookiefile"] is None and params["cookiesfrombrowser"] is None


def test_cookie_file_is_loaded_in_memory_only(sd_provider, account, settings):
    link(account)
    before = (settings.config_dir / COOKIE_FILENAME).read_text()
    ydl = sd_provider._ydl()
    assert ydl.params["cookiefile"] is None
    assert any(c.name == "sessionid" for c in ydl.cookiejar)
    ydl.close()
    assert (settings.config_dir / COOKIE_FILENAME).read_text() == before


# ---------------------------------------------------------------- download
def test_full_download_flow_with_cleanup(app_client, account, settings):
    link(account)
    analysed = app_client.post("/api/analyse", json={"url": SHORT, "platform": PLATFORM_SHORTDRAMA}).json()
    best = analysed["videos"][0]["options"][0]
    job = app_client.post("/api/download", json={"analysis_id": analysed["analysis_id"], "video_index": 1,
                                                 "option_id": best["option_id"]}).json()
    done = wait_for_job(app_client, job["job_id"])
    assert done["state"] == "completed", done
    assert done["file"]["filename"] == "Harbor & Crown Example 2 - E02.mp4"
    assert not any(p.name.startswith("job-") for p in settings.temp_dir.iterdir())  # job folder removed
    res = app_client.get(done["file"]["download_url"])
    assert res.status_code == 200 and len(res.content) > 0
    assert list((settings.temp_dir / "ready").iterdir()) == []  # deleted after delivery


def test_download_retries_cdn_403_with_mirror(sd_provider, account, pages, tmp_path):
    link(account)
    post = sd_provider.extract(sd_url(EP2))
    fid = next(f.format_id for f in post.videos[0].formats if f.height == 1280)
    assert fid.endswith("-0")
    pages.fail_403 = [fid]
    notes = []
    out = sd_provider.download(sd_url(EP2), 1, [fid], tmp_path, lambda u: notes.append(u.note))
    assert out[fid].is_file() and out[fid].name.startswith(fid[:-2] + "-1")
    assert any(n and "expired" in n for n in notes)


def test_download_with_session_lost_reports_access(sd_provider, account, pages, tmp_path):
    link(account)
    post = sd_provider.extract(sd_url(EP2))
    fid = post.videos[0].formats[0].format_id
    account.remove()
    with pytest.raises(AppError) as exc:
        sd_provider.download(sd_url(EP2), 1, [fid], tmp_path, lambda u: None)
    assert exc.value.code == ErrorCode.LOGIN_REQUIRED


# ===================================================================== v1.4
import time as _time

from app import batches as batches_mod
from app.providers.ytdlp_provider import equivalent_format_id
from app.selection import choose_option
from app.storage import episode_filename

EP3, EP4_LOCKED, EP5 = "7100000000000001003", "7100000000000001004", "7100000000000001005"
SERIES_ORDER = [EP3, EP1, EP5, EP2, EP4_LOCKED]  # deliberately unordered, as a test of sorting


@pytest.fixture
def series(pages, sd_provider, monkeypatch):
    """Fake /api/drama/detail and /api/drama/episode/item_list built from the same item data."""
    for item_id, ep in ((EP3, 3), (EP5, 5)):
        pages.add(item_id, anon=(item(item_id, episode=ep, stream=False), 0), signed=(item(item_id, episode=ep), 0))
    pages.add(EP4_LOCKED, anon=(item(EP4_LOCKED, episode=4, stream=False), 0),
              signed=(item(EP4_LOCKED, episode=4, stream=False), 0))  # no stream even signed in
    state = {"status": 0, "calls": [], "page_size": 2}
    listed = {"signed": {i: copy.deepcopy(pages.signed_in[i]) for i in SERIES_ORDER},
              "anon": {i: copy.deepcopy(pages.anonymous[i]) for i in SERIES_ORDER}}

    def fake_api(ydl, path, params):
        state["calls"].append((path, dict(params)))
        signed = any(c.name == "sessionid" for c in ydl.cookiejar)
        if state["status"]:
            raise AppError(ErrorCode.SERIES_METADATA_UNAVAILABLE, f"TikTok didn't return this series (status {state['status']}).")
        assert params["dramaID"] == SERIES_A
        if path == "drama/detail":
            return {"statusCode": 0, "dramaInfo": {"dramaID": SERIES_A, "dramaName": "Harbor & Crown Example 2",
                                                   "numVideos": 5, "author": {"uniqueId": "example.studio.a"},
                                                   "cover": {"UrlList": ["https://evil.example/c.jpg",
                                                                         "https://p16-common-sign.tiktokcdn-eu.com/c.jpg"]}}}
        table = listed["signed"] if signed else listed["anon"]
        cursor, size = int(params["cursor"]), state["page_size"]
        ids = SERIES_ORDER[cursor:cursor + size]
        return {"statusCode": 0, "itemList": [table[i][0] for i in ids], "cursor": str(cursor + len(ids)),
                "hasMore": cursor + len(ids) < len(SERIES_ORDER), "totalEpisodeCount": 5}

    monkeypatch.setattr(sd_provider, "_api", fake_api)
    monkeypatch.setattr(batches_mod, "TICK_SECONDS", 0.01)
    return state


def wait_batch(client, batch_id, until, timeout=10):
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        body = client.get(f"/api/shortdrama/batches/{batch_id}").json()
        if until(body):
            return body
        _time.sleep(0.02)
    raise AssertionError(f"batch never reached the condition: {body}")


def save_ready(client, body):
    for ep in body["episodes"]:
        if ep["state"] == "ready":
            res = client.get(ep["download_url"])
            assert res.status_code == 200, res.text


def count(body, state):
    return body["counts"][state]


# ------------------------------------------------------------------ series
def test_series_lists_episodes_in_order_with_availability(app_client, account, series):
    anon = app_client.get(f"/api/shortdrama/series/{SERIES_A}").json()
    assert [e["number"] for e in anon["episodes"]] == [1, 2, 3, 4, 5]
    assert {e["availability"] for e in anon["episodes"]} == {"login_required"} and not anon["account_used"]
    link(account)
    body = app_client.get(f"/api/shortdrama/series/{SERIES_A}").json()
    assert body["title"] == "Harbor & Crown Example 2" and body["episode_count"] == 5 and body["account_used"]
    assert body["cover_url"] == "https://p16-common-sign.tiktokcdn-eu.com/c.jpg"  # foreign host dropped
    assert [(e["number"], e["item_id"], e["availability"]) for e in body["episodes"]] == [
        (1, EP1, "available"), (2, EP2, "available"), (3, EP3, "available"), (4, EP4_LOCKED, "locked"),
        (5, EP5, "available")]
    assert body["episodes"][1]["title"] == "Harbor & Crown Example 2 EP2"
    assert body["episodes"][1]["duration_seconds"] == 115
    pages_requested = [p for p, q in series["calls"] if p == "drama/episode/item_list"]
    assert len(pages_requested) >= 3  # paginated (page size 2)


def test_series_is_cached_briefly(app_client, account, series):
    link(account)
    app_client.get(f"/api/shortdrama/series/{SERIES_A}")
    before = len(series["calls"])
    app_client.get(f"/api/shortdrama/series/{SERIES_A}")
    assert len(series["calls"]) == before


@pytest.mark.parametrize("bad", ["abc", "123", "1" * 30])
def test_series_rejects_bad_ids(app_client, bad):
    res = app_client.get(f"/api/shortdrama/series/{bad}")
    assert res.status_code == 400 and res.json()["error"]["code"] == "invalid_url"


def test_series_unavailable(app_client, account, series):
    series["status"] = 10000
    res = app_client.get(f"/api/shortdrama/series/{SERIES_A}")
    assert res.json()["error"]["code"] == "series_metadata_unavailable"


def test_expired_account_is_reported_as_auth_expired(app_client, account, series):
    account.save(SESSION_COOKIES.replace("1999999999", "1000000000"))
    res = app_client.get(f"/api/shortdrama/series/{SERIES_A}")
    assert res.status_code == 401 and res.json()["error"]["code"] == "auth_expired"


# ------------------------------------------------------------- direct URLs
def test_direct_episode_url_resolves_and_analyses(app_client, account, series, pages):
    link(account)
    res = app_client.post("/api/analyse", json={"url": f"https://www.tiktok.com/shortdrama/episode/{SERIES_A}/1",
                                                "platform": PLATFORM_SHORTDRAMA})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["post"]["url"] == url_for(EP1) and body["post"]["drama"]["episode"] == 1
    assert (EP1, True) in pages.requests


def test_direct_and_share_link_reach_the_same_episode(app_client, account, series):
    link(account)
    direct = app_client.post("/api/analyse", json={"url": f"https://www.tiktok.com/shortdrama/episode/{SERIES_A}/2",
                                                   "platform": PLATFORM_SHORTDRAMA}).json()
    share = app_client.post("/api/analyse", json={"url": SHORT, "platform": PLATFORM_SHORTDRAMA}).json()
    assert direct["post"]["post_id"] == share["post"]["post_id"] == EP2


def test_direct_url_download_uses_episode_filename(app_client, account, series):
    link(account)
    analysed = app_client.post("/api/analyse", json={"url": f"https://www.tiktok.com/shortdrama/episode/{SERIES_A}/3",
                                                     "platform": PLATFORM_SHORTDRAMA}).json()
    job = app_client.post("/api/download", json={"analysis_id": analysed["analysis_id"], "video_index": 1,
                                                 "option_id": "best"}).json()
    done = wait_for_job(app_client, job["job_id"])
    assert done["state"] == "completed" and done["file"]["filename"] == "Harbor & Crown Example 2 - E03.mp4"


def test_direct_url_anonymous_maps_but_reports_login(app_client, series):
    res = app_client.post("/api/analyse", json={"url": f"https://www.tiktok.com/shortdrama/episode/{SERIES_A}/1",
                                                "platform": PLATFORM_SHORTDRAMA})
    assert res.json()["error"]["code"] == "login_required"


def test_direct_url_for_missing_episode(app_client, account, series):
    link(account)
    res = app_client.post("/api/analyse", json={"url": f"https://www.tiktok.com/shortdrama/episode/{SERIES_A}/9",
                                                "platform": PLATFORM_SHORTDRAMA})
    err = res.json()["error"]
    assert res.status_code == 404 and err["code"] == "episode_not_in_series" and err["details"]["episode_count"] == 5


def test_direct_url_when_series_lookup_fails(app_client, account, series):
    link(account)
    series["status"] = 10000
    res = app_client.post("/api/analyse", json={"url": f"https://www.tiktok.com/shortdrama/episode/{SERIES_A}/1",
                                                "platform": PLATFORM_SHORTDRAMA})
    err = res.json()["error"]
    assert err["code"] == "episode_resolution_failed" and "status 10000" in err["message"]
    assert err["details"] == {"platform": PLATFORM_SHORTDRAMA, "series_id": SERIES_A, "episode": 1}


def test_invalid_episode_identifiers_are_rejected():
    for raw in (f"https://www.tiktok.com/shortdrama/episode/{SERIES_A}/0",
                "https://www.tiktok.com/shortdrama/episode/abc/2"):
        with pytest.raises(AppError) as exc:
            validate_post_url(raw)
        assert exc.value.code == ErrorCode.UNSUPPORTED_EPISODE_URL


def test_expired_short_link(app_client, monkeypatch):
    def expired(url, timeout):
        raise AppError(ErrorCode.SHORT_LINK_EXPIRED, "This shared link has expired or no longer leads to a video.")
    monkeypatch.setattr(resolve_mod, "resolve_tiktok_short_link", expired)
    res = app_client.post("/api/analyse", json={"url": SHORT, "platform": PLATFORM_SHORTDRAMA})
    assert res.json()["error"]["code"] == "short_link_expired"


# ------------------------------------------------------------------- batches
def test_batch_downloads_sequentially_and_waits_for_the_browser(app_client, account, series, settings):
    link(account)
    res = app_client.post("/api/shortdrama/batches", json={"series_id": SERIES_A, "episodes": [1, 2, 3, 5]})
    assert res.status_code == 202, res.text
    batch_id = res.json()["batch_id"]
    # Nothing saved yet: at most 2 episodes may occupy temporary storage; the others must wait.
    body = wait_batch(app_client, batch_id, lambda b: count(b, "ready") == 2)
    _time.sleep(0.2)
    body = app_client.get(f"/api/shortdrama/batches/{batch_id}").json()
    assert count(body, "ready") == 2 and count(body, "pending") == 2
    assert len(list((settings.temp_dir / "ready").iterdir())) <= 2
    names = {e["filename"] for e in body["episodes"] if e["filename"]}
    assert "Harbor & Crown Example 2 - E01.mp4" in names
    # Saving lets the batch continue until everything is saved.
    deadline = _time.time() + 10
    while body["state"] == "running" and _time.time() < deadline:
        save_ready(app_client, body)
        _time.sleep(0.05)
        body = app_client.get(f"/api/shortdrama/batches/{batch_id}").json()
    assert body["state"] == "completed" and count(body, "saved") == 4 and body["percent"] == 100.0
    assert list((settings.temp_dir / "ready").iterdir()) == []


def test_locked_episode_is_skipped_and_batch_is_partial(app_client, account, series):
    link(account)
    batch_id = app_client.post("/api/shortdrama/batches", json={"series_id": SERIES_A, "episodes": [1, 4]}).json()["batch_id"]
    body = wait_batch(app_client, batch_id, lambda b: count(b, "ready") == 1 or b["state"] != "running")
    save_ready(app_client, body)
    body = wait_batch(app_client, batch_id, lambda b: b["state"] != "running")
    assert body["state"] == "partial" and body["error"]["code"] == "batch_partial"
    ep4 = next(e for e in body["episodes"] if e["number"] == 4)
    assert ep4["state"] == "skipped" and ep4["error"]["code"] == "account_access_unavailable"
    assert ep4["attempts"] == 0  # never attempted


def test_one_failure_does_not_stop_the_batch_and_can_be_retried(app_client, account, series, pages):
    link(account)
    good = pages.signed_in[EP3]
    pages.signed_in[EP3] = ({}, 10204)  # episode 3 fails
    batch_id = app_client.post("/api/shortdrama/batches", json={"series_id": SERIES_A, "episodes": [2, 3, 5]}).json()["batch_id"]
    body = wait_batch(app_client, batch_id, lambda b: count(b, "failed") == 1)
    deadline = _time.time() + 10
    while body["state"] == "running" and _time.time() < deadline:
        save_ready(app_client, body)
        _time.sleep(0.05)
        body = app_client.get(f"/api/shortdrama/batches/{batch_id}").json()
    assert body["state"] == "partial" and count(body, "saved") == 2
    failed = next(e for e in body["episodes"] if e["number"] == 3)
    assert failed["error"]["code"] == "not_found" and failed["error"]["message"]
    pages.signed_in[EP3] = good
    body = app_client.post(f"/api/shortdrama/batches/{batch_id}/episodes/3/retry").json()
    assert body["state"] == "running"
    body = wait_batch(app_client, batch_id, lambda b: count(b, "ready") == 1)
    save_ready(app_client, body)
    body = wait_batch(app_client, batch_id, lambda b: b["state"] == "completed")
    assert next(e for e in body["episodes"] if e["number"] == 3)["attempts"] == 2


def test_pause_stops_new_episodes_and_resume_continues(app_client, account, series):
    link(account)
    batch_id = app_client.post("/api/shortdrama/batches", json={"series_id": SERIES_A, "episodes": [1, 2, 3]}).json()["batch_id"]
    app_client.post(f"/api/shortdrama/batches/{batch_id}/pause")
    _time.sleep(0.3)
    body = app_client.get(f"/api/shortdrama/batches/{batch_id}").json()
    assert body["state"] == "paused"
    started = 3 - count(body, "pending")
    assert started <= 1
    _time.sleep(0.3)
    assert 3 - count(app_client.get(f"/api/shortdrama/batches/{batch_id}").json(), "pending") == started
    app_client.post(f"/api/shortdrama/batches/{batch_id}/resume")
    deadline = _time.time() + 10
    body = app_client.get(f"/api/shortdrama/batches/{batch_id}").json()
    while body["state"] == "running" and _time.time() < deadline:
        save_ready(app_client, body)
        _time.sleep(0.05)
        body = app_client.get(f"/api/shortdrama/batches/{batch_id}").json()
    assert body["state"] == "completed"


def test_cancel_deletes_unsaved_files(app_client, account, series, settings):
    link(account)
    batch_id = app_client.post("/api/shortdrama/batches", json={"series_id": SERIES_A, "episodes": [1, 2, 3, 5]}).json()["batch_id"]
    wait_batch(app_client, batch_id, lambda b: count(b, "ready") == 2)
    body = app_client.post(f"/api/shortdrama/batches/{batch_id}/cancel").json()
    assert body["state"] == "cancelled" and body["error"]["code"] == "batch_cancelled"
    assert count(body, "cancelled") == 4 and count(body, "ready") == 0
    _time.sleep(0.1)
    assert list((settings.temp_dir / "ready").iterdir()) == []
    assert not any(p.name.startswith("job-") for p in settings.temp_dir.iterdir())


def test_batch_rejects_unknown_episodes_and_limits(app_client, account, series):
    link(account)
    res = app_client.post("/api/shortdrama/batches", json={"series_id": SERIES_A, "episodes": [1, 42]})
    assert res.status_code == 404 and res.json()["error"]["code"] == "episode_not_in_series"
    for bad in ({"series_id": SERIES_A, "episodes": [1], "concurrency": 3},
                {"series_id": SERIES_A, "episodes": []},
                {"series_id": "../etc", "episodes": [1]},
                {"series_id": SERIES_A, "episodes": [1], "quality": "4k; rm -rf"},
                {"series_id": SERIES_A, "episodes": [1], "path": "/tmp"}):
        assert app_client.post("/api/shortdrama/batches", json=bad).status_code == 422, bad
    assert app_client.get("/api/shortdrama/batches/" + "0" * 32).json()["error"]["code"] == "batch_not_found"


def test_strict_preferred_resolution_fails_the_episode(app_client, account, series):
    link(account)
    batch_id = app_client.post("/api/shortdrama/batches", json={"series_id": SERIES_A, "episodes": [1],
                                                                "quality": "1080p", "strict": True}).json()["batch_id"]
    body = wait_batch(app_client, batch_id, lambda b: b["state"] != "running")
    assert body["episodes"][0]["error"]["code"] == "preferred_resolution_unavailable"


def test_preferred_resolution_falls_back_with_a_note(app_client, account, series):
    link(account)
    batch_id = app_client.post("/api/shortdrama/batches", json={"series_id": SERIES_A, "episodes": [1],
                                                                "quality": "1080p"}).json()["batch_id"]
    body = wait_batch(app_client, batch_id, lambda b: count(b, "ready") == 1)
    ep = body["episodes"][0]
    assert ep["option_label"] == "720p" and "1080p isn't available" in ep["note"]
    save_ready(app_client, body)


# ------------------------------------------------------------------- units
def test_choose_option_rules():
    from app.selection import build_options
    from app.models import MediaFormat, VideoEntry

    def f(fid, h, w, acodec="aac", has_audio=True):
        return MediaFormat(format_id=fid, ext="mp4", protocol="https", vcodec="h264", acodec=acodec, width=w,
                           height=h, has_video=True, has_audio=has_audio)
    opts = build_options(VideoEntry(index=1, formats=(f("a", 1280, 720), f("b", 1024, 576), f("c", 852, 480))))
    assert choose_option(opts, "best")[0].height == 1280
    assert choose_option(opts, "576p") == (opts[2], None)
    pick, note = choose_option(opts, "540p")
    assert pick.height == 852 and "540p" in note
    pick, note = choose_option(opts, "360p")
    assert pick.is_best and "360p" in note
    with pytest.raises(AppError) as exc:
        choose_option(opts, "1080p", strict=True)
    assert exc.value.code == ErrorCode.PREFERRED_RESOLUTION_UNAVAILABLE


@pytest.mark.parametrize(("title", "n", "count", "expected"), [
    ("Harbor & Crown Example 2", 1, 52, "Harbor & Crown Example 2 - E01.mp4"),
    ("Harbor & Crown Example 2", 12, 52, "Harbor & Crown Example 2 - E12.mp4"),
    ("Long Show", 7, 120, "Long Show - E007.mp4"),
    ("../../etc/passwd", 3, 10, "etc passwd - E03.mp4"),
    (None, 2, None, "Short Drama - E02.mp4"),
])
def test_episode_filenames(title, n, count, expected):
    name = episode_filename(title, n, count)
    assert "/" not in name and name.endswith(".mp4")
    assert name == expected or (title and title.startswith("..") and name.endswith(" - E03.mp4"))


def test_equivalent_format_id():
    avail = ["audio", "bytevc1_720p_605781-0", "bytevc1_720p_605781-1", "h264_540p_1036410-0"]
    assert equivalent_format_id("bytevc1_720p_517560-0", avail) == "bytevc1_720p_605781-0"
    assert equivalent_format_id("bytevc1_720p_517560-1", avail) == "bytevc1_720p_605781-1"
    assert equivalent_format_id("bytevc1_1080p_1-0", avail) is None
    assert equivalent_format_id("audio", avail) is None


def test_download_survives_a_changed_tiktok_format_id(sd_provider, account, pages, tmp_path):
    link(account)
    post = sd_provider.extract(sd_url(EP2))
    fid = next(f.format_id for f in post.videos[0].formats if f.height == 1280 and f.format_id.endswith("-0"))
    changed = item(EP2, episode=2)
    for b in changed["video"]["bitrateInfo"]:
        b["PlayAddr"]["UrlKey"] = b["PlayAddr"]["UrlKey"].replace("610784", "999999")
        b["PlayAddr"]["UrlList"] = [u.replace("610784", "999999") for u in b["PlayAddr"]["UrlList"]]
    pages.signed_in[EP2] = (changed, 0)
    out = sd_provider.download(sd_url(EP2), 1, [fid], tmp_path, lambda u: None)
    assert out[fid].name.startswith("bytevc1_720p_999999-0")


# ===================================================================== v1.5: ZIP / merged MP4
import io as _io
import threading
import zipfile as _zipfile

from app import packaging as packaging_mod
from app.batches import range_label
from app.packaging import MergeResult


def fake_merge(calls, gate: "threading.Event | None" = None):
    def merge(processor, inputs, out, *, cancel, progress, timeout=0):
        calls.append([p.name for p in inputs])
        if gate is not None:
            while not gate.is_set():
                if cancel.is_set():
                    raise AppError(ErrorCode.BATCH_CANCELLED, "Processing was cancelled.")
                _time.sleep(0.01)
        out.write_bytes(b"".join(p.read_bytes() for p in inputs))
        progress(100)
        return MergeResult("stream_copy", None, 10.0 * len(inputs), [])
    return merge


def start_batch(client, **body):
    res = client.post("/api/shortdrama/batches", json={"series_id": SERIES_A, **body})
    assert res.status_code == 202, res.text
    return res.json()["batch_id"]


def finished(b):
    return b["state"] in ("ready", "needs_decision", "failed", "completed", "partial", "cancelled")


def test_zip_batch_packages_selected_episodes(app_client, account, series, settings):
    link(account)
    batch_id = start_batch(app_client, episodes=[3, 1, 2], output="zip")
    body = wait_batch(app_client, batch_id, finished)
    assert body["state"] == "ready", body
    r = body["result"]
    assert r["filename"] == "Harbor & Crown Example 2 - E01-E03.zip" and r["kind"] == "zip"
    assert r["included"] == [1, 2, 3] and r["omitted"] == []
    # Episodes were never offered to the browser one by one.
    assert all(e["download_url"] is None and e["state"] == "downloaded" for e in body["episodes"])
    res = app_client.get(r["download_url"])
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    with _zipfile.ZipFile(_io.BytesIO(res.content)) as zf:
        assert zf.namelist() == [f"Harbor & Crown Example 2 - E0{n}.mp4" for n in (1, 2, 3)]
        assert zf.testzip() is None
    body = wait_batch(app_client, batch_id, lambda b: b["state"] == "completed")
    assert body["percent"] == 100.0
    assert list((settings.temp_dir / "ready").iterdir()) == []
    assert not any(p.name.startswith("job-") for p in settings.temp_dir.iterdir())


def test_failed_episode_stops_packaging_by_default_then_continue(app_client, account, series, settings):
    link(account)
    batch_id = start_batch(app_client, episodes=[1, 2, 3, 4, 5], output="zip")  # 4 is locked
    body = wait_batch(app_client, batch_id, finished)
    assert body["state"] == "needs_decision" and body["error"]["code"] == "batch_partial"
    assert body["error"]["details"] == {"failed": [4], "downloaded": [1, 2, 3, 5]}
    assert body["result"] is None
    body = app_client.post(f"/api/shortdrama/batches/{batch_id}/continue").json()
    body = wait_batch(app_client, batch_id, finished)
    r = body["result"]
    assert body["state"] == "ready" and r["omitted"] == [4] and r["included"] == [1, 2, 3, 5]
    assert r["filename"] == "Harbor & Crown Example 2 - E01, E02, E03, E05 (partial, 4 of 5).zip"
    with _zipfile.ZipFile(_io.BytesIO(app_client.get(r["download_url"]).content)) as zf:
        manifest = zf.read("MediaLab manifest.txt").decode()
    assert "E04" in manifest and "skipped" in manifest
    assert "Complete Series" not in r["filename"]
    body = wait_batch(app_client, batch_id, lambda b: b["state"] in ("completed", "partial"))
    assert body["state"] == "partial"


def test_allow_partial_packages_without_asking(app_client, account, series):
    link(account)
    batch_id = start_batch(app_client, episodes=[2, 4], output="zip", allow_partial=True)
    body = wait_batch(app_client, batch_id, finished)
    # Only one episode remains: it is delivered as a normal MP4, not a one-file ZIP.
    assert body["state"] == "ready" and body["result"]["kind"] == "mp4"
    assert body["result"]["filename"] == "Harbor & Crown Example 2 - E02.mp4"


def test_complete_series_name_only_when_every_episode_is_included(app_client, account, series, pages):
    link(account)
    unlocked = item(EP4_LOCKED, episode=4)
    pages.signed_in[EP4_LOCKED] = (unlocked, 0)
    sd = app_client.app.state.services.batches.provider
    listing = sd._api

    def api(ydl, path, params):  # the series listing now shows episode 4 as playable too
        data = listing(ydl, path, params)
        data["itemList"] = [copy.deepcopy(unlocked) if it.get("id") == EP4_LOCKED else it
                            for it in data.get("itemList") or []]
        return data
    sd._api = api
    batch_id = start_batch(app_client, episodes=[1, 2, 3, 4, 5], output="zip")
    body = wait_batch(app_client, batch_id, finished)
    assert body["result"]["filename"] == "Harbor & Crown Example 2 - Complete Series.zip"


def test_merge_batch_plans_one_quality_and_merges_in_order(app_client, account, series, monkeypatch):
    link(account)
    calls = []
    monkeypatch.setattr(packaging_mod, "merge_mp4", fake_merge(calls))
    batch_id = start_batch(app_client, episodes=[3, 1, 2], output="merge")
    body = wait_batch(app_client, batch_id, finished)
    assert body["state"] == "ready", body
    assert body["quality"] == "720p" and body["strict"] is True and "720p" in body["plan_note"]
    assert calls == [["E0001.mp4", "E0002.mp4", "E0003.mp4"]]  # ascending episode order
    r = body["result"]
    assert r["filename"] == "Harbor & Crown Example 2 - E01-E03.mp4" and r["method"] == "stream_copy"
    assert all(e["option_label"] == "720p" for e in body["episodes"])
    assert app_client.get(r["download_url"]).status_code == 200
    wait_batch(app_client, batch_id, lambda b: b["state"] == "completed")


def test_merge_retry_failed_episode_then_package(app_client, account, series, pages, monkeypatch):
    link(account)
    calls = []
    monkeypatch.setattr(packaging_mod, "merge_mp4", fake_merge(calls))
    good = pages.signed_in[EP3]
    pages.signed_in[EP3] = ({}, 10204)
    batch_id = start_batch(app_client, episodes=[1, 2, 3], output="merge", quality="720p")
    body = wait_batch(app_client, batch_id, finished)
    assert body["state"] == "needs_decision" and calls == []
    pages.signed_in[EP3] = good
    app_client.post(f"/api/shortdrama/batches/{batch_id}/episodes/3/retry")
    body = wait_batch(app_client, batch_id, finished)
    assert body["state"] == "ready" and body["result"]["omitted"] == [] and len(calls) == 1


def test_cancel_during_packaging_cleans_up(app_client, account, series, settings, monkeypatch):
    link(account)
    gate = threading.Event()
    monkeypatch.setattr(packaging_mod, "merge_mp4", fake_merge([], gate))
    batch_id = start_batch(app_client, episodes=[1, 2], output="merge", quality="720p")
    wait_batch(app_client, batch_id, lambda b: b["state"] == "packaging")
    body = app_client.post(f"/api/shortdrama/batches/{batch_id}/cancel").json()
    assert body["state"] == "cancelled"
    _time.sleep(0.3)
    assert not any(p.name.startswith("job-") for p in settings.temp_dir.iterdir())
    assert list((settings.temp_dir / "ready").iterdir()) == []


def test_packaging_failure_keeps_episodes_for_retry(app_client, account, series, monkeypatch):
    link(account)
    attempts = []

    def flaky(processor, inputs, out, *, cancel, progress, timeout=0):
        attempts.append(1)
        if len(attempts) == 1:
            raise AppError(ErrorCode.MERGE_FAILED, "The merged MP4 doesn't decode cleanly.", retryable=True)
        return fake_merge([])(processor, inputs, out, cancel=cancel, progress=progress)
    monkeypatch.setattr(packaging_mod, "merge_mp4", flaky)
    batch_id = start_batch(app_client, episodes=[1, 2], output="merge", quality="720p")
    body = wait_batch(app_client, batch_id, finished)
    assert body["state"] == "failed" and body["error"]["code"] == "merge_failed" and body["error"]["retryable"]
    app_client.post(f"/api/shortdrama/batches/{batch_id}/continue")
    body = wait_batch(app_client, batch_id, lambda b: b["state"] == "ready")
    assert body["result"]["included"] == [1, 2]


def test_insufficient_disk_space_for_packaging(app_client, account, series, monkeypatch):
    from app import batches as bm
    link(account)
    monkeypatch.setattr(bm, "free_bytes", lambda path: 0)
    batch_id = start_batch(app_client, episodes=[1, 2], output="zip")
    body = wait_batch(app_client, batch_id, finished)
    assert body["state"] == "failed" and body["error"]["code"] == "insufficient_space"


def test_batch_output_limit_is_separate_from_episode_limit(app_client, account, series, monkeypatch):
    from app.user_settings import UserSettings
    link(account)
    monkeypatch.setattr(UserSettings, "batch_output_max_bytes", property(lambda self: 5000))
    batch_id = start_batch(app_client, episodes=[1, 2], output="zip")
    body = wait_batch(app_client, batch_id, finished)
    assert body["state"] == "failed" and body["error"]["code"] == "batch_output_too_large"
    assert "batch output limit" in body["error"]["message"]


def test_duplicate_batches_are_refused(app_client, account, series, monkeypatch):
    link(account)
    monkeypatch.setattr(packaging_mod, "merge_mp4", fake_merge([], threading.Event()))
    first = start_batch(app_client, episodes=[1, 2], output="merge", quality="720p")
    res = app_client.post("/api/shortdrama/batches", json={"series_id": SERIES_A, "episodes": [2, 1],
                                                           "output": "merge", "quality": "720p"})
    assert res.status_code == 409 and res.json()["error"]["details"]["batch_id"] == first
    app_client.post(f"/api/shortdrama/batches/{first}/cancel")


def test_settings_expose_and_bound_the_batch_output_limit(app_client):
    body = app_client.get("/api/settings").json()
    assert body["batch_output_max_mb"] == 32768 and body["batch_output_limits"]["max_mb"] == 262144
    assert app_client.patch("/api/settings", json={"batch_output_max_mb": 65536}).json()["batch_output_max_mb"] == 65536
    assert app_client.patch("/api/settings", json={"batch_output_max_mb": 10}).status_code == 422
    assert app_client.patch("/api/settings", json={"batch_output_max_mb": "big"}).status_code == 422


def test_progress_reports_stages(app_client, account, series, monkeypatch):
    link(account)
    gate = threading.Event()
    monkeypatch.setattr(packaging_mod, "merge_mp4", fake_merge([], gate))
    batch_id = start_batch(app_client, episodes=[1, 2], output="merge", quality="720p")
    body = wait_batch(app_client, batch_id, lambda b: b["state"] == "packaging")
    assert body["stage"] in ("Verifying episodes", "Merging videos") and 80 <= body["percent"] < 97
    assert body["estimated_duration_seconds"] == 230  # 115 s per fake episode
    gate.set()
    body = wait_batch(app_client, batch_id, lambda b: b["state"] == "ready")
    assert body["stage"] == "Ready to save" and body["percent"] == 97.0


@pytest.mark.parametrize(("nums", "complete", "expected"), [
    ([1, 2, 3], False, "E01-E03"), ([1, 3, 5], False, "E01, E03, E05"),
    ([1, 2, 4, 6, 8, 9], False, "E01-E09 (6 episodes)"), ([1, 2, 3, 4, 5], True, "Complete Series"),
    ([1, 2, 3, 4, 5], False, "E01-E05"), ([7], False, "E07"),
])
def test_range_labels(nums, complete, expected):
    assert range_label(nums, frozenset(range(1, 6)), complete, 52) == expected


# ------------------------------------- MED-1: Short Drama soundtrack trust
def _with_music(data, original):
    data = copy.deepcopy(data)
    data["music"] = {"playUrl": "https://v16-webapp-prime.tiktok.com/video/tos/music.mp3?mime_type=audio_mpeg",
                     "original": original, "title": "original sound - Emo Universe"}
    return data


@pytest.mark.parametrize(("original", "kept"), [(True, True), (False, False), (None, False)])
def test_short_drama_uses_separate_track_only_when_marked_original(sd_provider, account, pages, original, kept):
    link(account)
    pages.signed_in[EP2] = (_with_music(pages.signed_in[EP2][0], original), 0)
    post = sd_provider.extract(sd_url(EP2))
    assert ("audio" in {f.format_id for f in post.videos[0].formats}) is kept
