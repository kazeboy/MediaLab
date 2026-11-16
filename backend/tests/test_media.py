"""FFmpeg processing. Integration tests use real FFmpeg and are skipped if it is missing."""

import subprocess

import pytest

from app.errors import AppError, ErrorCode
from app.media import MediaProcessor, ProbeResult, parse_probe_output

from .conftest import HAS_FFMPEG

needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


def test_parse_probe_output():
    data = {
        "format": {"format_name": "mov,mp4,m4a", "duration": "15.55", "size": "199501"},
        "streams": [
            {"codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}},
            {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720, "avg_frame_rate": "30000/1001"},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }
    r = parse_probe_output(data)
    assert (r.width, r.height, r.video_codec, r.audio_codec) == (1280, 720, "h264", "aac")
    assert r.fps == 29.97 and r.size_bytes == 199501 and r.duration_seconds == 15.55


def test_parse_probe_output_missing_values():
    r = parse_probe_output({"format": {"duration": "N/A"}, "streams": []})
    assert r.duration_seconds is None and not r.has_video and r.width is None


def _probe(vcodec="h264", acodec=None, has_audio=False):
    return ProbeResult("mp4", 1.0, 1, 640, 360, 30.0, vcodec, acodec, vcodec is not None, has_audio)


def test_compatibility_check_rejects_reencode_cases():
    MediaProcessor.check_mp4_compatible(_probe(), _probe(None, "aac", True))
    with pytest.raises(AppError) as exc:
        MediaProcessor.check_mp4_compatible(_probe("vp8"), None)
    assert exc.value.code == ErrorCode.INCOMPATIBLE_FORMAT
    with pytest.raises(AppError) as exc:
        MediaProcessor.check_mp4_compatible(_probe(), _probe(None, "wmav2", True))
    assert exc.value.code == ErrorCode.INCOMPATIBLE_FORMAT


def test_missing_ffmpeg_reported(tmp_path):
    proc = MediaProcessor("definitely-not-ffmpeg-xyz", "definitely-not-ffprobe-xyz")
    assert proc.available() is False
    with pytest.raises(AppError) as exc:
        proc.probe(tmp_path / "x.mp4")
    assert exc.value.code == ErrorCode.FFMPEG_MISSING


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@needs_ffmpeg
def test_merge_video_only_and_audio_only_losslessly(tmp_path):
    video = tmp_path / "v.ts"
    audio = tmp_path / "a.m4a"
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(video))
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", str(audio))
    out = tmp_path / "out with spaces & $(echo injected).mp4"
    result = MediaProcessor().assemble_mp4(video, audio, out)
    assert out.is_file()
    assert (result.width, result.height) == (320, 240)  # never upscaled
    assert result.video_codec == "h264" and result.audio_codec == "aac"
    assert "mp4" in result.format_name
    assert not (tmp_path / "injected").exists()


@needs_ffmpeg
def test_single_file_without_audio(tmp_path):
    video = tmp_path / "v.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video))
    result = MediaProcessor().assemble_mp4(video, None, tmp_path / "o.mp4")
    assert result.has_video and not result.has_audio


@needs_ffmpeg
def test_incompatible_codec_is_not_transcoded(tmp_path):
    video = tmp_path / "v.mkv"
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=1", "-c:v", "mpeg2video", str(video))
    out = tmp_path / "o.mp4"
    with pytest.raises(AppError) as exc:
        MediaProcessor().assemble_mp4(video, None, out)
    assert exc.value.code == ErrorCode.INCOMPATIBLE_FORMAT
    assert not out.exists()


@needs_ffmpeg
def test_corrupt_input(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(AppError) as exc:
        MediaProcessor().assemble_mp4(bad, None, tmp_path / "o.mp4")
    assert exc.value.code == ErrorCode.PROCESSING_FAILED


def _has_hevc_encoder() -> bool:
    if not HAS_FFMPEG:
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return "libx265" in out


@pytest.mark.skipif(not _has_hevc_encoder(), reason="ffmpeg without libx265")
def test_hevc_is_tagged_hvc1_for_apple_players(tmp_path):
    video = tmp_path / "v.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=1", "-c:v", "libx265",
            "-tag:v", "hev1", "-x265-params", "log-level=error", str(video))
    out = tmp_path / "o.mp4"
    result = MediaProcessor().assemble_mp4(video, None, out)
    assert result.video_codec == "hevc"
    tag = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=codec_tag_string", "-of", "csv=p=0", str(out)], capture_output=True, text=True)
    assert tag.stdout.strip() == "hvc1"
