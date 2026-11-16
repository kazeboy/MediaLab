"""User-editable settings, persisted to a local JSON file.

Only a small, explicit set of preferences can be changed from the GUI:

* ``fxtwitter_fallback``: opt-in third-party metadata fallback for X posts.
* ``max_file_size_mb``: per-download (per-episode) size limit (bounded; disk checks still apply).
* ``batch_output_max_mb``: size limit for one packaged batch output (a Short Drama ZIP or
  merged MP4), separate from the per-download limit so whole-series exports are possible.

Paths, network binding, timeouts, host allowlists and every other security
setting stay in the environment / ``.env`` and cannot be changed through the API.

Precedence: once ``settings.json`` exists it is authoritative for these two
values. Until then, ``MEDIALAB_FXTWITTER_FALLBACK`` / ``MEDIALAB_MAX_FILE_SIZE_MB``
from the environment (or the built-in defaults) are used as initial values.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError

log = logging.getLogger(__name__)

SETTINGS_FILENAME = "settings.json"
MIN_FILE_SIZE_MB = 256
MAX_FILE_SIZE_MB = 65536  # 64 GB
DEFAULT_FILE_SIZE_MB = 8192
FILE_SIZE_PRESETS_MB = (2048, 8192, 16384)
MAX_BATCH_OUTPUT_MB = 262144  # 256 GB
DEFAULT_BATCH_OUTPUT_MB = 32768
BATCH_OUTPUT_PRESETS_MB = (8192, 32768, 65536)


class UserSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fxtwitter_fallback: StrictBool = False
    max_file_size_mb: StrictInt = Field(default=DEFAULT_FILE_SIZE_MB, ge=MIN_FILE_SIZE_MB, le=MAX_FILE_SIZE_MB)
    batch_output_max_mb: StrictInt = Field(default=DEFAULT_BATCH_OUTPUT_MB, ge=MIN_FILE_SIZE_MB, le=MAX_BATCH_OUTPUT_MB)

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def batch_output_max_bytes(self) -> int:
        return self.batch_output_max_mb * 1024 * 1024


class SettingsPatch(BaseModel):
    """Partial update; unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")

    fxtwitter_fallback: StrictBool | None = None
    max_file_size_mb: StrictInt | None = Field(default=None, ge=MIN_FILE_SIZE_MB, le=MAX_FILE_SIZE_MB)
    batch_output_max_mb: StrictInt | None = Field(default=None, ge=MIN_FILE_SIZE_MB, le=MAX_BATCH_OUTPUT_MB)


class SettingsStore:
    """Thread-safe holder of :class:`UserSettings` backed by an atomically written file."""

    def __init__(self, path: Path, initial: UserSettings) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._persisted = False
        self._current = self._load(initial)

    @property
    def persisted(self) -> bool:
        """True once the settings have been saved to disk (i.e. the file is authoritative)."""
        return self._persisted

    def _load(self, initial: UserSettings) -> UserSettings:
        if not self.path.is_file():
            return initial
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            loaded = UserSettings.model_validate(data)
        except (OSError, ValueError, ValidationError) as exc:
            backup = self.path.with_suffix(".invalid.json")
            log.warning("Ignoring unreadable settings file %s (%s); moved to %s", self.path, exc, backup.name)
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            return initial
        self._persisted = True
        return loaded

    def get(self) -> UserSettings:
        with self._lock:
            return self._current

    def update(self, patch: SettingsPatch) -> UserSettings:
        changes = patch.model_dump(exclude_none=True)
        with self._lock:
            updated = UserSettings.model_validate({**self._current.model_dump(), **changes})
            self._write(updated)
            self._current = updated
            self._persisted = True
            return updated

    def _write(self, settings: UserSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        payload = json.dumps(settings.model_dump(), indent=2) + "\n"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
