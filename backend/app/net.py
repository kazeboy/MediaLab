"""Minimal HTTPS client with per-hop redirect validation.

Used by providers that fetch URLs themselves (rather than through yt-dlp).
Every request, including each redirect hop, must be ``https`` to a host that
matches the caller's allowlist; anything else is refused before a connection
is made. No cookies are stored or sent.
"""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from functools import lru_cache
from http.client import HTTPResponse

from .errors import AppError, ErrorCode

MAX_REDIRECTS = 5
USER_AGENT = "MediaLab/1.0 (+local MP4 downloader)"

HostCheck = Callable[[str], bool]


@lru_cache(maxsize=1)
def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover - certifi is a declared dependency
        return ssl.create_default_context()


class BlockedRedirect(AppError):
    pass


def _check(url: str, allowed: HostCheck) -> None:
    if not allowed(url):
        raise BlockedRedirect(ErrorCode.FORBIDDEN, "Refused to contact a host MediaLab does not trust.")


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def __init__(self, allowed: HostCheck) -> None:
        super().__init__()
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _check(newurl, self.allowed)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(
    url: str,
    allowed: HostCheck,
    *,
    timeout: float,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
) -> HTTPResponse:
    """Open ``url`` after validating it and every redirect against ``allowed``.

    Only https is possible (no plain-HTTP handler is installed). HTTP error
    statuses are returned as responses so callers can map them; network
    failures raise ``AppError``. With ``follow_redirects=False`` a 3xx response is
    returned as-is so the caller can validate and follow each hop itself.
    """
    _check(url, allowed)
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler(),
        urllib.request.HTTPSHandler(context=_ssl_context()),
        *((_ValidatingRedirectHandler(allowed),) if follow_redirects else ()),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    request = urllib.request.Request(
        url, method=method, headers={"User-Agent": USER_AGENT, "Accept": "*/*", **(headers or {})}
    )
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return exc  # type: ignore[return-value]  # HTTPError is a response object
    except BlockedRedirect:
        raise
    except TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "The request timed out. Please try again.") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise AppError(ErrorCode.NETWORK_ERROR, "Could not reach the remote server. Check your connection.") from exc
    # Defence in depth: the final URL must still be allowed.
    _check(response.geturl(), allowed)
    return response
