"""In-memory stores, file naming and temporary-file cleanup.

MediaLab v1 has no database. Analyses, jobs and completed files are tracked in
memory with time-to-live expiry. Files are only ever addressed by opaque IDs;
local paths never leave the server.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
import unicodedata
import uuid
from collections import OrderedDict
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from .errors import AppError, ErrorCode
from .models import PostMetadata, ResolutionOption, VideoEntry
from .validation import ValidatedUrl

log = logging.getLogger(__name__)

JOB_DIR_PREFIX = "job-"
_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def new_id() -> str:
    return uuid.uuid4().hex


def is_valid_id(value: str) -> bool:
    return bool(_ID_RE.match(value or ""))


# --------------------------------------------------------------------- naming
_FORBIDDEN_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_URLS = re.compile(r"https?://\S+")
_WHITESPACE = re.compile(r"\s+")


def sanitise_filename_part(text: str | None, max_length: int = 80) -> str:
    """Make ``text`` safe for use inside a file name on macOS/Linux/Windows."""
    if not text:
        return ""
    value = unicodedata.normalize("NFC", text)
    value = _URLS.sub("", value)
    value = _WHITESPACE.sub(" ", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co", "Cn"))
    value = _FORBIDDEN_CHARS.sub(" ", value)
    value = _WHITESPACE.sub(" ", value).strip(" .-_")
    if len(value) > max_length:
        cut = value[:max_length]
        value = (cut.rsplit(" ", 1)[0] if " " in cut[max_length // 2 :] else cut).rstrip(" .-_")
    return value


def build_filename(
    post: PostMetadata, video: VideoEntry, option: ResolutionOption, video_count: int, platform_label: str = "X"
) -> str:
    """Readable name: ``<author> - <text> [<post id>] <res>.mp4``."""
    author = sanitise_filename_part(post.author_handle or post.author_name, 40)
    text = sanitise_filename_part(post.text, 60)
    head = " - ".join(part for part in (author, text) if part) or f"{platform_label} video"
    post_id = re.sub(r"[^0-9]", "", post.post_id)[:20]
    tag = f"[{post_id}]" if post_id else ""
    if video_count > 1:
        tag = f"{tag} #{video.index}".strip()
    short = min(option.width, option.height) if option.width and option.height else option.height
    res = f"{short}p" if short else ""
    name = " ".join(part for part in (head, tag, res) if part)
    name = sanitise_filename_part(name, 150) or "video"
    return f"{name}.mp4"


def episode_filename(series_title: str | None, number: int, episode_count: int | None = None) -> str:
    """``<Series> - E01.mp4`` (zero-padded to the series length, at least two digits)."""
    title = sanitise_filename_part(series_title, 120) or "Short Drama"
    width = max(2, len(str(episode_count or 0)))
    return f"{title} - E{number:0{width}d}.mp4"


# ------------------------------------------------------------------- analyses
@dataclass
class StoredAnalysis:
    analysis_id: str
    url: ValidatedUrl
    post: PostMetadata
    options: dict[int, list[ResolutionOption]]
    provider: str
    created_at: float
    expires_at: float

    def video(self, index: int) -> VideoEntry:
        for video in self.post.videos:
            if video.index == index:
                return video
        raise AppError(ErrorCode.INVALID_SELECTION, "That video does not exist in this post.")


class AnalysisStore:
    def __init__(self, ttl_seconds: int, max_entries: int = 200) -> None:
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._items: OrderedDict[str, StoredAnalysis] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, url: ValidatedUrl, post: PostMetadata, options: dict[int, list[ResolutionOption]], provider: str) -> StoredAnalysis:
        now = time.time()
        item = StoredAnalysis(new_id(), url, post, options, provider, now, now + self.ttl)
        with self._lock:
            self._items[item.analysis_id] = item
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
        return item

    def get(self, analysis_id: str) -> StoredAnalysis:
        with self._lock:
            item = self._items.get(analysis_id)
            if item is None or item.expires_at < time.time():
                self._items.pop(analysis_id, None)
                raise AppError(ErrorCode.ANALYSIS_EXPIRED, "This analysis has expired. Please analyse the post again.")
            return item

    def prune(self, now: float | None = None) -> int:
        now = now or time.time()
        with self._lock:
            expired = [k for k, v in self._items.items() if v.expires_at < now]
            for key in expired:
                del self._items[key]
        return len(expired)


# ------------------------------------------------------------------ delivery
DELIVERY_DIR_NAME = "ready"


class DeliveryState(str, Enum):
    READY = "ready"            # finished MP4 waiting for the browser
    DELIVERING = "delivering"  # an HTTP response is streaming it right now
    DELIVERED = "delivered"    # fully sent; MediaLab's copy has been deleted
    EXPIRED = "expired"        # not saved in time; MediaLab's copy has been deleted


@dataclass
class Delivery:
    file_id: str
    path: Path
    filename: str
    size_bytes: int
    expires_at: float
    state: DeliveryState = DeliveryState.READY
    attempts: int = 0
    finished_at: float | None = None


class DeliveryStore:
    """Temporary hand-off of finished MP4s to the browser.

    * Files live in ``<temp>/ready/<random id>.mp4`` (never the display name),
      separate from partial downloads in ``<temp>/job-*/``.
    * Only one response may stream a file at a time; duplicate requests get 409.
    * A file is deleted after a response has sent every byte, or when its
      retention period ends, never while a response is still streaming.
    * An interrupted transfer returns the file to ``ready`` so the user can retry
      until it expires.
    """

    def __init__(self, temp_dir: Path, retention_seconds: int, forget_after_seconds: int = 6 * 3600) -> None:
        self.root = (temp_dir / DELIVERY_DIR_NAME).resolve()
        self.retention = retention_seconds
        self.forget_after = forget_after_seconds
        self._items: dict[str, Delivery] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------- lifecycle
    def reset(self) -> None:
        """Remove leftovers from a previous run (nothing there can be in use)."""
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def add(self, source: Path, filename: str) -> Delivery:
        """Move a finished, verified MP4 into the delivery area (atomic rename)."""
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        file_id = new_id()
        suffix = ".zip" if filename.lower().endswith(".zip") else ".mp4"
        dest = self.root / f"{file_id}{suffix}"
        os.replace(source, dest)  # same volume as the job directory
        item = Delivery(
            file_id=file_id,
            path=dest,
            filename=Path(filename).name or "video.mp4",
            size_bytes=dest.stat().st_size,
            expires_at=time.time() + self.retention,
        )
        with self._lock:
            self._items[file_id] = item
        return item

    def status(self, file_id: str) -> Delivery | None:
        with self._lock:
            item = self._items.get(file_id)
            return replace(item) if item else None

    # ----------------------------------------------------------- transfer
    def begin(self, file_id: str) -> Delivery:
        with self._lock:
            item = self._items.get(file_id) if is_valid_id(file_id) else None
            if item is None:
                raise AppError(ErrorCode.FILE_NOT_FOUND, "This file is not available. Download the video again.")
            if item.state == DeliveryState.DELIVERED:
                raise AppError(ErrorCode.FILE_NOT_FOUND,
                               "This video was already saved. MediaLab deleted its temporary copy; download it again if needed.")
            if item.state == DeliveryState.READY and item.expires_at < time.time():
                self._expire(item)
            if item.state == DeliveryState.EXPIRED:
                raise AppError(ErrorCode.FILE_NOT_FOUND, "This file expired and was deleted. Download the video again.")
            if item.state == DeliveryState.DELIVERING:
                raise AppError(ErrorCode.DELIVERY_IN_PROGRESS, "This video is already being saved by your browser.")
            if not item.path.is_file() or not item.path.resolve().is_relative_to(self.root):
                self._expire(item)
                raise AppError(ErrorCode.FILE_NOT_FOUND, "The temporary file is missing. Download the video again.")
            item.state = DeliveryState.DELIVERING
            item.attempts += 1
            return replace(item)

    def finish(self, file_id: str, completed: bool) -> None:
        """Called exactly once per :meth:`begin`, after the response ends."""
        with self._lock:
            item = self._items.get(file_id)
            if item is None or item.state != DeliveryState.DELIVERING:
                return
            if completed:
                item.state = DeliveryState.DELIVERED
                item.finished_at = time.time()
                item.path.unlink(missing_ok=True)
            elif item.expires_at < time.time():
                self._expire(item)
            else:
                item.state = DeliveryState.READY  # interrupted: allow a retry until expiry

    def take(self, file_id: str, dest: Path) -> Path | None:
        """Move a finished file out of the delivery area (a batch packages it instead). None if unavailable."""
        with self._lock:
            item = self._items.get(file_id)
            if item is None or item.state != DeliveryState.READY or not item.path.is_file():
                return None
            dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.replace(item.path, dest)
            item.state = DeliveryState.DELIVERED
            item.finished_at = time.time()
            return dest

    def discard(self, file_id: str) -> bool:
        """Delete a finished file nobody is downloading (e.g. a cancelled batch). Never one being streamed."""
        with self._lock:
            item = self._items.get(file_id)
            if item is None or item.state != DeliveryState.READY:
                return False
            self._expire(item)
            return True

    # ------------------------------------------------------------ cleanup
    def _expire(self, item: Delivery) -> None:
        item.path.unlink(missing_ok=True)
        item.state = DeliveryState.EXPIRED
        item.finished_at = time.time()

    def prune(self, now: float | None = None) -> int:
        """Delete expired files (never one being streamed) and forget old records."""
        now = now or time.time()
        removed = 0
        with self._lock:
            for key, item in list(self._items.items()):
                if item.state == DeliveryState.READY and item.expires_at < now:
                    self._expire(item)
                    removed += 1
                elif item.state in (DeliveryState.DELIVERED, DeliveryState.EXPIRED) and (
                    now - (item.finished_at or now) > self.forget_after
                ):
                    del self._items[key]
            known = {item.path.name for item in self._items.values() if item.state in (DeliveryState.READY, DeliveryState.DELIVERING)}
        # Orphans (e.g. a crash between rename and registration).
        if self.root.is_dir():
            for entry in self.root.iterdir():
                if entry.name not in known:
                    try:
                        if now - entry.stat().st_mtime > 60:
                            remove_tree_within(self.root, entry)
                            removed += 1
                    except OSError:
                        continue
        return removed


# -------------------------------------------------------------------- cleanup
def remove_tree_within(root: Path, path: Path) -> bool:
    """Delete ``path`` only if it is strictly inside ``root``."""
    root_resolved = root.resolve()
    try:
        target = path.resolve()
    except OSError:
        return False
    if target == root_resolved or not target.is_relative_to(root_resolved):
        log.warning("Refusing to delete %s: outside %s", target, root_resolved)
        return False
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    elif target.exists():
        target.unlink(missing_ok=True)
    return not target.exists()


def cleanup_temp_root(temp_root: Path, max_age_seconds: float, active: set[str] | None = None, now: float | None = None) -> int:
    """Remove MediaLab job directories older than ``max_age_seconds``.

    ``active`` holds directory names in use by running jobs; they are never touched.
    Only entries created by MediaLab (``job-*``) are considered.
    """
    if not temp_root.is_dir():
        return 0
    now = now or time.time()
    active = active or set()
    removed = 0
    for entry in temp_root.iterdir():
        if not entry.name.startswith(JOB_DIR_PREFIX) or entry.name in active:
            continue
        try:
            age = now - entry.stat().st_mtime
        except OSError:
            continue
        if age >= max_age_seconds and remove_tree_within(temp_root, entry):
            removed += 1
    return removed


# ----------------------------------------------------------------- disk space
def free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def ensure_free_space(temp_dir: Path, expected_bytes: int, reserve_bytes: int) -> None:
    """Refuse a download that would not fit, before any bytes are fetched.

    The temp volume briefly holds the download plus its lossless MP4 remux
    (about 2x the size); ``reserve_bytes`` is always kept free.
    """
    need = 2 * expected_bytes + reserve_bytes
    free = free_bytes(temp_dir)
    if free < need:
        mb = 1024 * 1024
        raise AppError(
            ErrorCode.INSUFFICIENT_SPACE,
            f"Not enough disk space for this download: about {need // mb:,} MB of temporary space is needed, "
            f"but only {free // mb:,} MB is free. Free up space or choose a smaller resolution.",
        )


def directory_usage_bytes(root: Path) -> int:
    """Total size of regular files under ``root`` (no symlinks followed)."""
    total = 0
    if not root.is_dir():
        return 0
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
    return total
