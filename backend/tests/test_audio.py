"""Audio reliability: real FFmpeg on small generated samples (skipped without FFmpeg).

Regression for the v1.3 bug: HEVC video + separate MP3 was muxed as MP3-in-MP4,
which AVFoundation (QuickTime/Safari) ignores, so the file played silently.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from app.errors import AppError, ErrorCode
from app.media import MediaProcessor, ProbeResult
from app.models import MediaFormat, VideoEntry
from app.selection import audio_needs_conversion, build_options

from .conftest import HAS_FFMPEG

needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


def _encoders() -> str:
    if not HAS_FFMPEG:
        return ""
    return subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout


ENC = _encoders()
needs_x265 = pytest.mark.skipif("libx265" not in ENC, reason="ffmpeg without libx265")
needs_mp3 = pytest.mark.skipif("libmp3lame" not in ENC, reason="ffmpeg without libmp3lame")


def ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def video(tmp: Path, codec="libx264", seconds=3, name="v.mp4", audio: str | None = None) -> Path:
    path = tmp / name
    args = ["-f", "lavfi", "-i", f"testsrc=size=160x284:rate=24:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", audio]
    else:
        args += ["-an"]
    args += ["-c:v", codec, "-pix_fmt", "yuv420p"]
    if codec == "libx265":
        args += ["-tag:v", "hvc1", "-x265-params", "log-level=error"]
    ff(*args, str(path))
    return path


def audio(tmp: Path, codec: str, seconds=3, name=None, silent=False) -> Path:
    ext = {"libmp3lame": "mp3", "aac": "m4a", "libopus": "ogg", "wmav2": "wma"}[codec]
    path = tmp / (name or f"a.{ext}")
    src = f"anullsrc=r=44100:cl=stereo:d={seconds}" if silent else f"sine=frequency=440:duration={seconds}"
    ff("-f", "lavfi", "-i", src, *(["-t", str(seconds)] if silent else []), "-c:a", codec, str(path))
    return path


def video_hash(path: Path) -> str:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return hashlib.sha256(raw).hexdigest()


def codec_tag(path: Path, stream: str) -> str:
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries",
                           "stream=codec_tag_string", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True).stdout.strip()


# ------------------------------------------------------------ codec matrix
@needs_ffmpeg
@needs_x265
@needs_mp3
def test_hevc_plus_mp3_converts_audio_to_aac_and_keeps_video(tmp_path):
    v, a = video(tmp_path, "libx265"), audio(tmp_path, "libmp3lame")
    out = tmp_path / "o.mp4"
    result = MediaProcessor().assemble_mp4(v, a, out)
    assert result.video_codec == "hevc" and codec_tag(out, "v:0") == "hvc1"
    assert result.audio_codec == "aac" and result.audio_converted and result.source_audio_codec == "mp3"
    assert video_hash(out) == video_hash(v)  # video bitstream untouched
    assert MediaProcessor().max_volume_db(out) > -30  # audible
    assert not result.audio_silent


@needs_ffmpeg
@needs_x265
def test_hevc_plus_aac_copies_audio(tmp_path):
    v, a = video(tmp_path, "libx265"), audio(tmp_path, "aac")
    result = MediaProcessor().assemble_mp4(v, a, tmp_path / "o.mp4")
    assert result.audio_codec == "aac" and not result.audio_converted


@needs_ffmpeg
def test_h264_with_embedded_aac_is_copied(tmp_path):
    v = video(tmp_path, audio="aac")
    out = tmp_path / "o.mp4"
    result = MediaProcessor().assemble_mp4(v, None, out)
    assert result.video_codec == "h264" and result.audio_codec == "aac" and not result.audio_converted
    assert video_hash(out) == video_hash(v)


@needs_ffmpeg
@needs_mp3
def test_embedded_mp3_is_converted_too(tmp_path):
    v = tmp_path / "v.mov"
    ff("-f", "lavfi", "-i", "testsrc=size=160x120:rate=24:duration=2", "-f", "lavfi", "-i",
       "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "libmp3lame", str(v))
    result = MediaProcessor().assemble_mp4(v, None, tmp_path / "o.mp4")
    assert result.audio_codec == "aac" and result.audio_converted


@needs_ffmpeg
@pytest.mark.skipif("libopus" not in ENC, reason="ffmpeg without libopus")
def test_opus_is_converted(tmp_path):
    result = MediaProcessor().assemble_mp4(video(tmp_path), audio(tmp_path, "libopus"), tmp_path / "o.mp4")
    assert result.audio_codec == "aac" and result.audio_converted and result.source_audio_codec == "opus"


@needs_ffmpeg
def test_video_only_source_is_not_an_error(tmp_path):
    result = MediaProcessor().assemble_mp4(video(tmp_path), None, tmp_path / "o.mp4")
    assert result.has_video and not result.has_audio and not result.audio_converted


@needs_ffmpeg
def test_missing_audio_track_in_separate_file(tmp_path):
    v = video(tmp_path)
    not_audio = video(tmp_path, name="not-audio.mp4")
    with pytest.raises(AppError) as exc:
        MediaProcessor().assemble_mp4(v, not_audio, tmp_path / "o.mp4")
    assert exc.value.code == ErrorCode.AUDIO_MISSING


@needs_ffmpeg
def test_silent_source_audio_is_accepted_and_flagged(tmp_path):
    result = MediaProcessor().assemble_mp4(video(tmp_path), audio(tmp_path, "aac", silent=True), tmp_path / "o.mp4")
    assert result.has_audio and result.audio_silent


@needs_ffmpeg
def test_audio_duration_mismatch_is_reported(tmp_path):
    v = video(tmp_path, seconds=6)
    a = audio(tmp_path, "aac", seconds=2)
    with pytest.raises(AppError) as exc:
        MediaProcessor().assemble_mp4(v, a, tmp_path / "o.mp4")
    assert exc.value.code == ErrorCode.AV_SYNC_FAILED
    assert exc.value.details["audio_seconds"] < exc.value.details["video_seconds"]


@needs_ffmpeg
@pytest.mark.skipif("wmav2" not in ENC, reason="ffmpeg without wmav2")
def test_unsupported_audio_codec_is_rejected(tmp_path):
    with pytest.raises(AppError) as exc:
        MediaProcessor().assemble_mp4(video(tmp_path), audio(tmp_path, "wmav2"), tmp_path / "o.mp4")
    assert exc.value.code == ErrorCode.INCOMPATIBLE_FORMAT


# ------------------------------------------------- output validation logic
def _result(**kw) -> ProbeResult:
    base = dict(format_name="mp4", duration_seconds=10.0, size_bytes=1, width=1, height=1, fps=24.0,
                video_codec="hevc", audio_codec="aac", has_video=True, has_audio=True,
                video_duration=10.0, audio_duration=10.0, video_start=0.0, audio_start=0.0)
    base.update(kw)
    return ProbeResult(**base)


class Levels(MediaProcessor):
    def __init__(self, *levels):
        super().__init__()
        self.levels = list(levels)

    def max_volume_db(self, path, stream="0:a:0"):
        return self.levels.pop(0)


def test_wrong_stream_mapping_without_audio_is_detected(tmp_path):
    with pytest.raises(AppError) as exc:
        Levels().validate_output(_result(has_audio=False, audio_codec=None), "mp3", True, tmp_path, tmp_path)
    assert exc.value.code == ErrorCode.AUDIO_MISSING


def test_mp3_left_in_mp4_is_a_compatibility_error(tmp_path):
    with pytest.raises(AppError) as exc:
        Levels(-5.0).validate_output(_result(audio_codec="mp3"), "mp3", False, tmp_path, tmp_path)
    assert exc.value.code == ErrorCode.MP4_COMPATIBILITY


def test_silent_output_from_audible_source_is_a_conversion_failure(tmp_path):
    with pytest.raises(AppError) as exc:
        Levels(float("-inf"), -3.0).validate_output(_result(), "mp3", True, tmp_path, tmp_path)
    assert exc.value.code == ErrorCode.AUDIO_CONVERSION_FAILED


def test_undecodable_output_audio(tmp_path):
    with pytest.raises(AppError) as exc:
        Levels(None).validate_output(_result(), "aac", False, tmp_path, tmp_path)
    assert exc.value.code == ErrorCode.MP4_COMPATIBILITY


def test_start_offset_is_a_sync_failure(tmp_path):
    with pytest.raises(AppError) as exc:
        Levels(-5.0).validate_output(_result(audio_start=1.2), "aac", False, tmp_path, tmp_path)
    assert exc.value.code == ErrorCode.AV_SYNC_FAILED


def test_single_file_sync_is_not_second_guessed(tmp_path):
    assert Levels(-5.0).validate_output(_result(audio_duration=4.0), "aac", False, tmp_path, tmp_path, merged=False) is False


# ------------------------------------------------------- selection labels
def _fmt(fid, **kw):
    return MediaFormat(format_id=fid, ext="mp4", protocol="https", **kw)


def tiktok_like_entry():
    """Mirrors the reported episode: HEVC 720p video-only + MP3 audio, and H.264 576p with AAC."""
    return VideoEntry(index=1, formats=(
        _fmt("audio", vcodec="none", acodec="mp3", has_video=False, has_audio=True, filesize=1856618),
        _fmt("bytevc1_720p-0", vcodec="h265", acodec="none", width=720, height=1280, has_video=True,
             has_audio=False, filesize=7340604),
        _fmt("h264_540p-0", vcodec="h264", acodec="aac", width=576, height=1024, has_video=True,
             has_audio=True, filesize=15021086),
    ))


def test_conversion_is_labelled_and_best_keeps_720p_with_aac():
    options = build_options(tiktok_like_entry())
    best, p720, p576 = options
    assert best.is_best and best.height == 1280 and best.audio_converted
    assert "converted from MP3 to AAC" in p720.note and "not re-encoded" in p720.note
    assert not p576.audio_converted and p576.note is None


def test_best_prefers_a_resolution_with_audio_over_a_silent_higher_one():
    entry = VideoEntry(index=1, formats=(
        _fmt("v1080", vcodec="h265", acodec="none", width=1080, height=1920, has_video=True, has_audio=False),
        _fmt("v576", vcodec="h264", acodec="aac", width=576, height=1024, has_video=True, has_audio=True),
    ))
    best = build_options(entry)[0]
    assert best.height == 1024 and best.has_audio


def test_genuinely_silent_source_still_gets_best():
    entry = VideoEntry(index=1, formats=(
        _fmt("v1080", vcodec="h264", acodec="none", width=1080, height=1920, has_video=True, has_audio=False),))
    assert build_options(entry)[0].height == 1920


@pytest.mark.parametrize(("codec", "converted"), [
    ("mp3", True), ("mp4a.6b", True), ("opus", True), ("vorbis", True), ("aac", False), ("mp4a.40.2", False),
    ("ac-3", False), (None, False), ("none", False),
])
def test_audio_needs_conversion(codec, converted):
    assert audio_needs_conversion(codec) is converted


# ------------------------------------------- metadata claims audio that isn't there
def test_selection_keeps_separate_audio_as_fallback_for_claimed_embedded_audio():
    # Episode 8 of the reported series: yt-dlp labelled the HEVC streams "aac", but they were video-only.
    entry = VideoEntry(index=1, formats=(
        _fmt("audio", vcodec="none", acodec="mp3", has_video=False, has_audio=True),
        _fmt("bytevc1_1080p-0", vcodec="h265", acodec="aac", width=1080, height=1920, has_video=True, has_audio=True),
    ))
    best = build_options(entry)[0]
    assert best.audio_format_id is None and best.fallback_audio_format_id == "audio"


@needs_ffmpeg
def test_expected_audio_missing_is_an_error_not_a_silent_pass(tmp_path):
    with pytest.raises(AppError) as exc:
        MediaProcessor().assemble_mp4(video(tmp_path), None, tmp_path / "o.mp4", expect_audio=True)
    assert exc.value.code == ErrorCode.AUDIO_MISSING


@needs_ffmpeg
@needs_mp3
def test_job_adds_fallback_audio_when_the_video_has_none(tmp_path, settings):
    """End to end through JobManager with real FFmpeg: video-only file + separate MP3 -> MP4 with AAC."""
    import time as _t

    from app.jobs import DownloadPlan, JobManager, JobState
    from app.providers.base import ProgressUpdate, VideoProvider
    from app.storage import DeliveryStore
    from app.validation import validate_post_url

    v_src, a_src = video(tmp_path, name="v_src.mp4"), audio(tmp_path, "libmp3lame", name="a_src.mp3")

    class Provider(VideoProvider):
        name = "p"
        calls: list = []

        def extract(self, url):  # pragma: no cover - unused
            raise NotImplementedError

        def download(self, url, video_index, format_ids, dest_dir, on_progress):
            self.calls.append(list(format_ids))
            dest_dir.mkdir(parents=True, exist_ok=True)
            out = {}
            for fid in format_ids:
                src = a_src if fid == "audio" else v_src
                target = dest_dir / f"{fid}{src.suffix}"
                target.write_bytes(src.read_bytes())
                on_progress(ProgressUpdate(fid, "finished", target.stat().st_size, target.stat().st_size, False))
                out[fid] = target
            return out

    provider = Provider()
    option = build_options(VideoEntry(index=1, formats=(
        _fmt("audio", vcodec="none", acodec="mp3", has_video=False, has_audio=True),
        _fmt("v1080", vcodec="h264", acodec="aac", width=160, height=284, has_video=True, has_audio=True),
    )))[0]
    deliveries = DeliveryStore(settings.temp_dir, 60)
    jobs = JobManager(settings, provider, MediaProcessor(), deliveries)
    snap = jobs.submit(DownloadPlan(url=validate_post_url("https://x.com/a/status/1"), video_index=1, option=option,
                                    filename="x.mp4"))
    for _ in range(200):
        snap = jobs.get(snap.job_id)
        if snap.state in (JobState.COMPLETED, JobState.FAILED):
            break
        _t.sleep(0.05)
    assert snap.state == JobState.COMPLETED, snap.error
    assert provider.calls == [["v1080"], ["audio"]]
    assert snap.result.probe.audio_codec == "aac" and snap.result.probe.audio_converted
    jobs.shutdown()
