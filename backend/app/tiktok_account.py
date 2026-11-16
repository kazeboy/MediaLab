"""Optional TikTok sign-in for the Short Drama tab only.

TikTok streams Short Drama episodes only to signed-in viewers. MediaLab never
asks for a TikTok password and never reads a browser's cookie store. Instead
the user may *explicitly* give MediaLab a Netscape ``cookies.txt`` export of
their own tiktok.com session (from a browser extension or yt-dlp), through the
Settings panel. Then:

* Only cookies for ``tiktok.com`` and its subdomains are kept; everything else
  in the file is discarded before anything is written.
* The file is stored at a fixed path (``<config dir>/tiktok-cookies.txt``), written
  atomically with owner-only permissions (0600). Its contents are never logged
  or returned by the API; only a status (linked, cookie count, expiry) is.
* Only the Short Drama provider loads it, into an in-memory cookie jar per
  request (the file is never rewritten by yt-dlp). X and the TikTok Videos tab
  never send these cookies.
* Removing the account deletes the file.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import AppError, ErrorCode

COOKIE_FILENAME = "tiktok-cookies.txt"
MAX_UPLOAD_BYTES = 1_000_000
MAX_COOKIES = 500
# Any of these marks a signed-in TikTok web session.
SESSION_COOKIES = ("sessionid", "sessionid_ss", "sid_tt")
_HEADER = "# Netscape HTTP Cookie File\n# Written by MediaLab: tiktok.com cookies for Short Drama only.\n"


@dataclass(frozen=True)
class AccountStatus:
    linked: bool
    cookie_count: int = 0
    session_expires_at: float | None = None  # None: browser-session cookie or not linked
    expired: bool = False
    saved_at: float | None = None


def _is_tiktok_domain(domain: str) -> bool:
    d = domain.lower().lstrip(".")
    return d == "tiktok.com" or d.endswith(".tiktok.com")


def parse_tiktok_cookies(text: str) -> list[list[str]]:
    """Return the tiktok.com cookie lines (7 fields each) from a Netscape cookies file.

    Raises ``validation_error`` when the text isn't a cookies file or holds no
    signed-in TikTok session.
    """
    if not isinstance(text, str) or not text.strip():
        raise AppError(ErrorCode.VALIDATION_ERROR, "The cookies file is empty.")
    if len(text.encode("utf-8", "ignore")) > MAX_UPLOAD_BYTES:
        raise AppError(ErrorCode.VALIDATION_ERROR, "That file is too large to be a cookies file (limit 1 MB).")
    rows: list[list[str]] = []
    saw_cookie_line = False
    for line in text.splitlines():
        line = line.rstrip("\r")
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line[len("#HttpOnly_"):]
        elif not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        saw_cookie_line = True
        domain, flag, path, secure, expiry, name, value = fields
        if not _is_tiktok_domain(domain) or not name or any(c in name + value for c in "\n\r"):
            continue
        if not expiry.strip().lstrip("-").isdigit():
            continue
        rows.append([("#HttpOnly_" if http_only else "") + domain, flag, path, secure, expiry.strip(), name, value])
    if not saw_cookie_line:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "This isn't a cookies.txt file. Export your tiktok.com cookies in Netscape format (cookies.txt).",
        )
    if len(rows) > MAX_COOKIES:
        raise AppError(ErrorCode.VALIDATION_ERROR, "The file contains too many TikTok cookies.")
    if not any(r[5] in SESSION_COOKIES and r[6] for r in rows):
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "No signed-in TikTok session was found in this file. Sign in to tiktok.com in your browser, then export "
            "the cookies again.",
        )
    return rows


class TikTokAccountStore:
    def __init__(self, config_dir: Path) -> None:
        self.path = config_dir / COOKIE_FILENAME
        self._lock = threading.Lock()

    def linked(self) -> bool:
        return self.path.is_file()

    def save(self, text: str) -> AccountStatus:
        rows = parse_tiktok_cookies(text)
        body = _HEADER + "".join("\t".join(r) + "\n" for r in rows)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".tiktok-cookies-", dir=self.path.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(body)
                os.replace(tmp, self.path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        return self.status()

    def remove(self) -> AccountStatus:
        with self._lock:
            self.path.unlink(missing_ok=True)
        return self.status()

    def load_into(self, jar) -> bool:
        """Load the saved cookies into a yt-dlp cookie jar (in memory). Returns False if none."""
        with self._lock:
            if not self.path.is_file():
                return False
            jar.load(str(self.path), ignore_discard=True, ignore_expires=False)
        return True

    def status(self, now: float | None = None) -> AccountStatus:
        now = time.time() if now is None else now
        with self._lock:
            try:
                text = self.path.read_text(encoding="utf-8")
                saved_at = self.path.stat().st_mtime
            except OSError:
                return AccountStatus(linked=False)
        try:
            rows = parse_tiktok_cookies(text)
        except AppError:
            return AccountStatus(linked=True, expired=True, saved_at=saved_at)
        expiries = [int(r[4]) for r in rows if r[5] in SESSION_COOKIES and r[6]]
        persistent = [e for e in expiries if e > 0]
        expires_at = float(max(persistent)) if persistent else None
        return AccountStatus(
            linked=True,
            cookie_count=len(rows),
            session_expires_at=expires_at,
            expired=expires_at is not None and expires_at <= now,
            saved_at=saved_at,
        )
