"""Resolution option discovery and Best Available selection.

Options are derived only from formats the provider actually reported. A
resolution is offered only if it can be downloaded directly or assembled from
real streams. Video is never re-encoded and nothing is upscaled; options whose
*video* would need re-encoding are listed as not downloadable. Audio that Apple
players can't play from MP4 (e.g. MP3) is converted to AAC, and such options say so
(``audio_converted``). Best Available is the highest resolution that is
downloadable *with audio* whenever the source has audio.
"""

from __future__ import annotations

from collections import defaultdict

from .errors import AppError, ErrorCode
from .models import MediaFormat, ResolutionOption, VideoEntry

BEST_OPTION_ID = "best"

# Codec families that MP4 can carry as-is (yt-dlp/RFC 6381 style names and
# FFprobe names). Deliberately conservative: these play in common players.
MP4_VIDEO_CODECS = frozenset({"avc1", "avc3", "h264", "hev1", "hvc1", "h265", "hevc", "av01", "av1"})
MP4_AUDIO_CODECS = frozenset({"mp4a", "aac", "mp3", "mp4a.6b", "ac-3", "ac3", "ec-3", "eac3", "alac",
                              "opus", "vorbis", "flac"})
# Audio copied as-is into MP4 (Apple players decode it); everything else in MP4_AUDIO_CODECS is converted to AAC.
APPLE_AUDIO_CODECS = frozenset({"mp4a", "aac", "ac-3", "ac3", "ec-3", "eac3", "alac"})
MP4_CONTAINER_EXTS = frozenset({"mp4", "m4v", "m4a", "mov"})


def codec_family(codec: str | None) -> str | None:
    if not codec or codec == "none":
        return None
    return codec.strip().lower().split(".")[0]


def video_codec_mp4_ok(codec: str | None) -> bool | None:
    family = codec_family(codec)
    if family is None:
        return None
    return family in MP4_VIDEO_CODECS


def audio_codec_mp4_ok(codec: str | None) -> bool | None:
    family = codec_family(codec)
    if family is None:
        return None
    return family in MP4_AUDIO_CODECS


def audio_needs_conversion(codec: str | None) -> bool:
    family = codec_family(codec)
    if family is None:
        return False
    if (codec or "").lower().startswith("mp4a.6b") or (codec or "").lower().startswith("mp4a.69"):
        return True  # MP3 signalled with an MP4 object type
    return family in MP4_AUDIO_CODECS and family not in APPLE_AUDIO_CODECS


def format_mp4_compatibility(fmt: MediaFormat) -> bool | None:
    """Can this format go into an MP4 without re-encoding? None if unknown."""
    checks: list[bool | None] = []
    if fmt.has_video is not False:
        checks.append(video_codec_mp4_ok(fmt.vcodec))
    if fmt.has_audio is not False:
        checks.append(audio_codec_mp4_ok(fmt.acodec))
    if any(c is False for c in checks):
        return False
    if checks and all(c is True for c in checks):
        return True
    # Codecs unknown: an MP4 file from the source is already MP4.
    if fmt.ext in MP4_CONTAINER_EXTS and (fmt.protocol or "").startswith("http") and fmt.protocol != "http_dash_segments":
        return True
    return None


def resolution_label(width: int | None, height: int | None) -> str | None:
    """Human label based on the short side (so 720x1280 portrait is 720p)."""
    short = short_side(width, height)
    if short is None:
        return None
    label = f"{short}p"
    if short >= 4320:
        return f"{label} (8K)"
    if short >= 2160:
        return f"{label} (4K)"
    return label


def short_side(width: int | None, height: int | None) -> int | None:
    if width and height:
        return min(width, height)
    return height or None


def _sum_or_none(values: list[int | None]) -> int | None:
    if any(v is None for v in values):
        return None
    return sum(v for v in values if v is not None)


def _audio_rank(fmt: MediaFormat) -> tuple:
    return (fmt.tbr or 0, fmt.filesize or fmt.filesize_approx or 0)


def _compat_rank(value: bool | None) -> int:
    return {True: 2, None: 1, False: 0}[value]


def _build_candidate(video: MediaFormat, audio: MediaFormat | None,
                     fallback_audio: MediaFormat | None = None) -> tuple[ResolutionOption, bool | None]:
    v_ok = format_mp4_compatibility(video)
    if audio is not None:
        a_ok = format_mp4_compatibility(audio)
        compat: bool | None
        if v_ok is False or a_ok is False:
            compat = False
        elif v_ok is True and a_ok is True:
            compat = True
        else:
            compat = None
        exact = _sum_or_none([video.filesize, audio.filesize])
        approx = _sum_or_none(
            [video.filesize or video.filesize_approx, audio.filesize or audio.filesize_approx]
        )
        tbr = (video.tbr + audio.tbr) if video.tbr and audio.tbr else None
        acodec, has_audio = audio.acodec, True
    else:
        compat = v_ok
        exact = video.filesize
        approx = video.filesize_approx
        tbr = video.tbr
        acodec, has_audio = video.acodec, video.has_audio

    note = None
    downloadable = True
    if compat is False:
        downloadable = False
        bad = []
        if video_codec_mp4_ok(video.vcodec) is False:
            bad.append(f"video codec {video.vcodec}")
        audio_codec = audio.acodec if audio else video.acodec
        if audio_codec_mp4_ok(audio_codec) is False:
            bad.append(f"audio codec {audio_codec}")
        note = f"Not available as MP4 without re-encoding ({', '.join(bad) or 'incompatible codec'})."
    elif compat is None:
        note = "Codec not reported by source; it will be verified after download."
    if has_audio is False:
        note = (note + " " if note else "") + "No audio track."
    converted = bool(has_audio) and audio_needs_conversion(acodec)
    if converted and downloadable:
        note = (note + " " if note else "") + (
            f"Audio converted from {codec_family(acodec).upper()} to AAC for compatibility; video is not re-encoded."
        )

    option = ResolutionOption(
        option_id="",
        label="",
        width=video.width,
        height=video.height,
        fps=video.fps,
        vcodec=video.vcodec,
        acodec=acodec if acodec != "none" else None,
        has_audio=has_audio,
        video_format_id=video.format_id,
        audio_format_id=audio.format_id if audio else None,
        requires_merge=audio is not None,
        tbr=tbr,
        filesize=exact,
        filesize_approx=approx if exact is None else None,
        downloadable=downloadable,
        audio_converted=converted,
        # Metadata can claim embedded audio that isn't there (seen on TikTok HEVC streams);
        # keep the source's separate audio as a fallback for that case.
        fallback_audio_format_id=fallback_audio.format_id if audio is None and fallback_audio is not None else None,
        note=note,
    )
    return option, compat


def build_options(video: VideoEntry, max_size_bytes: int | None = None) -> list[ResolutionOption]:
    """Return the resolution options for a video, Best Available first.

    One option is produced per distinct resolution (short side). For each
    resolution the best candidate is chosen: MP4-compatible first, then the
    highest bitrate, then the fewest streams.
    """
    video_formats = [f for f in video.formats if f.has_video is not False and (f.has_video or f.width or f.height)]
    audio_formats = [f for f in video.formats if f.has_video is False and f.has_audio]

    compatible_audio = [a for a in audio_formats if format_mp4_compatibility(a) is not False]
    best_audio = max(compatible_audio, key=_audio_rank) if compatible_audio else None
    if best_audio is None and audio_formats:
        best_audio = max(audio_formats, key=_audio_rank)  # will be marked incompatible

    groups: dict[int | None, list[tuple[ResolutionOption, bool | None]]] = defaultdict(list)
    for fmt in video_formats:
        audio = best_audio if fmt.has_audio is False else None
        groups[short_side(fmt.width, fmt.height)].append(_build_candidate(fmt, audio, best_audio))

    chosen: list[ResolutionOption] = []
    for candidates in groups.values():
        best, _ = max(
            candidates,
            key=lambda pair: (_compat_rank(pair[1]), pair[0].tbr or 0, -len(pair[0].format_ids)),
        )
        chosen.append(best)

    chosen.sort(key=lambda c: (short_side(c.width, c.height) or 0, c.tbr or 0), reverse=True)

    options: list[ResolutionOption] = []
    used_ids: set[str] = set()
    for c in chosen:
        label = resolution_label(c.width, c.height)
        if label is None:
            label = f"Unknown resolution ({c.video_format_id})"
            base_id = "fmt-" + "".join(ch if ch.isalnum() else "-" for ch in c.video_format_id.lower())[:24]
        else:
            base_id = f"{short_side(c.width, c.height)}p"
        option_id, n = base_id, 2
        while option_id in used_ids or option_id == BEST_OPTION_ID:
            option_id, n = f"{base_id}-{n}", n + 1
        used_ids.add(option_id)
        options.append(c.model_copy(update={"option_id": option_id, "label": label}))
    return apply_size_limit(options, max_size_bytes)


def apply_size_limit(options: list[ResolutionOption], max_size_bytes: int | None) -> list[ResolutionOption]:
    """Mark options whose exact size exceeds the limit and (re)compute Best Available.

    Accepts the output of :func:`build_options` made with any earlier limit, so a
    stored analysis can be re-evaluated when the size limit setting changes.
    Only exact sizes are grounds for blocking; estimates are checked while downloading.
    """
    base: list[ResolutionOption] = []
    for o in options:
        if o.is_best:
            continue
        if o.too_large:  # undo an earlier limit
            o = o.model_copy(update={"downloadable": True, "too_large": False, "note": o.base_note})
        base.append(o)

    out: list[ResolutionOption] = []
    for o in base:
        if max_size_bytes is not None and o.downloadable and o.filesize is not None and o.filesize > max_size_bytes:
            limit_note = f"Larger than the {max_size_bytes // (1024 * 1024)} MB size limit (change it in Settings)."
            o = o.model_copy(update={"downloadable": False, "too_large": True, "base_note": o.note, "note": limit_note})
        out.append(o)

    # Best Available: the highest downloadable option with audio when the source has audio at all.
    with_audio = [o for o in out if o.downloadable and o.has_audio is not False]
    best = with_audio[0] if with_audio else next((o for o in out if o.downloadable), None)
    if best is not None:
        out.insert(
            0,
            best.model_copy(update={"option_id": BEST_OPTION_ID, "label": f"Best Available ({best.label})", "is_best": True}),
        )
    return out


def resolve_option(options: list[ResolutionOption], option_id: str) -> ResolutionOption:
    """Find the option the user picked; raise a clear error if it cannot be used."""
    for option in options:
        if option.option_id == option_id:
            if option.too_large:
                raise AppError(ErrorCode.FILE_TOO_LARGE, option.note or "This option exceeds the size limit.")
            if not option.downloadable:
                raise AppError(ErrorCode.INCOMPATIBLE_FORMAT, option.note or "This option cannot be saved as MP4.")
            return option
    if option_id == BEST_OPTION_ID:
        if options and all(o.too_large for o in options if not o.downloadable) and any(o.too_large for o in options):
            raise AppError(ErrorCode.FILE_TOO_LARGE, "Every resolution of this video exceeds the size limit (change it in Settings).")
        raise AppError(ErrorCode.INCOMPATIBLE_FORMAT, "No format of this video can be saved as MP4 without re-encoding.")
    raise AppError(ErrorCode.INVALID_SELECTION, "That resolution is not available for this video.")


def choose_option(options: list[ResolutionOption], quality: str, strict: bool = False,
                  above: str = "best") -> tuple[ResolutionOption, str | None]:
    """Pick an option for a batch: ``"best"`` or a preferred short side such as ``"720p"``.

    Fallback when the preferred resolution isn't offered (and ``strict`` is off):
    the highest downloadable resolution *below* it; if there is none, Best Available
    (``above="best"``, Short Drama) or the *closest* higher resolution (``above="closest"``,
    bulk X/TikTok downloads). Nothing is ever upscaled: every option is a resolution the
    source really offers. Options with audio are preferred whenever the source has audio.
    Returns the option and a note describing any fallback.
    """
    if quality == BEST_OPTION_ID:
        return resolve_option(options, BEST_OPTION_ID), None
    try:
        wanted = int(quality.rstrip("p"))
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown quality preference.") from exc
    usable = [o for o in options if not o.is_best and o.downloadable]
    exact = [o for o in usable if short_side(o.width, o.height) == wanted]
    if exact:
        return exact[0], None
    if strict:
        offered = ", ".join(o.label for o in usable) or "none"
        raise AppError(ErrorCode.PREFERRED_RESOLUTION_UNAVAILABLE,
                       f"{wanted}p isn't available for this episode (offered: {offered}).")
    lower = [o for o in usable if (short_side(o.width, o.height) or 0) < wanted]
    with_audio = [o for o in lower if o.has_audio is not False] or lower
    if with_audio:
        pick = with_audio[0]
        return pick, f"{wanted}p isn't available; used {pick.label}, the next lower resolution."
    if above == "closest":
        higher = sorted((o for o in usable if (short_side(o.width, o.height) or 0) > wanted),
                        key=lambda o: short_side(o.width, o.height) or 0)
        higher = [o for o in higher if o.has_audio is not False] or higher
        if higher:
            pick = higher[0]
            return pick, f"{wanted}p isn't available and nothing lower is; used {pick.label}, the closest offered."
    best = resolve_option(options, BEST_OPTION_ID)
    return best, f"{wanted}p isn't available; used {best.label}."
