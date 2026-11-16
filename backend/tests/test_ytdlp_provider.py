"""yt-dlp provider: sanitising raw results, error mapping, output collection (no network)."""

import pytest

from app.config import Settings
from app.errors import AppError, ErrorCode
from app.providers.ytdlp_provider import YtDlpProvider, map_ytdlp_error

from . import fixtures


@pytest.fixture
def provider():
    return YtDlpProvider(Settings())


def test_params_lock_down_extractors_and_credentials(provider):
    params = provider._base_params()
    assert params["allowed_extractors"] == ["twitter"]
    assert params["cookiefile"] is None and params["cookiesfrombrowser"] is None
    assert params["usenetrc"] is False and params["cachedir"] is False


def test_sanitise_drops_foreign_formats(provider):
    safe = provider._sanitise(fixtures.single_video_info())
    assert all("twimg.com" in f["url"] for f in safe["formats"])
    assert "http-9999" not in {f["format_id"] for f in safe["formats"]}


@pytest.mark.parametrize("kind", ["url", "url_transparent"])
def test_sanitise_rejects_external_links(provider, kind):
    with pytest.raises(AppError) as exc:
        provider._sanitise({"_type": kind, "url": "http://169.254.169.254/"})
    assert exc.value.code == ErrorCode.NO_VIDEO


def test_sanitise_playlist_drops_url_entries(provider):
    info = fixtures.multi_video_info()
    info["entries"].insert(0, {"_type": "url", "url": "https://example.com"})
    safe = provider._sanitise(info)
    assert [e["id"] for e in safe["entries"]] == ["111", "222"]


def test_sanitise_entry_with_only_foreign_formats(provider):
    info = fixtures.single_video_info()
    for f in info["formats"]:
        f["url"] = "https://cdn.example.com/x.mp4"
    with pytest.raises(AppError) as exc:
        provider._sanitise(info)
    # Regression: a video that exists on an unexpected host is not "no video".
    assert exc.value.code == ErrorCode.MEDIA_HOST_BLOCKED and "was found" in exc.value.message


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("ERROR: [twitter] 1: No video could be found in this tweet", ErrorCode.NO_VIDEO),
        ("ERROR: [twitter] 1: NSFW tweet requires authentication. Use --cookies", ErrorCode.LOGIN_REQUIRED),
        ("ERROR: [twitter] 1: Requested tweet is unavailable", ErrorCode.NOT_FOUND),
        ("ERROR: [twitter] 1: Twitter API says: This account is suspended", ErrorCode.UNAVAILABLE),
        ("ERROR: Unable to download JSON metadata: HTTP Error 429: Too Many Requests", ErrorCode.RATE_LIMITED),
        ("ERROR: [twitter] 1: Unable to download webpage: <urlopen error [Errno 8] nodename nor servname>",
         ErrorCode.NETWORK_ERROR),
        ("ERROR: Read timed out.", ErrorCode.TIMEOUT),
        ("ERROR: [twitter] 1: Requested format is not available", ErrorCode.FORMAT_UNAVAILABLE),
        ("ERROR: [twitter] 1: Something odd happened", ErrorCode.EXTRACTION_FAILED),
    ],
)
def test_error_mapping(message, code):
    from yt_dlp.utils import DownloadError

    err = map_ytdlp_error(DownloadError(message))
    assert err.code == code
    assert err.message


def test_unknown_download_error_maps_to_download_failed():
    from yt_dlp.utils import DownloadError

    assert map_ytdlp_error(DownloadError("weird"), during_download=True).code == ErrorCode.DOWNLOAD_FAILED


def test_collect_outputs_from_requested_downloads(tmp_path):
    v = tmp_path / "hls-1.mp4"
    a = tmp_path / "hls-audio.mp4"
    v.write_bytes(b"v")
    a.write_bytes(b"a")
    result = {"requested_downloads": [{"format_id": "hls-1", "filepath": str(v)}]}
    outputs = YtDlpProvider._collect_outputs(result, ["hls-1", "hls-audio"], tmp_path)
    assert outputs == {"hls-1": v.resolve(), "hls-audio": a.resolve()}


def test_collect_outputs_ignores_paths_outside_job_dir(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    outside = tmp_path / "x.mp4"
    outside.write_bytes(b"x")
    with pytest.raises(AppError) as exc:
        YtDlpProvider._collect_outputs({"requested_downloads": [{"format_id": "x", "filepath": str(outside)}]}, ["x"], job)
    assert exc.value.code == ErrorCode.DOWNLOAD_FAILED


def test_guest_tombstone_message_mentions_signed_in_only_posts():
    """X answers logged-out clients with a bare TweetTombstone for some posts; yt-dlp then
    reports "No video could be found". The message must not claim the post has no video."""
    from yt_dlp.utils import DownloadError

    err = map_ytdlp_error(DownloadError("ERROR: [twitter] 2117302655580311799: No video could be found in this tweet"))
    assert err.code == ErrorCode.NO_VIDEO
    assert "signed-in" in err.message and "public posts only" in err.message
