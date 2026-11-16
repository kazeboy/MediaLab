"""ZIP packaging and MP4 merging with real FFmpeg on small generated fixtures."""

from __future__ import annotations

import subprocess
import threading
import zipfile
from pathlib import Path

import pytest

from app import packaging
from app.errors import AppError, ErrorCode
from app.media import MediaProcessor
from app.packaging import build_zip, copy_incompatibility, merge_mp4, probe_streams

from .conftest import HAS_FFMPEG

needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")
ENC = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout if HAS_FFMPEG else ""
needs_x265 = pytest.mark.skipif("libx265" not in ENC, reason="no libx265")
needs_x264 = pytest.mark.skipif("libx264" not in ENC, reason="no libx264")


def ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def episode(tmp: Path, name: str, *, seconds=2, size="160x284", rate=24, vcodec="libx264", audio="aac",
            freq=440, audio_offset: float | None = None) -> Path:
    """A small MP4 like MediaLab's processed episodes (AAC audio unless told otherwise)."""
    path = tmp / name
    args = ["-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}:duration={seconds}"]
    if audio:
        if audio_offset:
            args += ["-itsoffset", str(audio_offset)]
        args += ["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=44100:duration={seconds}"]
    args += ["-map", "0:v"] + (["-map", "1:a", "-c:a", audio, "-ac", "2"] if audio else [])
    args += ["-c:v", vcodec, "-pix_fmt", "yuv420p", "-g", str(rate)]
    if vcodec == "libx265":
        args += ["-tag:v", "hvc1", "-x265-params", "log-level=error"]
    ff(*args, str(path))
    return path


def frames(path: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries",
                          "stream=nb_read_packets", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return int(out.stdout.strip())


def no_cancel():
    return threading.Event()


# ------------------------------------------------------------------------ ZIP
def test_zip_contains_episodes_in_order_and_verifies(tmp_path):
    files = []
    for n in (1, 2, 3):
        p = tmp_path / f"E{n:04d}.mp4"
        p.write_bytes(bytes([n]) * (100_000 + n))
        files.append((p, f"Harbor & Crown Example 2 - E{n:02d}.mp4"))
    out = tmp_path / "out.zip"
    seen = []
    size = build_zip(files, out, manifest=None, cancel=no_cancel(), progress=seen.append, delete_sources=False)
    with zipfile.ZipFile(out) as zf:
        assert [i.filename for i in zf.infolist()] == [name for _, name in files]
        assert all(i.compress_type == zipfile.ZIP_STORED for i in zf.infolist())
        assert zf.read(files[1][1]) == bytes([2]) * 100_002
        assert zf.testzip() is None
    assert size == out.stat().st_size and seen[-1] == 100.0 and seen == sorted(seen)
    assert all(p.exists() for p, _ in files)


def test_zip_with_manifest_and_source_deletion(tmp_path):
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x" * 10)
    build_zip([(p, "Show - E01.mp4")], tmp_path / "o.zip", manifest="Not included:\n  E02  failed\n",
              cancel=no_cancel(), progress=lambda _: None)
    with zipfile.ZipFile(tmp_path / "o.zip") as zf:
        assert zf.namelist() == ["Show - E01.mp4", "MediaLab manifest.txt"]
        assert "E02" in zf.read("MediaLab manifest.txt").decode()
    assert not p.exists()


@pytest.mark.parametrize("bad", ["../escape.mp4", "a/b.mp4", "..\\x.mp4", ".hidden", ""])
def test_zip_rejects_unsafe_names(tmp_path, bad):
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    with pytest.raises(AppError) as exc:
        build_zip([(p, bad)], tmp_path / "o.zip", manifest=None, cancel=no_cancel(), progress=lambda _: None)
    assert exc.value.code == ErrorCode.ZIP_FAILED and not (tmp_path / "o.zip").exists()


def test_zip_cancellation_removes_partial_archive(tmp_path):
    p = tmp_path / "big.mp4"
    with p.open("wb") as fh:
        fh.truncate(8 * 1024 * 1024)
    cancel = threading.Event()

    def progress(pct):
        if pct > 1:
            cancel.set()
    with pytest.raises(AppError) as exc:
        build_zip([(p, "Show - E01.mp4")], tmp_path / "o.zip", manifest=None, cancel=cancel, progress=progress)
    assert exc.value.code == ErrorCode.BATCH_CANCELLED
    assert not (tmp_path / "o.zip").exists() and p.exists()  # sources kept until success


def test_large_archive_streams_with_zip64(tmp_path):
    files = []
    for n in range(3):
        p = tmp_path / f"E{n}.mp4"
        with p.open("wb") as fh:
            fh.truncate(48 * 1024 * 1024)  # sparse: 144 MB in total, written without being held in memory
        files.append((p, f"Show - E{n + 1:02d}.mp4"))
    out = tmp_path / "big.zip"
    build_zip(files, out, manifest=None, cancel=no_cancel(), progress=lambda _: None)
    with zipfile.ZipFile(out) as zf:
        assert [i.file_size for i in zf.infolist()] == [48 * 1024 * 1024] * 3


# ---------------------------------------------------------------------- merge
@needs_ffmpeg
@needs_x264
def test_two_compatible_episodes_are_joined_without_reencoding(tmp_path):
    a, b = episode(tmp_path, "a.mp4", freq=440), episode(tmp_path, "b.mp4", seconds=3, freq=660)
    out = tmp_path / "m.mp4"
    result = merge_mp4(MediaProcessor(), [a, b], out, cancel=no_cancel(), progress=lambda _: None)
    assert result.method == "stream_copy" and result.reason is None
    assert frames(out) == frames(a) + frames(b)
    assert abs(result.duration - 5.0) < 0.2 and result.segments[1][0] == pytest.approx(2.0, abs=0.1)
    probe = MediaProcessor().probe(out)
    assert probe.video_codec == "h264" and probe.audio_codec == "aac"


@needs_ffmpeg
@needs_x265
def test_three_compatible_hevc_episodes_keep_hvc1(tmp_path):
    eps = [episode(tmp_path, f"e{n}.mp4", vcodec="libx265", freq=300 + 100 * n) for n in range(3)]
    out = tmp_path / "m.mp4"
    result = merge_mp4(MediaProcessor(), eps, out, cancel=no_cancel(), progress=lambda _: None)
    assert result.method == "stream_copy"
    tag = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_tag_string",
                          "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    assert tag == "hvc1" and len(result.segments) == 3


@needs_ffmpeg
@needs_x265
@needs_x264
def test_mixed_h264_and_hevc_are_normalised_to_h264(tmp_path):
    a = episode(tmp_path, "a.mp4", vcodec="libx265")
    b = episode(tmp_path, "b.mp4", vcodec="libx264")
    result = merge_mp4(MediaProcessor(), [a, b], tmp_path / "m.mp4", cancel=no_cancel(), progress=lambda _: None)
    assert result.method == "re_encoded" and "video codec" in result.reason
    probe = MediaProcessor().probe(tmp_path / "m.mp4")
    assert probe.video_codec == "h264" and probe.audio_codec == "aac"
    assert abs(probe.video_duration - 4.0) < 0.2 and abs(probe.audio_duration - probe.video_duration) < 0.2


@needs_ffmpeg
@needs_x264
def test_different_resolutions_are_never_upscaled(tmp_path):
    big = episode(tmp_path, "big.mp4", size="320x568")
    small = episode(tmp_path, "small.mp4", size="160x284")
    result = merge_mp4(MediaProcessor(), [big, small], tmp_path / "m.mp4", cancel=no_cancel(), progress=lambda _: None)
    probe = MediaProcessor().probe(tmp_path / "m.mp4")
    assert result.method == "re_encoded" and (probe.width, probe.height) == (160, 284)


@needs_ffmpeg
@needs_x264
def test_different_frame_rates(tmp_path):
    a = episode(tmp_path, "a.mp4", rate=24)
    b = episode(tmp_path, "b.mp4", rate=30)
    result = merge_mp4(MediaProcessor(), [a, b], tmp_path / "m.mp4", cancel=no_cancel(), progress=lambda _: None)
    probe = MediaProcessor().probe(tmp_path / "m.mp4")
    assert result.method == "re_encoded" and probe.fps == 30.0 and abs(probe.video_duration - 4.0) < 0.2


@needs_ffmpeg
@needs_x264
@pytest.mark.skipif("libmp3lame" not in ENC, reason="no libmp3lame")
def test_aac_and_mp3_sources_become_aac(tmp_path):
    a = episode(tmp_path, "a.mp4", audio="aac")
    b = episode(tmp_path, "b.mov", audio="libmp3lame")
    result = merge_mp4(MediaProcessor(), [a, b], tmp_path / "m.mp4", cancel=no_cancel(), progress=lambda _: None)
    assert result.method == "re_encoded" and MediaProcessor().probe(tmp_path / "m.mp4").audio_codec == "aac"


@needs_ffmpeg
@needs_x264
def test_offset_audio_timestamps_are_normalised_and_in_sync(tmp_path):
    a = episode(tmp_path, "a.mp4")
    b = episode(tmp_path, "b.mp4", audio_offset=1.0)  # audio starts 1 s late
    info = probe_streams(MediaProcessor(), b)
    assert copy_incompatibility([probe_streams(MediaProcessor(), a), info]) is not None
    merge_mp4(MediaProcessor(), [a, b], tmp_path / "m.mp4", cancel=no_cancel(), progress=lambda _: None)
    probe = MediaProcessor().probe(tmp_path / "m.mp4")
    assert abs(probe.audio_duration - probe.video_duration) < 0.2 and abs(probe.video_duration - 4.0) < 0.2


@needs_ffmpeg
@needs_x264
def test_episode_without_audio_gets_silence_and_others_stay_audible(tmp_path):
    a = episode(tmp_path, "a.mp4")
    silent = episode(tmp_path, "b.mp4", audio=None)
    c = episode(tmp_path, "c.mp4", freq=880)
    out = tmp_path / "m.mp4"
    result = merge_mp4(MediaProcessor(), [a, silent, c], out, cancel=no_cancel(), progress=lambda _: None)
    assert result.method == "re_encoded"
    probe = MediaProcessor().probe(out)
    assert probe.has_audio and abs(probe.audio_duration - 6.0) < 0.2
    # The third episode's sound is where it belongs (after 4 s), not shifted into the silent gap.
    assert packaging._segment_peak(MediaProcessor(), out, 2.3, 3.7) <= -70
    assert packaging._segment_peak(MediaProcessor(), out, 4.3, 5.7) > -30


@needs_ffmpeg
@needs_x264
def test_silent_audio_regression_is_caught(tmp_path, monkeypatch):
    a, b = episode(tmp_path, "a.mp4"), episode(tmp_path, "b.mp4", freq=660)
    real = packaging._segment_peak
    monkeypatch.setattr(packaging, "_segment_peak",
                        lambda proc, path, s, e: float("-inf") if s > 1.5 else real(proc, path, s, e))
    with pytest.raises(AppError) as exc:
        merge_mp4(MediaProcessor(), [a, b], tmp_path / "m.mp4", cancel=no_cancel(), progress=lambda _: None)
    assert exc.value.code == ErrorCode.AUDIO_MISSING and exc.value.details == {"segment": 2}


@needs_ffmpeg
@needs_x264
def test_final_duration_mismatch_is_reported(tmp_path, monkeypatch):
    a, b = episode(tmp_path, "a.mp4"), episode(tmp_path, "b.mp4")
    proc = MediaProcessor()
    real_probe = proc.probe
    from dataclasses import replace

    monkeypatch.setattr(proc, "probe", lambda p: replace(real_probe(p), video_duration=1.0)
                        if p.name == "m.mp4" else real_probe(p))
    with pytest.raises(AppError) as exc:
        merge_mp4(proc, [a, b], tmp_path / "m.mp4", cancel=no_cancel(), progress=lambda _: None)
    assert exc.value.code == ErrorCode.MERGE_FAILED and exc.value.details["expected_seconds"] == pytest.approx(4.0, abs=0.2)


@needs_ffmpeg
@needs_x264
def test_output_is_playback_compatible(tmp_path):
    a, b = episode(tmp_path, "a.mp4"), episode(tmp_path, "b.mp4", vcodec="libx264", size="200x356")
    out = tmp_path / "m.mp4"
    merge_mp4(MediaProcessor(), [a, b], out, cancel=no_cancel(), progress=lambda _: None)
    info = probe_streams(MediaProcessor(), out)
    assert info.vcodec == "h264" and info.pix_fmt == "yuv420p" and info.acodec == "aac" and info.aprofile == "LC"
    # faststart: the index (moov) comes before the media data, as Safari streaming prefers
    head = out.read_bytes()[:4096]
    assert head.find(b"moov") != -1 and (head.find(b"mdat") == -1 or head.find(b"moov") < head.find(b"mdat"))


@needs_ffmpeg
@needs_x264
def test_cancellation_during_merging(tmp_path):
    a = episode(tmp_path, "a.mp4", seconds=4, size="640x1136")
    b = episode(tmp_path, "b.mp4", seconds=4, size="320x568")
    cancel = threading.Event()

    def progress(p):
        cancel.set()  # cancel at the first progress report
    with pytest.raises(AppError) as exc:
        merge_mp4(MediaProcessor(), [a, b], tmp_path / "m.mp4", cancel=cancel, progress=progress)
    assert exc.value.code == ErrorCode.BATCH_CANCELLED


@needs_ffmpeg
def test_input_without_video_is_incompatible(tmp_path):
    a = tmp_path / "a.m4a"
    ff("-f", "lavfi", "-i", "sine=duration=1", "-c:a", "aac", str(a))
    with pytest.raises(AppError) as exc:
        probe_streams(MediaProcessor(), a)
    assert exc.value.code == ErrorCode.MERGE_INCOMPATIBLE


# ------------------------------------------------- REL-1: stalled FFmpeg
@needs_ffmpeg
@pytest.mark.parametrize("trigger", ["cancel", "timeout"])
def test_stalled_ffmpeg_is_stopped_by_cancel_and_timeout(tmp_path, trigger):
    """An input that never delivers data makes FFmpeg print nothing; cancel/timeout must still work."""
    import os
    import shutil
    import time

    fifo = tmp_path / "stall.ts"
    os.mkfifo(fifo)
    cancel = threading.Event()
    if trigger == "cancel":
        threading.Timer(0.5, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(AppError) as exc:
        packaging.run_ffmpeg([shutil.which("ffmpeg"), "-nostdin", "-y", "-i", str(fifo), "-f", "null", "-"],
                             cancel=cancel, total_seconds=10, progress=lambda _: None,
                             timeout=60 if trigger == "cancel" else 1.0, what="Stall test",
                             error_code=ErrorCode.MERGE_FAILED)
    assert time.monotonic() - started < 5
    assert exc.value.code == (ErrorCode.BATCH_CANCELLED if trigger == "cancel" else ErrorCode.MERGE_FAILED)


@needs_ffmpeg
@needs_x264
def test_missing_libx264_gives_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(packaging, "has_encoder", lambda name, ffmpeg=None: False)
    a = episode(tmp_path, "a.mp4", size="160x284")
    b = episode(tmp_path, "b.mp4", size="200x356")  # different size -> needs re-encoding
    with pytest.raises(AppError) as exc:
        merge_mp4(MediaProcessor(), [a, b], tmp_path / "m.mp4", cancel=no_cancel(), progress=lambda _: None)
    assert exc.value.code == ErrorCode.TRANSCODE_FAILED and "libx264" in exc.value.message
    assert exc.value.retryable is False and "ZIP" in exc.value.action
