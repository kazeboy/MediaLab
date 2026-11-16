"""FFmpeg / FFprobe processing.

Video is never re-encoded: it is stream-copied (``-c:v copy``) into an MP4
container (HEVC tagged ``hvc1`` for Apple players). If the video codec can't be
stored in MP4, processing stops with an explicit error.

Audio is stream-copied when Apple's players can play it from MP4 (AAC, ALAC,
AC-3, E-AC-3). Other audio, notably MP3, is converted to AAC: FFmpeg can write
MP3 into MP4, but AVFoundation (QuickTime, Safari, Finder previews) ignores such
a track entirely, so the file plays silently there. Verified 2026-11-12 on a
real TikTok Short Drama episode (HEVC video + separate MP3).

Every output is checked with FFprobe and an audio decode: the audio track must
be present when the source had audio, in an Apple-playable codec, in sync with
the video, and not silent unless the source itself is silent.

Commands are always executed as argument lists (no shell), so file names can
never be interpreted as shell syntax.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path

from .errors import AppError, ErrorCode

log = logging.getLogger(__name__)

MP4_SAFE_VIDEO = frozenset({"h264", "hevc", "av1"})
# Audio Apple's players decode from an MP4 container: copied as-is.
APPLE_MP4_AUDIO = frozenset({"aac", "alac", "ac3", "eac3"})
# Audio FFmpeg decodes reliably that is converted to AAC for compatibility.
CONVERTIBLE_AUDIO = frozenset({"mp3", "mp2", "opus", "vorbis", "flac", "pcm_s16le", "pcm_s24le", "pcm_f32le"})
MP4_SAFE_AUDIO = APPLE_MP4_AUDIO | CONVERTIBLE_AUDIO  # what assemble_mp4 can turn into a playable MP4
AAC_BITRATE = "192k"  # transparent for 128-160 kb/s MP3 sources
SILENT_DB = -70.0  # max_volume at or below this counts as silence
POLL_SECONDS = 0.2  # how often a running FFmpeg/FFprobe checks for cancellation

# The cancel event of the job running on this thread (see MediaProcessor.cancellable).
_local = threading.local()


def cancelled_error() -> AppError:
    return AppError(ErrorCode.DOWNLOAD_CANCELLED, "The download was cancelled.", retryable=False)


@dataclass(frozen=True)
class ProbeResult:
    format_name: str | None
    duration_seconds: float | None
    size_bytes: int | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    has_video: bool
    has_audio: bool
    video_duration: float | None = None
    audio_duration: float | None = None
    video_start: float | None = None
    audio_start: float | None = None
    audio_channels: int | None = None
    audio_sample_rate: int | None = None
    audio_converted: bool = False  # set by assemble_mp4 when the audio was transcoded to AAC
    source_audio_codec: str | None = None
    audio_silent: bool = False  # the source's audio is genuinely silent

def _parse_fps(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "0"):
        return None
    try:
        value = float(Fraction(rate))
    except (ValueError, ZeroDivisionError):
        return None
    return round(value, 3) if value > 0 else None


def parse_probe_output(data: dict) -> ProbeResult:
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    def _num(value, cast):
        try:
            return cast(value) if value not in (None, "", "N/A") else None
        except (TypeError, ValueError):
            return None

    return ProbeResult(
        format_name=fmt.get("format_name"),
        duration_seconds=_num(fmt.get("duration"), float),
        size_bytes=_num(fmt.get("size"), int),
        width=_num(video.get("width"), int) if video else None,
        height=_num(video.get("height"), int) if video else None,
        fps=_parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")) if video else None,
        video_codec=video.get("codec_name") if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        has_video=video is not None,
        has_audio=audio is not None,
        video_duration=_num(video.get("duration"), float) if video else None,
        audio_duration=_num(audio.get("duration"), float) if audio else None,
        video_start=_num(video.get("start_time"), float) if video else None,
        audio_start=_num(audio.get("start_time"), float) if audio else None,
        audio_channels=_num(audio.get("channels"), int) if audio else None,
        audio_sample_rate=_num(audio.get("sample_rate"), int) if audio else None,
    )


class MediaProcessor:
    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe", timeout_seconds: int = 600) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.timeout_seconds = timeout_seconds

    def available(self) -> bool:
        return shutil.which(self.ffmpeg_path) is not None and shutil.which(self.ffprobe_path) is not None

    def require(self) -> tuple[str, str]:
        ffmpeg, ffprobe = shutil.which(self.ffmpeg_path), shutil.which(self.ffprobe_path)
        if not ffmpeg or not ffprobe:
            raise AppError(
                ErrorCode.FFMPEG_MISSING,
                "FFmpeg/FFprobe were not found. Install them (e.g. `brew install ffmpeg`) and restart MediaLab.",
            )
        return ffmpeg, ffprobe

    @staticmethod
    @contextmanager
    def cancellable(event: threading.Event):
        """Make every FFmpeg/FFprobe call on this thread stop (process killed) once ``event`` is set."""
        previous = getattr(_local, "cancel", None)
        _local.cancel = event
        try:
            yield
        finally:
            _local.cancel = previous

    def run(self, args: list[str], what: str) -> subprocess.CompletedProcess:
        cancel: threading.Event | None = getattr(_local, "cancel", None)
        if cancel is not None and cancel.is_set():
            raise cancelled_error()
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    stdin=subprocess.DEVNULL, text=True)
        except OSError as exc:
            raise AppError(ErrorCode.PROCESSING_FAILED, f"The video downloaded, but MP4 processing failed: "
                           f"{what.lower()} could not be started.") from exc
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                out, err = proc.communicate(timeout=POLL_SECONDS)
                return subprocess.CompletedProcess(args, proc.returncode, out, err)
            except subprocess.TimeoutExpired:
                stop = "cancel" if cancel is not None and cancel.is_set() else (
                    "timeout" if time.monotonic() > deadline else None)
                if stop is None:
                    continue
                proc.kill()
                proc.communicate()
                if stop == "cancel":
                    log.info("%s stopped: the download was cancelled", what)
                    raise cancelled_error() from None
                raise AppError(ErrorCode.PROCESSING_FAILED, f"The video downloaded, but MP4 processing failed: "
                               f"{what.lower()} took too long and was stopped.", retryable=True) from None
            except BaseException:
                proc.kill()
                proc.communicate()
                raise

    def probe(self, path: Path) -> ProbeResult:
        _, ffprobe = self.require()
        proc = self.run(
            # Absolute paths can never be mistaken for command-line options.
            [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path.resolve())],
            "Inspecting the media file",
        )
        if proc.returncode != 0:
            log.info("ffprobe failed: %s", proc.stderr.strip()[:500])
            raise AppError(ErrorCode.PROCESSING_FAILED, "The video downloaded, but FFprobe couldn't read the file. "
                           "It may be incomplete or corrupt.", retryable=True)
        try:
            return parse_probe_output(json.loads(proc.stdout or "{}"))
        except json.JSONDecodeError as exc:
            raise AppError(ErrorCode.PROCESSING_FAILED, "The video downloaded, but FFprobe returned unreadable "
                           "information about it.") from exc

    @staticmethod
    def check_mp4_compatible(video: ProbeResult, audio: ProbeResult | None) -> None:
        if not video.has_video:
            raise AppError(ErrorCode.PROCESSING_FAILED, "The download finished, but FFprobe found no video stream in it.")
        if video.video_codec not in MP4_SAFE_VIDEO:
            raise AppError(
                ErrorCode.INCOMPATIBLE_FORMAT,
                f"The video codec ({video.video_codec or 'unknown'}) cannot be stored in MP4 without re-encoding the "
                "video. MediaLab doesn't re-encode video; choose another resolution.",
            )
        audio_codec = audio.audio_codec if audio is not None else video.audio_codec
        if audio_codec is not None and audio_codec not in MP4_SAFE_AUDIO:
            raise AppError(
                ErrorCode.INCOMPATIBLE_FORMAT,
                f"The audio codec ({audio_codec}) isn't one MediaLab can store or convert for MP4. "
                "Choose another resolution.",
            )

    def max_volume_db(self, path: Path, stream: str = "0:a:0") -> float | None:
        """Decode the audio and return its peak level in dB (None if it can't be decoded)."""
        ffmpeg, _ = self.require()
        proc = self.run([ffmpeg, "-nostdin", "-hide_banner", "-i", str(path.resolve()), "-map", stream,
                          "-af", "volumedetect", "-vn", "-sn", "-f", "null", "-"], "Checking the audio")
        if proc.returncode != 0:
            log.info("audio decode failed: %s", proc.stderr.strip()[-500:])
            return None
        for line in proc.stderr.splitlines():
            if "max_volume:" in line:
                value = line.split("max_volume:")[1].strip().split(" ")[0]
                return float("-inf") if value in ("-inf", "-nan") else float(value)
        return None

    def assemble_mp4(self, video_path: Path, audio_path: Path | None, output_path: Path,
                     expect_audio: bool = False) -> ProbeResult:
        """Copy the video (+ optional separate audio) into a faststart MP4 that Apple players can play.

        Video is always stream-copied. Audio is copied when it's AAC/ALAC/AC-3/E-AC-3,
        otherwise converted to AAC. The result is then validated (see module docstring).
        """
        ffmpeg, _ = self.require()
        video_info = self.probe(video_path)
        audio_info = self.probe(audio_path) if audio_path is not None else None
        if audio_info is not None and not audio_info.has_audio:
            raise AppError(ErrorCode.AUDIO_MISSING, "The download finished, but the separate audio file contains no "
                           "audio stream.", retryable=True)
        self.check_mp4_compatible(video_info, audio_info)

        source = audio_info if audio_info is not None else video_info
        source_audio = source.audio_codec if source.has_audio else None
        if expect_audio and source_audio is None:
            raise AppError(ErrorCode.AUDIO_MISSING, "The source said this video has sound, but the downloaded file "
                           "has no audio track (and no trustworthy separate audio was available), so it wasn't "
                           "saved silently.", retryable=True)
        convert = source_audio is not None and source_audio not in APPLE_MP4_AUDIO

        args = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_path.resolve())]
        if audio_path is not None:
            args += ["-i", str(audio_path.resolve()), "-map", "0:v:0", "-map", "1:a:0"]
        else:
            args += ["-map", "0:v:0", "-map", "0:a:0?"]
        args += ["-c:v", "copy"]
        if video_info.video_codec == "hevc":
            args += ["-tag:v", "hvc1"]  # Apple players (QuickTime/Safari) only play HEVC tagged hvc1
        if convert:
            args += ["-c:a", "aac", "-b:a", AAC_BITRATE]
        elif source_audio is not None:
            args += ["-c:a", "copy"]
        args += ["-movflags", "+faststart", "-f", "mp4", str(output_path.resolve())]

        proc = self.run(args, "Converting the audio" if convert else "Combining the streams")
        if proc.returncode != 0 or not output_path.is_file():
            log.info("ffmpeg failed: %s", proc.stderr.strip()[:1000])
            if convert:
                raise AppError(ErrorCode.AUDIO_CONVERSION_FAILED, f"The video downloaded, but converting its "
                               f"{source_audio.upper()} audio to AAC failed.", retryable=True)
            raise AppError(ErrorCode.PROCESSING_FAILED, "The video downloaded, but MP4 processing failed "
                           "(FFmpeg could not create the MP4 file).", retryable=True)
        result = self.probe(output_path)
        silent = self.validate_output(result, source_audio, convert, output_path,
                                      audio_path if audio_path is not None else video_path,
                                      merged=audio_path is not None)
        return replace(result, audio_converted=convert, source_audio_codec=source_audio, audio_silent=silent)

    def validate_output(self, result: ProbeResult, source_audio: str | None, converted: bool,
                        output_path: Path, source_path: Path, merged: bool = True) -> bool:
        """Raise if the MP4 isn't playable with working audio. Returns True if the source audio is silent."""
        if not result.has_video:
            raise AppError(ErrorCode.PROCESSING_FAILED, "The resulting MP4 contains no video stream.")
        if source_audio is None:
            return False  # genuinely video-only source
        if not result.has_audio:
            raise AppError(ErrorCode.AUDIO_MISSING, "The source has audio, but the finished MP4 has no audio track "
                           "(stream mapping failed).", retryable=True)
        if result.audio_codec not in APPLE_MP4_AUDIO:
            raise AppError(ErrorCode.MP4_COMPATIBILITY, f"The finished MP4's audio ({result.audio_codec}) wouldn't "
                           "play in QuickTime or Safari.", retryable=False)
        # Sync is MediaLab's responsibility when it combines separate streams; a single
        # source file's own audio/video relationship is preserved by stream copy.
        v, a = result.video_duration, result.audio_duration
        if merged and v and a and abs(v - a) > max(1.0, 0.05 * v):
            raise AppError(ErrorCode.AV_SYNC_FAILED, f"The audio ({a:.1f} s) and video ({v:.1f} s) lengths don't "
                           "match, so they would drift out of sync.", retryable=True, details={"video_seconds": round(v, 2), "audio_seconds": round(a, 2)})
        if (merged and result.video_start is not None and result.audio_start is not None
                and abs(result.video_start - result.audio_start) > 0.5):
            raise AppError(ErrorCode.AV_SYNC_FAILED, "The audio and video start at different times in the finished "
                           "MP4.", retryable=True)
        out_peak = self.max_volume_db(output_path)
        if out_peak is None:
            raise AppError(ErrorCode.AUDIO_CONVERSION_FAILED if converted else ErrorCode.MP4_COMPATIBILITY,
                           "The finished MP4's audio track can't be decoded.", retryable=True)
        if out_peak > SILENT_DB:
            return False
        # Output is silent: acceptable only if the source audio is silent too.
        src_peak = self.max_volume_db(source_path)
        if src_peak is not None and src_peak <= SILENT_DB:
            log.info("Source audio is silent (peak %s dB); keeping the silent track", src_peak)
            return True
        raise AppError(ErrorCode.AUDIO_CONVERSION_FAILED if converted else ErrorCode.AUDIO_MISSING,
                       "The source audio has sound, but the finished MP4's audio is silent.", retryable=True)
