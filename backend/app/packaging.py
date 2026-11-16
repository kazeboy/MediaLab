"""Packaging several finished episodes into one file: a ZIP archive or one merged MP4.

ZIP
    MP4s are stored uncompressed (``ZIP_STORED``: video doesn't compress further) and streamed
    into the archive in 1 MiB chunks (never loaded into memory). Entry names are MediaLab's
    own sanitised episode filenames. The archive is verified (CRC of every entry) before the
    episode files are deleted, so a failed archive can be rebuilt without re-downloading.

Merged MP4
    *Stream copy* (no re-encoding) is used only when every input has the same video codec,
    codec configuration (extradata), resolution, frame rate, pixel format, time base and the
    same audio codec, configuration, sample rate and channels, with audio and video aligned.
    That is exactly what QuickTime needs for one ``hvc1``/``avc1`` sample description.
    Otherwise the inputs are *normalised*: H.264 (CRF 20) + AAC 192 kb/s, at the smallest
    input's dimensions (never upscaled, aspect preserved with padding), the highest input
    frame rate, and each episode's audio padded/trimmed to its own video length so sync
    can't drift across episode boundaries. Episodes without audio get matching silence.

    The result is verified, not assumed: FFprobe codecs and durations, a full decode with
    no errors, and audible audio inside *every* episode's segment whose source was audible
    (the v1.3 silent-audio regression class).

FFmpeg runs as a cancellable subprocess (argument list, no shell) with progress reporting.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import shutil
import subprocess
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .errors import AppError, ErrorCode
from .media import APPLE_MP4_AUDIO, SILENT_DB, MediaProcessor

log = logging.getLogger(__name__)

Progress = Callable[[float], None]  # 0..100
CHUNK = 1024 * 1024
SYNC_TOLERANCE = 0.5  # seconds between an input's audio and video length for stream-copy joining
SEGMENT_MARGIN = 0.25  # seconds ignored at each episode boundary when checking audio
X264_CRF = "20"
X264_PRESET = "fast"


def _cancelled() -> AppError:
    return AppError(ErrorCode.BATCH_CANCELLED, "Processing was cancelled.", retryable=False)


# --------------------------------------------------------------------- probing
@dataclass(frozen=True)
class StreamInfo:
    path: Path
    vcodec: str | None
    vprofile: str | None
    width: int | None
    height: int | None
    pix_fmt: str | None
    fps: str | None  # rational, e.g. "24/1"
    v_time_base: str | None
    v_extradata: str | None  # md5 of the codec configuration
    acodec: str | None
    aprofile: str | None
    sample_rate: int | None
    channels: int | None
    a_extradata: str | None
    v_duration: float | None
    a_duration: float | None
    v_start: float | None
    a_start: float | None
    duration: float | None

    @property
    def has_audio(self) -> bool:
        return self.acodec is not None

    @property
    def length(self) -> float:
        return self.v_duration or self.duration or 0.0


def _f(value) -> float | None:
    try:
        return float(value) if value not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        return None


def _i(value) -> int | None:
    try:
        return int(value) if value not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        return None


def probe_streams(processor: MediaProcessor, path: Path) -> StreamInfo:
    _, ffprobe = processor.require()
    proc = processor.run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                           "-show_data", str(path.resolve())], "Inspecting an episode")
    if proc.returncode != 0:
        raise AppError(ErrorCode.MERGE_INCOMPATIBLE, f"FFprobe couldn't read {path.name}; it may be corrupt.",
                       retryable=True)
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None:
        raise AppError(ErrorCode.MERGE_INCOMPATIBLE, f"{path.name} has no video stream.")

    def md5(s):
        ex = (s or {}).get("extradata")
        return hashlib.md5(ex.encode()).hexdigest() if ex else None

    return StreamInfo(
        path=path, vcodec=v.get("codec_name"), vprofile=v.get("profile"), width=_i(v.get("width")),
        height=_i(v.get("height")), pix_fmt=v.get("pix_fmt"), fps=v.get("r_frame_rate"),
        v_time_base=v.get("time_base"), v_extradata=md5(v),
        acodec=a.get("codec_name") if a else None, aprofile=a.get("profile") if a else None,
        sample_rate=_i(a.get("sample_rate")) if a else None, channels=_i(a.get("channels")) if a else None,
        a_extradata=md5(a), v_duration=_f(v.get("duration")), a_duration=_f(a.get("duration")) if a else None,
        v_start=_f(v.get("start_time")), a_start=_f(a.get("start_time")) if a else None,
        duration=_f((data.get("format") or {}).get("duration")),
    )


def copy_incompatibility(infos: list[StreamInfo]) -> str | None:
    """Why these inputs can't be joined by stream copy (None if they can)."""
    first = infos[0]
    names = {"vcodec": "video codec", "vprofile": "video profile", "width": "width", "height": "height",
             "pix_fmt": "pixel format", "fps": "frame rate", "v_time_base": "video time base",
             "v_extradata": "video codec configuration", "acodec": "audio codec", "aprofile": "audio profile",
             "sample_rate": "audio sample rate", "channels": "audio channels",
             "a_extradata": "audio codec configuration"}
    for info in infos[1:]:
        for key, label in names.items():
            if getattr(info, key) != getattr(first, key):
                return f"{label} differs ({getattr(first, key)} vs {getattr(info, key)} in {info.path.name})"
    for info in infos:
        if info.vcodec not in ("h264", "hevc"):
            return f"{info.path.name} uses {info.vcodec} video"
        if info.has_audio and info.acodec not in APPLE_MP4_AUDIO:
            return f"{info.path.name} has {info.acodec} audio"
        if info.has_audio and info.v_duration and info.a_duration and abs(info.v_duration - info.a_duration) > SYNC_TOLERANCE:
            return f"audio and video lengths differ in {info.path.name}"
        if (info.v_start or 0) > 0.1 or (info.a_start or 0) > 0.1:
            return f"{info.path.name} doesn't start at time zero"
    if len({i.has_audio for i in infos}) > 1:
        return "some episodes have audio and others don't"
    return None


# ------------------------------------------------------------------ subprocess
def run_ffmpeg(args: list[str], *, cancel: threading.Event, total_seconds: float | None, progress: Progress,
               timeout: float, what: str, error_code: ErrorCode) -> None:
    """Run FFmpeg with ``-progress``; kill it if cancelled or too slow.

    A watchdog thread enforces cancel and timeout every 0.2 s, independently of
    FFmpeg's output, so a stalled FFmpeg (e.g. a blocked input) can't hang the batch.
    """
    proc = subprocess.Popen([*args[:1], "-progress", "pipe:1", "-nostats", *args[1:]], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, bufsize=1)
    errors: list[str] = []
    stop_reason: list[str] = []
    reader = threading.Thread(target=lambda: errors.extend(proc.stderr.readlines()), daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout

    def watchdog() -> None:
        while proc.poll() is None:
            if cancel.is_set() or time.monotonic() > deadline:
                stop_reason.append("cancel" if cancel.is_set() else "timeout")
                proc.kill()
                return
            time.sleep(0.2)

    guard = threading.Thread(target=watchdog, daemon=True)
    guard.start()
    try:
        for line in proc.stdout:  # key=value lines; ends when FFmpeg exits or is killed
            if line.startswith("out_time_us=") and total_seconds:
                us = _i(line.split("=", 1)[1].strip())
                if us is not None and us >= 0:
                    progress(min(99.0, 100 * us / 1e6 / total_seconds))
        proc.wait()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        guard.join(timeout=5)
        reader.join(timeout=5)
    if cancel.is_set() or stop_reason == ["cancel"]:
        raise _cancelled()
    if stop_reason == ["timeout"]:
        raise AppError(error_code, f"{what} took too long and was stopped.", retryable=True)
    if proc.returncode != 0:
        log.info("%s failed: %s", what, "".join(errors)[-1500:])
        raise AppError(error_code, f"{what} failed (FFmpeg exit code {proc.returncode}).", retryable=True)


# ------------------------------------------------------------------------- ZIP
def build_zip(items: list[tuple[Path, str]], out: Path, *, manifest: str | None, cancel: threading.Event,
              progress: Progress, delete_sources: bool = True) -> int:
    """Write ``items`` (path, archive name) into ``out``; returns its size."""
    total = sum(p.stat().st_size for p, _ in items) or 1
    done = 0
    try:
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            for path, name in items:
                if "/" in name or "\\" in name or name.startswith(".") or not name:
                    raise AppError(ErrorCode.ZIP_FAILED, "Refusing an unsafe file name in the archive.")
                info = zipfile.ZipInfo(name, date_time=time.localtime(path.stat().st_mtime)[:6])
                info.compress_type = zipfile.ZIP_STORED
                with path.open("rb") as src, zf.open(info, "w", force_zip64=True) as dst:
                    while chunk := src.read(CHUNK):
                        if cancel.is_set():
                            raise _cancelled()
                        dst.write(chunk)
                        done += len(chunk)
                        progress(min(95.0, 95 * done / total))
                if delete_sources:
                    path.unlink(missing_ok=True)  # keep peak disk use near one archive
            if manifest is not None:
                zf.writestr("MediaLab manifest.txt", manifest)
        progress(96.0)
        with zipfile.ZipFile(out) as zf:  # verify every entry's CRC
            bad = zf.testzip()
        if bad is not None:
            raise AppError(ErrorCode.ZIP_FAILED, f"The ZIP failed its integrity check ({bad}).", retryable=True)
    except AppError:
        out.unlink(missing_ok=True)
        raise
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        out.unlink(missing_ok=True)
        raise AppError(ErrorCode.ZIP_FAILED, f"Creating the ZIP failed: {exc.__class__.__name__}.", retryable=True) from exc
    progress(100.0)
    return out.stat().st_size


# ----------------------------------------------------------------------- merge
@dataclass(frozen=True)
class MergeResult:
    method: str  # "stream_copy" | "re_encoded"
    reason: str | None  # why re-encoding was needed
    duration: float
    segments: list[tuple[float, float]]  # (start, end) of each episode in the output


def _even(n: int) -> int:
    return n - (n % 2)


def _fps_value(fps: str | None) -> Fraction:
    try:
        value = Fraction(fps or "0")
        return value if value > 0 else Fraction(30)
    except (ValueError, ZeroDivisionError):
        return Fraction(30)


def merge_mp4(processor: MediaProcessor, inputs: list[Path], out: Path, *, cancel: threading.Event,
              progress: Progress, timeout: float = 6 * 3600) -> MergeResult:
    ffmpeg, _ = processor.require()
    infos = [probe_streams(processor, p) for p in inputs]
    audible = [i.has_audio and (processor.max_volume_db(i.path) or float("-inf")) > SILENT_DB for i in infos]
    reason = copy_incompatibility(infos)
    total = sum(i.length for i in infos) or None
    workdir = out.parent

    if reason is None:
        listing = workdir / "concat.txt"
        listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in inputs), encoding="utf-8")
        args = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                "-i", str(listing), "-map", "0:v:0"]
        if infos[0].has_audio:
            args += ["-map", "0:a:0"]
        args += ["-c", "copy"]
        if infos[0].vcodec == "hevc":
            args += ["-tag:v", "hvc1"]
        args += ["-movflags", "+faststart", "-f", "mp4", str(out.resolve())]
        run_ffmpeg(args, cancel=cancel, total_seconds=total, progress=lambda p: progress(p * 0.6),
                   timeout=timeout, what="Joining the episodes", error_code=ErrorCode.MERGE_FAILED)
        # The concat demuxer places each file at the previous files' total (format) duration.
        lengths = [i.duration or i.length for i in infos]
        method = "stream_copy"
    else:
        log.info("Merging with normalisation: %s", reason)
        if not has_encoder("libx264", processor.require()[0]):
            raise AppError(ErrorCode.TRANSCODE_FAILED,
                           f"These episodes need re-encoding to be joined ({reason}), but this FFmpeg build has no "
                           "libx264 encoder.", action="Install FFmpeg with libx264 (brew install ffmpeg), or download "
                           "the episodes as a ZIP instead.", retryable=False)
        w = _even(min(i.width or 0 for i in infos)) or 720
        h = _even(min(i.height or 0 for i in infos)) or 1280
        fps = max((_fps_value(i.fps) for i in infos), default=Fraction(30))
        rates = {i.sample_rate for i in infos if i.has_audio}
        sr = rates.pop() if len(rates) == 1 else 48000
        parts, labels = [], []
        for n, info in enumerate(infos):
            d = f"{info.length:.6f}"
            parts.append(f"[{n}:v:0]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                         f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps.numerator}/{fps.denominator},"
                         f"format=yuv420p,trim=duration={d},setpts=PTS-STARTPTS[v{n}]")
            if info.has_audio:
                parts.append(f"[{n}:a:0]aresample={sr}:async=1:first_pts=0,"
                             f"aformat=sample_fmts=fltp:sample_rates={sr}:channel_layouts=stereo,"
                             f"apad=whole_dur={d},atrim=duration={d},asetpts=PTS-STARTPTS[a{n}]")
            else:
                parts.append(f"anullsrc=r={sr}:cl=stereo,atrim=duration={d},asetpts=PTS-STARTPTS[a{n}]")
            labels.append(f"[v{n}][a{n}]")
        graph = ";".join(parts) + f";{''.join(labels)}concat=n={len(infos)}:v=1:a=1[v][a]"
        args = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
        for p in inputs:
            args += ["-i", str(p.resolve())]
        args += ["-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", X264_PRESET,
                 "-crf", X264_CRF, "-profile:v", "high", "-pix_fmt", "yuv420p", "-tag:v", "avc1",
                 "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-f", "mp4", str(out.resolve())]
        run_ffmpeg(args, cancel=cancel, total_seconds=total, progress=lambda p: progress(p * 0.8),
                   timeout=timeout, what="Re-encoding the episodes", error_code=ErrorCode.TRANSCODE_FAILED)
        lengths = [i.length for i in infos]
        method = "re_encoded"

    if cancel.is_set():
        raise _cancelled()
    segments, t = [], 0.0
    for length in lengths:
        segments.append((t, t + length))
        t += length
    verify_merged(processor, out, infos, audible, segments, cancel=cancel,
                  progress=lambda p: progress((60 if method == "stream_copy" else 80) + p * 0.4 * (1 if method == "stream_copy" else 0.5)))
    progress(100.0)
    return MergeResult(method, reason, t, segments)


def verify_merged(processor: MediaProcessor, out: Path, infos: list[StreamInfo], audible: list[bool],
                  segments: list[tuple[float, float]], *, cancel: threading.Event, progress: Progress) -> None:
    result = processor.probe(out)
    expected = segments[-1][1] if segments else 0.0
    if not result.has_video:
        raise AppError(ErrorCode.MERGE_FAILED, "The merged MP4 has no video stream.", retryable=True)
    if result.video_codec not in ("h264", "hevc"):
        raise AppError(ErrorCode.MP4_COMPATIBILITY, f"The merged MP4's video ({result.video_codec}) wouldn't play in "
                       "QuickTime or Safari.")
    any_audio = any(i.has_audio for i in infos)
    if any_audio and not result.has_audio:
        raise AppError(ErrorCode.AUDIO_MISSING, "The episodes have audio, but the merged MP4 has none.", retryable=True)
    if result.has_audio and result.audio_codec not in APPLE_MP4_AUDIO:
        raise AppError(ErrorCode.MP4_COMPATIBILITY, f"The merged MP4's audio ({result.audio_codec}) wouldn't play in "
                       "QuickTime or Safari.")
    tolerance = 1.0 + 0.1 * len(infos)
    v = result.video_duration or result.duration_seconds or 0.0
    if abs(v - expected) > tolerance:
        raise AppError(ErrorCode.MERGE_FAILED, f"The merged video is {v:.1f} s long, but the episodes add up to "
                       f"{expected:.1f} s.", retryable=True, details={"expected_seconds": round(expected, 2),
                                                                     "actual_seconds": round(v, 2)})
    if result.has_audio and result.audio_duration and abs(result.audio_duration - v) > tolerance:
        raise AppError(ErrorCode.AV_SYNC_FAILED, f"The merged audio ({result.audio_duration:.1f} s) and video "
                       f"({v:.1f} s) lengths don't match.", retryable=True)
    progress(20)
    # A full decode must produce no errors (catches broken timestamps and corrupt joins).
    # Allow at least the video's own length plus 10 minutes, whatever the per-step limit is.
    ffmpeg, _ = processor.require()
    decoder = MediaProcessor(processor.ffmpeg_path, processor.ffprobe_path,
                             max(processor.timeout_seconds, int(expected) + 600))
    proc = decoder.run([ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-i", str(out.resolve()),
                           "-f", "null", "-"], "Decoding the merged video")
    if cancel.is_set():
        raise _cancelled()
    if proc.returncode != 0 or proc.stderr.strip():
        log.info("merged decode errors: %s", proc.stderr.strip()[-1000:])
        raise AppError(ErrorCode.MERGE_FAILED, "The merged MP4 doesn't decode cleanly.", retryable=True)
    progress(60)
    # Audio must be audible inside every episode that had audible audio.
    for n, ((start, end), loud) in enumerate(zip(segments, audible)):
        if cancel.is_set():
            raise _cancelled()
        if not loud:
            continue
        a, b = start + SEGMENT_MARGIN, max(start + SEGMENT_MARGIN + 0.1, end - SEGMENT_MARGIN)
        peak = _segment_peak(processor, out, a, b)
        if peak is None or peak <= SILENT_DB:
            raise AppError(ErrorCode.AUDIO_MISSING, f"Episode {n + 1} of the merged MP4 is silent although its "
                           "source has sound.", retryable=True, details={"segment": n + 1})
        progress(60 + 40 * (n + 1) / len(segments))


def _segment_peak(processor: MediaProcessor, path: Path, start: float, end: float) -> float | None:
    ffmpeg, _ = processor.require()
    # Input seeking (-ss/-t before -i) decodes only this segment, so checking N episodes costs
    # about one pass over the audio instead of N passes from the start (PERF-1).
    proc = processor.run([ffmpeg, "-nostdin", "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{max(end - start, 0.1):.3f}",
                          "-i", str(path.resolve()), "-map", "0:a:0", "-af", "volumedetect", "-vn", "-f", "null", "-"],
                         "Checking the merged audio")
    for line in proc.stderr.splitlines():
        if "max_volume:" in line:
            value = line.split("max_volume:")[1].strip().split(" ")[0]
            return float("-inf") if value in ("-inf", "-nan") else float(value)
    return None


@functools.lru_cache(maxsize=8)
def has_encoder(name: str, ffmpeg: str | None = None) -> bool:
    """Whether the FFmpeg build provides an encoder (cached per binary)."""
    exe = ffmpeg or shutil.which("ffmpeg")
    if not exe:
        return False
    out = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True, check=False).stdout
    return f" {name} " in out
