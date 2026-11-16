from __future__ import annotations

import shutil
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.errors import AppError, ErrorCode  # noqa: E402
from app.main import create_app  # noqa: E402
from app.media import ProbeResult  # noqa: E402
from app.models import PostMetadata  # noqa: E402
from app.providers.base import ProgressUpdate, VideoProvider  # noqa: E402
from app.providers.ytdlp_normalise import normalise_info  # noqa: E402
from app.validation import ValidatedUrl  # noqa: E402

from . import fixtures  # noqa: E402

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        config_dir=(tmp_path / "config").resolve(),
        temp_dir=(tmp_path / "tmp").resolve(),
        max_concurrent_downloads=1,
        max_queued_jobs=3,
        serve_frontend=False,
    )


class FakeProvider(VideoProvider):
    """Returns fixture metadata and writes small fake media files."""

    name = "fake"

    def __init__(self, info: dict | None = None, error: AppError | None = None) -> None:
        self.info = info if info is not None else fixtures.single_video_info()
        self.error = error
        self.download_error: AppError | None = None
        self.chunk_sizes = [400, 600]
        self.gate: threading.Event | None = None
        self.calls: list[tuple] = []

    def extract(self, url: ValidatedUrl) -> PostMetadata:
        if self.error:
            raise self.error
        return normalise_info(self.info, url, ("twimg.com",))

    def download(self, url, video_index, format_ids, dest_dir: Path, on_progress):
        self.calls.append((url.canonical_url, video_index, list(format_ids)))
        if self.gate is not None:
            self.gate.wait(5)
        if self.download_error:
            raise self.download_error
        outputs = {}
        for fid in format_ids:
            total = sum(self.chunk_sizes)
            done = 0
            for chunk in self.chunk_sizes:
                done += chunk
                on_progress(ProgressUpdate(fid, "downloading", done, total, False, 1000.0, 1.0))
            on_progress(ProgressUpdate(fid, "finished", total, total, False))
            path = dest_dir / f"{fid}.mp4"
            path.write_bytes(b"\0" * total)
            outputs[fid] = path
        return outputs


class FakeProcessor:
    """Stands in for FFmpeg: concatenates inputs and reports a fixed probe."""

    def __init__(self) -> None:
        self.error: AppError | None = None
        self.calls: list[tuple] = []

    def available(self) -> bool:
        return True

    def assemble_mp4(self, video_path: Path, audio_path: Path | None, output_path: Path,
                     expect_audio: bool = False) -> ProbeResult:
        self.calls.append((video_path.name, audio_path.name if audio_path else None))
        if self.error:
            raise self.error
        data = video_path.read_bytes() + (audio_path.read_bytes() if audio_path else b"")
        output_path.write_bytes(data)
        return ProbeResult("mov,mp4", 15.5, len(data), 1280, 720, 30.0, "h264", "aac", True, True)

    def probe(self, path: Path) -> ProbeResult:
        return ProbeResult("mov,mp4", 15.5, path.stat().st_size, 1280, 720, 30.0, "h264", "aac", True, True)


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def processor() -> FakeProcessor:
    return FakeProcessor()


@pytest.fixture
def client(settings, provider, processor):
    app = create_app(settings, provider=provider, processor=processor)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def wait_for_job(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["state"] in ("completed", "failed"):
            return body
        time.sleep(0.02)
    raise AssertionError("job did not finish in time")


__all__ = ["AppError", "ErrorCode", "FakeProvider", "FakeProcessor", "HAS_FFMPEG", "wait_for_job"]
