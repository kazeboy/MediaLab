"""Metadata normalisation and resolution discovery using mocked extraction output."""

import pytest

from app.errors import AppError, ErrorCode
from app.models import MediaFormat, VideoEntry
from app.providers.ytdlp_normalise import normalise_info
from app.selection import BEST_OPTION_ID, build_options, resolution_label, resolve_option
from app.validation import validate_post_url

from . import fixtures

URL = validate_post_url(fixtures.POST_URL)
HOSTS = ("twimg.com",)


def test_normalise_single_video_metadata():
    post = normalise_info(fixtures.single_video_info(), URL, HOSTS)
    assert post.url == fixtures.POST_URL
    assert post.post_id == "1800000000000000001"
    assert post.author_name == "Test Author"
    assert post.author_handle == "medialab_test"
    assert post.text.startswith("A test post")
    assert len(post.videos) == 1
    video = post.videos[0]
    assert video.index == 1
    assert video.duration_seconds == 15.5
    assert video.thumbnail_url.startswith("https://pbs.twimg.com/")


def test_normalise_drops_formats_on_unknown_hosts():
    video = normalise_info(fixtures.single_video_info(), URL, HOSTS).videos[0]
    ids = {f.format_id for f in video.formats}
    assert "http-9999" not in ids
    assert {"http-288", "hls-4500", "hls-audio-128000-Audio"} <= ids


def test_normalise_stream_flags_and_codecs():
    formats = {f.format_id: f for f in normalise_info(fixtures.single_video_info(), URL, HOSTS).videos[0].formats}
    hls = formats["hls-4500"]
    assert (hls.has_video, hls.has_audio, hls.vcodec, hls.acodec) == (True, False, "avc1.64001F", None)
    audio = formats["hls-audio-128000-Audio"]
    assert (audio.has_video, audio.has_audio, audio.acodec) == (False, True, "mp4a.40.2")
    progressive = formats["http-2176"]
    # yt-dlp does not report codecs for X's progressive files: stay unknown, never guess.
    assert progressive.vcodec is None and progressive.acodec is None
    assert progressive.has_audio is None
    assert progressive.filesize == 1404023 and progressive.filesize_approx is None
    assert progressive.mp4_compatible is True


def test_approximate_size_from_bitrate_is_flagged_approximate():
    formats = {f.format_id: f for f in normalise_info(fixtures.single_video_info(), URL, HOSTS).videos[0].formats}
    hls = formats["hls-4500"]
    assert hls.filesize is None
    assert hls.filesize_approx == int(4500 * 1000 / 8 * 15.5)


def test_missing_metadata_is_not_fabricated():
    info = fixtures.single_video_info()
    for key in ("uploader", "uploader_id", "description", "duration", "thumbnail"):
        info.pop(key)
    post = normalise_info(info, URL, HOSTS)
    assert post.author_name is None and post.author_handle is None and post.text is None
    video = post.videos[0]
    assert video.duration_seconds is None and video.thumbnail_url is None
    hls = next(f for f in video.formats if f.format_id == "hls-4500")
    assert hls.filesize is None and hls.filesize_approx is None


def test_multi_video_post():
    post = normalise_info(fixtures.multi_video_info(), URL, HOSTS)
    assert [v.index for v in post.videos] == [1, 2]
    assert post.videos[1].duration_seconds == 30
    assert post.author_handle == "medialab_test"


def test_no_video_raises():
    info = fixtures.single_video_info()
    info["formats"] = [f for f in info["formats"] if f.get("vcodec") == "none"]
    with pytest.raises(AppError) as exc:
        normalise_info(info, URL, HOSTS)
    assert exc.value.code == ErrorCode.NO_VIDEO


def test_thumbnail_on_foreign_host_is_dropped():
    info = fixtures.single_video_info()
    info["thumbnail"] = "https://tracker.example.com/pixel.gif"
    assert normalise_info(info, URL, HOSTS).videos[0].thumbnail_url is None


# --------------------------------------------------------------- resolutions
def _options(info=None):
    video = normalise_info(info or fixtures.single_video_info(), URL, HOSTS).videos[0]
    return build_options(video)


def test_resolution_discovery_only_real_resolutions():
    options = _options()
    ids = [o.option_id for o in options]
    assert ids == ["best", "1080p", "720p", "360p", "270p"]
    assert "2160p" not in ids  # the 4K format was on a foreign host and was dropped


def test_best_available_is_highest_resolution():
    best = _options()[0]
    assert best.option_id == BEST_OPTION_ID and best.is_best
    assert best.label == "Best Available (1080p)"
    assert (best.width, best.height) == (1920, 1080)


def test_video_only_stream_is_paired_with_best_audio():
    opt = next(o for o in _options() if o.option_id == "1080p")
    assert opt.video_format_id == "hls-4500"
    assert opt.audio_format_id == "hls-audio-128000-Audio"  # 128k beats 64k
    assert opt.requires_merge
    assert opt.acodec == "mp4a.40.2"
    assert opt.filesize is None and opt.filesize_approx > 0


def test_higher_bitrate_candidate_wins_within_a_resolution():
    opt = next(o for o in _options() if o.option_id == "720p")
    # progressive 2176 kbps beats HLS 716 + 128 kbps
    assert opt.video_format_id == "http-2176" and not opt.requires_merge
    assert opt.filesize == 1404023


def test_portrait_video_labelled_by_short_side():
    assert resolution_label(720, 1280) == "720p"
    assert resolution_label(3840, 2160) == "2160p (4K)"
    assert resolution_label(None, 480) == "480p"
    assert resolution_label(None, None) is None


def test_incompatible_codecs_are_not_offered_for_download():
    options = _options(fixtures.vp9_only_info())
    assert all(o.option_id != BEST_OPTION_ID for o in options)
    assert len(options) == 1 and not options[0].downloadable
    assert "re-encoding" in options[0].note
    with pytest.raises(AppError) as exc:
        resolve_option(options, BEST_OPTION_ID)
    assert exc.value.code == ErrorCode.INCOMPATIBLE_FORMAT
    with pytest.raises(AppError) as exc:
        resolve_option(options, options[0].option_id)
    assert exc.value.code == ErrorCode.INCOMPATIBLE_FORMAT


def test_best_skips_incompatible_higher_resolution():
    formats = (
        MediaFormat(format_id="vp9", ext="webm", protocol="https", width=3840, height=2160, vcodec="vp9",
                    acodec="opus", has_video=True, has_audio=True, tbr=9000),
        MediaFormat(format_id="h264", ext="mp4", protocol="https", width=1920, height=1080, vcodec="avc1",
                    acodec="mp4a.40.2", has_video=True, has_audio=True, tbr=4000),
    )
    options = build_options(VideoEntry(index=1, formats=formats))
    assert options[0].label == "Best Available (1080p)"
    assert options[0].video_format_id == "h264"


def test_resolve_unknown_option():
    with pytest.raises(AppError) as exc:
        resolve_option(_options(), "4320p")
    assert exc.value.code == ErrorCode.INVALID_SELECTION


def test_video_without_audio_is_labelled():
    formats = (MediaFormat(format_id="gif", ext="mp4", protocol="https", width=480, height=270, vcodec="avc1",
                           acodec=None, has_video=True, has_audio=False),)
    opt = build_options(VideoEntry(index=1, formats=formats))[1]
    assert opt.has_audio is False and "No audio" in opt.note and opt.downloadable


# ------------------------------------------------------------- size limit
def _sized(height: int, size: int) -> MediaFormat:
    return MediaFormat(format_id=f"h{height}", ext="mp4", protocol="https", width=height * 16 // 9, height=height,
                       vcodec="avc1", acodec="mp4a.40.2", has_video=True, has_audio=True, tbr=height, filesize=size)


def test_options_over_size_limit_are_flagged_and_skipped_by_best():
    video = VideoEntry(index=1, formats=(_sized(1080, 3_000_000_000), _sized(720, 700_000_000)))
    options = build_options(video, max_size_bytes=2048 * 1024 * 1024)
    by_id = {o.option_id: o for o in options}
    assert by_id["1080p"].too_large and not by_id["1080p"].downloadable and "size limit" in by_id["1080p"].note
    assert by_id["best"].label == "Best Available (720p)"
    with pytest.raises(AppError) as exc:
        resolve_option(options, "1080p")
    assert exc.value.code == ErrorCode.FILE_TOO_LARGE


def test_all_options_over_size_limit():
    options = build_options(VideoEntry(index=1, formats=(_sized(720, 5_000_000),)), max_size_bytes=1_000_000)
    with pytest.raises(AppError) as exc:
        resolve_option(options, BEST_OPTION_ID)
    assert exc.value.code == ErrorCode.FILE_TOO_LARGE


def test_estimated_sizes_never_block():
    fmt = _sized(1080, 0).model_copy(update={"filesize": None, "filesize_approx": 9_000_000_000})
    options = build_options(VideoEntry(index=1, formats=(fmt,)), max_size_bytes=1_000_000)
    assert options[0].downloadable  # only exact sizes are grounds to refuse up front
