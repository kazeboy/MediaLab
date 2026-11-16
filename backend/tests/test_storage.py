"""Filename sanitisation, file registry and temporary-file cleanup."""

import os
import time

import pytest

from app.errors import AppError, ErrorCode
from app.models import PostMetadata, ResolutionOption, VideoEntry
from app.storage import (
    build_filename,
    cleanup_temp_root,
    remove_tree_within,
    sanitise_filename_part,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("hello world", "hello world"),
        ("../../etc/passwd", "etc passwd"),
        ('a/b\\c:d*e?f"g<h>i|j', "a b c d e f g h i j"),
        ("line\nbreak\ttab", "line break tab"),
        ("bidi‮evil", "bidievil"),
        ("...hidden", "hidden"),
        ("see https://t.co/abc now", "see now"),
        ("   ", ""),
        (None, ""),
        ("café", "café"),
    ],
)
def test_sanitise_filename_part(raw, expected):
    assert sanitise_filename_part(raw) == expected


def test_sanitise_truncates_long_text():
    out = sanitise_filename_part("word " * 100, max_length=30)
    assert len(out) <= 30 and not out.endswith(" ")


def _option(w=1280, h=720):
    return ResolutionOption(option_id="720p", label="720p", width=w, height=h, video_format_id="v")


def test_build_filename_is_readable_and_safe():
    post = PostMetadata(url="u", post_id="123", author_handle="nasa", text="Launch! / Day 1: <live>")
    name = build_filename(post, VideoEntry(index=1), _option(), 1)
    assert name == "nasa - Launch! Day 1 live [123] 720p.mp4"
    assert "/" not in name and name.endswith(".mp4")


def test_build_filename_multi_video_and_portrait():
    post = PostMetadata(url="u", post_id="123", author_handle=None, text=None)
    name = build_filename(post, VideoEntry(index=2), _option(720, 1280), 3)
    assert name == "X video [123] #2 720p.mp4"


def _make_old(path, age):
    t = time.time() - age
    os.utime(path, (t, t))


def test_cleanup_removes_only_old_job_dirs(tmp_path):
    root = tmp_path / "tmp"
    root.mkdir()
    old = root / "job-old"
    old.mkdir()
    (old / "video.mp4").write_bytes(b"x")
    _make_old(old, 7200)
    fresh = root / "job-new"
    fresh.mkdir()
    active = root / "job-active"
    active.mkdir()
    _make_old(active, 7200)
    foreign = root / "not-ours"
    foreign.mkdir()
    _make_old(foreign, 7200)

    removed = cleanup_temp_root(root, 3600, active={"job-active"})
    assert removed == 1
    assert not old.exists() and fresh.exists() and active.exists() and foreign.exists()


def test_remove_tree_within_refuses_outside_and_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    assert remove_tree_within(root, outside) is False and outside.exists()
    assert remove_tree_within(root, root) is False and root.exists()
    assert remove_tree_within(root, root / ".." / "outside") is False and outside.exists()


def test_working_folders_are_owner_only(tmp_path):
    """SEC-2: MediaLab's own temp subfolders are 0700 even inside a shared base folder."""
    import stat as _stat

    from app.storage import DeliveryStore

    base = tmp_path / "shared"
    base.mkdir(mode=0o755)
    store = DeliveryStore(base, 60)
    store.reset()
    src = base / "x.mp4"
    src.write_bytes(b"x")
    item = store.add(src, "Show - E01-E02.zip")
    assert _stat.S_IMODE(store.root.stat().st_mode) == 0o700
    assert item.path.suffix == ".zip"  # MNT-6: stored with its real extension
    dest = store.take(item.file_id, base / "job-batch-x" / "E0001.mp4")
    assert dest is not None and _stat.S_IMODE(dest.parent.stat().st_mode) == 0o700
