"""Resolve TikTok short links (vm.tiktok.com, vt.tiktok.com, tiktok.com/t/...).

Redirects are followed manually, one HEAD request per hop, so no page content
is downloaded and every hop is validated *before* it is requested: each
``Location`` must be https on TikTok's own page/short-link hosts. The result
must be an individual-video URL, which is then canonicalised like any other.
"""

from __future__ import annotations

from urllib.parse import urljoin

from .errors import AppError, ErrorCode
from .net import open_url
from .validation import TIKTOK_FAMILY, ValidatedUrl, is_tiktok_redirect_hop, validate_post_url

MAX_HOPS = 5
_EXPIRED = "This shared link has expired or no longer leads to a video."


def resolve_tiktok_short_link(url: ValidatedUrl, timeout: float) -> ValidatedUrl:
    if not url.short_link:
        return url
    current = url.canonical_url
    for _ in range(MAX_HOPS):
        resp = open_url(current, is_tiktok_redirect_hop, timeout=timeout, method="HEAD", follow_redirects=False)
        with resp:
            status = getattr(resp, "status", None) or resp.getcode()
            location = resp.headers.get("Location")
        if status not in (301, 302, 303, 307, 308) or not location:
            raise AppError(ErrorCode.SHORT_LINK_EXPIRED, _EXPIRED)
        nxt = urljoin(current, location)
        if not is_tiktok_redirect_hop(nxt):
            raise AppError(ErrorCode.UNSUPPORTED_URL, "This short link redirects outside TikTok, so MediaLab won't follow it.")
        try:
            candidate = validate_post_url(nxt)
        except AppError as exc:
            raise AppError(ErrorCode.SHORT_LINK_EXPIRED, _EXPIRED) from exc  # e.g. redirected to the homepage
        if candidate.platform in TIKTOK_FAMILY and not candidate.short_link:
            return candidate  # a regular video or a Short Drama episode
        current = candidate.canonical_url
    raise AppError(ErrorCode.SHORT_LINK_EXPIRED, "This shared link redirects too many times without reaching a video.")
