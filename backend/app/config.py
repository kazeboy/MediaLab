"""Application configuration.

Settings are read from environment variables (optionally loaded from a ``.env``
file in the repository root or the ``backend`` directory). Every setting has a
safe local default so the app runs without any configuration.
"""

from __future__ import annotations

import logging

import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_DIR = _BACKEND_DIR.parent

log = logging.getLogger(__name__)


def load_dotenv(path: Path) -> None:
    """Minimal ``.env`` loader: ``KEY=value`` lines, ``#`` comments, optional quotes.

    Existing environment variables always win over values in the file.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


MAX_BULK_URLS = 100  # upper bound for MEDIALAB_MAX_BULK_URLS


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _default_config_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MediaLab"
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "medialab"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    path = Path(raw).expanduser() if raw and raw.strip() else default
    return path.resolve()


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return tuple(item.strip().lower() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8000
    allow_non_local: bool = False

    # Application-managed working area: partial downloads (job-*/) and finished
    # MP4s awaiting delivery to the browser (ready/). Nothing here is permanent.
    temp_dir: Path = field(default_factory=lambda: (Path(tempfile.gettempdir()) / "medialab").resolve())
    # Where settings.json (GUI settings) is stored.
    config_dir: Path = field(default_factory=lambda: _default_config_dir().resolve())

    max_concurrent_downloads: int = 2
    max_queued_jobs: int = 10
    max_concurrent_analyses: int = 4
    # Links per bulk download (X / TikTok). 50 keeps a bulk analysis to a few minutes and well
    # inside the analysis cache (200 entries); capped at MAX_BULK_URLS.
    max_bulk_urls: int = 50
    # Initial value only: the GUI setting in settings.json takes precedence once saved.
    max_file_size_mb: int = 8192
    batch_output_max_mb: int = 32768

    analysis_timeout_seconds: int = 45
    download_timeout_seconds: int = 3 * 3600
    ffmpeg_timeout_seconds: int = 600
    socket_timeout_seconds: int = 20

    analysis_ttl_seconds: int = 3600
    job_ttl_seconds: int = 6 * 3600
    temp_max_age_seconds: int = 6 * 3600
    cleanup_interval_seconds: int = 60
    # Finished MP4s not saved by the browser are deleted after this long.
    delivery_retention_seconds: int = 30 * 60

    media_host_suffixes: tuple[str, ...] = ("twimg.com",)

    # Opt-in third-party fallback (initial value only; GUI setting takes precedence).
    fxtwitter_fallback: bool = False

    # Free space kept in reserve on the temp volume.
    min_free_space_mb: int = 512

    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"

    serve_frontend: bool = True
    frontend_dist: Path = field(default_factory=lambda: (_REPO_DIR / "frontend" / "dist").resolve())

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(_REPO_DIR / ".env")
        load_dotenv(_BACKEND_DIR / ".env")
        defaults = cls()
        return cls(
            host=os.environ.get("MEDIALAB_HOST", defaults.host).strip(),
            port=_env_int("MEDIALAB_PORT", defaults.port, minimum=1),
            allow_non_local=_env_bool("MEDIALAB_ALLOW_NON_LOCAL", defaults.allow_non_local),
            temp_dir=_env_path("MEDIALAB_TEMP_DIR", defaults.temp_dir),
            config_dir=_env_path("MEDIALAB_CONFIG_DIR", defaults.config_dir),
            max_concurrent_downloads=_env_int("MEDIALAB_MAX_CONCURRENT_DOWNLOADS", defaults.max_concurrent_downloads, 1),
            max_queued_jobs=_env_int("MEDIALAB_MAX_QUEUED_JOBS", defaults.max_queued_jobs, 1),
            max_concurrent_analyses=_env_int("MEDIALAB_MAX_CONCURRENT_ANALYSES", defaults.max_concurrent_analyses, 1),
            max_bulk_urls=min(MAX_BULK_URLS, _env_int("MEDIALAB_MAX_BULK_URLS", defaults.max_bulk_urls, 1)),
            max_file_size_mb=_env_int("MEDIALAB_MAX_FILE_SIZE_MB", defaults.max_file_size_mb, 1),
            batch_output_max_mb=_env_int("MEDIALAB_BATCH_OUTPUT_MAX_MB", defaults.batch_output_max_mb, 1),
            delivery_retention_seconds=60 * _env_int(
                "MEDIALAB_DELIVERY_RETENTION_MINUTES", defaults.delivery_retention_seconds // 60, 1
            ),
            analysis_timeout_seconds=_env_int("MEDIALAB_ANALYSIS_TIMEOUT_SECONDS", defaults.analysis_timeout_seconds, 1),
            download_timeout_seconds=_env_int("MEDIALAB_DOWNLOAD_TIMEOUT_SECONDS", defaults.download_timeout_seconds, 1),
            ffmpeg_timeout_seconds=_env_int("MEDIALAB_FFMPEG_TIMEOUT_SECONDS", defaults.ffmpeg_timeout_seconds, 1),
            socket_timeout_seconds=_env_int("MEDIALAB_SOCKET_TIMEOUT_SECONDS", defaults.socket_timeout_seconds, 1),
            analysis_ttl_seconds=_env_int("MEDIALAB_ANALYSIS_TTL_SECONDS", defaults.analysis_ttl_seconds, 60),
            job_ttl_seconds=_env_int("MEDIALAB_JOB_TTL_SECONDS", defaults.job_ttl_seconds, 60),
            temp_max_age_seconds=_env_int("MEDIALAB_TEMP_MAX_AGE_SECONDS", defaults.temp_max_age_seconds, 60),
            cleanup_interval_seconds=_env_int("MEDIALAB_CLEANUP_INTERVAL_SECONDS", defaults.cleanup_interval_seconds, 10),
            media_host_suffixes=_env_list("MEDIALAB_MEDIA_HOST_SUFFIXES", defaults.media_host_suffixes),
            fxtwitter_fallback=_env_bool("MEDIALAB_FXTWITTER_FALLBACK", defaults.fxtwitter_fallback),
            min_free_space_mb=_env_int("MEDIALAB_MIN_FREE_SPACE_MB", defaults.min_free_space_mb, 0),
            ffmpeg_path=os.environ.get("MEDIALAB_FFMPEG_PATH", defaults.ffmpeg_path).strip() or "ffmpeg",
            ffprobe_path=os.environ.get("MEDIALAB_FFPROBE_PATH", defaults.ffprobe_path).strip() or "ffprobe",
            serve_frontend=_env_bool("MEDIALAB_SERVE_FRONTEND", defaults.serve_frontend),
        )

    def prepare_directories(self) -> None:
        """Create the temp/config folders and check they are writable.

        Raises ValueError with an actionable message. On macOS, folders such as
        ~/Downloads are privacy-protected: a terminal without "Files and Folders"
        access gets "Operation not permitted" (EPERM) even though Unix
        permissions look fine.
        """
        for label, var, path in (
            ("temporary", "MEDIALAB_TEMP_DIR", self.temp_dir),
            ("settings", "MEDIALAB_CONFIG_DIR", self.config_dir),
        ):
            try:
                created = not path.exists()
                path.mkdir(mode=0o700, parents=True, exist_ok=True)
                if not created and path.stat().st_mode & 0o077:
                    # Not changed automatically (it may be a folder the user chose and shares);
                    # MediaLab's own subfolders are created owner-only regardless.
                    log.info("The %s folder %s is accessible to other users; MediaLab's working "
                             "subfolders inside it are owner-only.", label, path)
                probe = path / f".medialab-write-test-{os.getpid()}"
                probe.write_bytes(b"")
                probe.unlink()
            except OSError as exc:
                hint = ""
                if isinstance(exc, PermissionError) and exc.errno == 1:  # EPERM
                    hint = (
                        " macOS blocked access: allow your terminal app under System Settings > "
                        "Privacy & Security > Files and Folders, or choose another folder."
                    )
                raise ValueError(
                    f"Cannot use the {label} folder {path}: {exc.strerror or exc}.{hint} "
                    f"(Set {var} in .env to change it.)"
                ) from exc

    def validate_bind_host(self) -> None:
        """Refuse to listen on a non-loopback interface unless explicitly allowed."""
        if self.host not in LOOPBACK_HOSTS and not self.allow_non_local:
            raise ValueError(
                f"Refusing to bind to {self.host!r}: MediaLab is a local-only tool. "
                "Set MEDIALAB_ALLOW_NON_LOCAL=true if you really need this."
            )
