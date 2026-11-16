"""Video URL validation and canonicalisation for X/Twitter and TikTok.

Only URLs that point at an individual X post or an individual TikTok video on an
allowlisted host are accepted. Accepted URLs are rebuilt from the parsed IDs, so
the string handed to an extractor never contains user-controlled query strings,
fragments, credentials, ports or unexpected path segments.

TikTok short links (vm.tiktok.com, vt.tiktok.com, tiktok.com/t/...) cannot be
canonicalised offline; they are marked ``short_link`` and resolved later by
following redirects hop by hop, each hop validated (see ``app.resolve``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

from .errors import AppError, ErrorCode

MAX_URL_LENGTH = 2048

PLATFORM_X = "x"
PLATFORM_TIKTOK = "tiktok"
PLATFORM_SHORTDRAMA = "tiktok_shortdrama"
PLATFORMS = (PLATFORM_X, PLATFORM_TIKTOK, PLATFORM_SHORTDRAMA)
PLATFORM_LABELS = {PLATFORM_X: "X", PLATFORM_TIKTOK: "TikTok", PLATFORM_SHORTDRAMA: "TikTok Short Drama"}
TIKTOK_FAMILY = frozenset({PLATFORM_TIKTOK, PLATFORM_SHORTDRAMA})
TAB_NAMES = {PLATFORM_X: "X", PLATFORM_TIKTOK: "TikTok Videos", PLATFORM_SHORTDRAMA: "TikTok Short Drama"}

# ------------------------------------------------------------------------- X
ALLOWED_HOSTS = frozenset(
    {
        "x.com",
        "www.x.com",
        "mobile.x.com",
        "m.x.com",
        "twitter.com",
        "www.twitter.com",
        "mobile.twitter.com",
        "m.twitter.com",
    }
)

_HANDLE = r"[A-Za-z0-9_]{1,15}"
_POST_ID = r"[0-9]{1,20}"

# /<handle>/status/<id>[/video/<n>|/photo/<n>]   (also /statuses/<id> legacy form)
# /i/web/status/<id>   /i/status/<id>
_PATH_PATTERNS = (
    re.compile(
        rf"^/(?P<handle>{_HANDLE})/status(?:es)?/(?P<id>{_POST_ID})"
        r"(?:/(?P<kind>video|photo)/(?P<index>[1-9][0-9]?))?/?$"
    ),
    re.compile(
        rf"^/i/(?:web/)?status/(?P<id>{_POST_ID})"
        r"(?:/(?P<kind>video|photo)/(?P<index>[1-9][0-9]?))?/?$"
    ),
    re.compile(rf"^/statuses/(?P<id>{_POST_ID})/?$"),
)

# Reserved first path segments that are not user handles.
_RESERVED_HANDLES = frozenset({"i", "home", "explore", "search", "settings", "messages", "notifications"})

# -------------------------------------------------------------------- TikTok
TIKTOK_PAGE_HOSTS = frozenset({"tiktok.com", "www.tiktok.com", "m.tiktok.com"})
TIKTOK_SHORT_HOSTS = frozenset({"vm.tiktok.com", "vt.tiktok.com"})
_TT_USER = r"[A-Za-z0-9_.-]{0,64}"
_TT_ID = r"[0-9]{5,25}"
_TT_CODE = r"[A-Za-z0-9]{4,32}"
_TT_VIDEO = re.compile(rf"^/@(?P<user>{_TT_USER})/video/(?P<id>{_TT_ID})/?$")
_TT_MOBILE = re.compile(rf"^/v/(?P<id>{_TT_ID})(?:\.html)?/?$")
_TT_SHORT_PATH = re.compile(rf"^/t/(?P<code>{_TT_CODE})/?$")
_TT_SHORT_HOST_PATH = re.compile(rf"^/(?P<code>{_TT_CODE})/?$")
_TT_PHOTO = re.compile(rf"^/@{_TT_USER}/photo/")
_TT_LIVE = re.compile(rf"^/@{_TT_USER}/live/?$")
_TT_PROFILE = re.compile(rf"^/@{_TT_USER}/?$")
# Short Drama: /shortdrama/episode/<drama id>/<episode number>
_TT_DRAMA_EPISODE = re.compile(r"^/shortdrama/episode/(?P<drama>[0-9]{5,25})/(?P<ep>[1-9][0-9]{0,3})/?$")
_TT_DRAMA_ANY = re.compile(r"^/shortdrama(?:/|$)")

# TikTok media CDNs observed for public videos. Edge nodes on tiktok.com itself
# are matched by pattern (e.g. v16-webapp-prime.tiktok.com), never www/m/vm.
_TIKTOK_MEDIA_SUFFIXES = ("tiktokcdn.com", "tiktokcdn-eu.com", "tiktokcdn-us.com")
_TIKTOK_EDGE_HOST = re.compile(r"^v[0-9]{1,3}[a-z0-9-]*\.tiktok\.com$")


@dataclass(frozen=True)
class ValidatedUrl:
    """A validated, canonical video URL."""

    canonical_url: str
    post_id: str  # X post ID or TikTok video ID ("" for an unresolved short link)
    handle: str | None
    video_index: int | None  # 1-based index from an X /video/<n> suffix, if present
    platform: str = PLATFORM_X
    short_link: bool = False
    episode: int | None = None  # Short Drama episode number

    @property
    def platform_label(self) -> str:
        return PLATFORM_LABELS.get(self.platform, self.platform)


def _parse(raw: str):
    if not isinstance(raw, str):
        raise AppError(ErrorCode.INVALID_URL, "Please provide a URL.")
    text = raw.strip()
    if not text:
        raise AppError(ErrorCode.INVALID_URL, "Please paste an X or TikTok video URL.")
    if len(text) > MAX_URL_LENGTH:
        raise AppError(ErrorCode.INVALID_URL, "That URL is too long.")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise AppError(ErrorCode.INVALID_URL, "The URL contains spaces or control characters.")
    if "://" not in text:
        text = "https://" + text  # accept "x.com/user/status/123" without a scheme
    try:
        parts = urlsplit(text)
        port = parts.port  # raises ValueError for non-numeric ports
    except ValueError as exc:
        raise AppError(ErrorCode.INVALID_URL, "That does not look like a valid URL.") from exc
    if parts.scheme.lower() not in {"http", "https"}:
        raise AppError(ErrorCode.UNSUPPORTED_URL, "Only http(s) links to X posts or TikTok videos are supported.")
    if parts.username is not None or parts.password is not None:
        raise AppError(ErrorCode.INVALID_URL, "URLs containing credentials are not accepted.")
    if port is not None and port not in (80, 443):
        raise AppError(ErrorCode.UNSUPPORTED_URL, "Only standard X or TikTok URLs are supported.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise AppError(ErrorCode.INVALID_URL, "That does not look like a valid URL.")
    return host, parts.path or "/"


def validate_post_url(raw: str, expected_platform: str | None = None) -> ValidatedUrl:
    """Validate ``raw`` (X post, TikTok video or Short Drama episode) and canonicalise it.

    With ``expected_platform`` (the UI tab), a valid URL for a *different*
    platform raises ``wrong_platform`` with ``details.detected_platform`` so the
    UI can offer to switch. TikTok short links can't be classified until they
    are resolved, so they are accepted by both TikTok tabs and checked again
    after resolution (see :func:`check_platform`).
    """
    host, path = _parse(raw)
    if host in ALLOWED_HOSTS:
        result = _validate_x(path)
    elif host in TIKTOK_PAGE_HOSTS or host in TIKTOK_SHORT_HOSTS:
        result = _validate_tiktok(host, path)
    else:
        raise AppError(
            ErrorCode.INVALID_URL,
            "This URL isn't recognised. MediaLab supports X posts (x.com, twitter.com), TikTok videos and "
            "TikTok Short Drama episodes (tiktok.com).",
        )
    result = adopt_for_tab(result, expected_platform)
    if expected_platform and not (result.short_link and expected_platform in TIKTOK_FAMILY):
        check_platform(result, expected_platform)
    return result


def adopt_for_tab(url: ValidatedUrl, expected_platform: str | None) -> ValidatedUrl:
    """Short Drama episodes are ordinary TikTok items (``/@user/video/<id>``), so the
    Short Drama tab accepts TikTok video links; its provider then checks that the
    item really is an episode (and suggests the TikTok Videos tab if not)."""
    if expected_platform == PLATFORM_SHORTDRAMA and url.platform == PLATFORM_TIKTOK and not url.short_link:
        return replace(url, platform=PLATFORM_SHORTDRAMA)
    return url


def check_platform(url: ValidatedUrl, expected_platform: str | None) -> None:
    """Raise ``wrong_platform`` if a valid URL belongs to another tab."""
    if expected_platform and url.platform != expected_platform:
        detected = PLATFORM_LABELS.get(url.platform, url.platform)
        expected = PLATFORM_LABELS.get(expected_platform, expected_platform)
        def an(word: str) -> str:
            return "an" if word[:1] in "AEIOUX" else "a"

        raise AppError(
            ErrorCode.WRONG_PLATFORM,
            f"This is {an(detected)} {detected} link, not {an(expected)} {expected} link.",
            action=f"Switch to the {TAB_NAMES.get(url.platform, detected)} tab.",
            details={"detected_platform": url.platform, "url": url.canonical_url},
        )


# Backwards-compatible name used across the codebase.
validate_video_url = validate_post_url


def _validate_x(path: str) -> ValidatedUrl:
    for pattern in _PATH_PATTERNS:
        match = pattern.match(path)
        if not match:
            continue
        groups = match.groupdict()
        handle = groups.get("handle")
        if handle and handle.lower() in _RESERVED_HANDLES:
            continue
        post_id = groups["id"].lstrip("0") or "0"
        if post_id == "0":
            break
        index = groups.get("index")
        video_index = int(index) if index and groups.get("kind") == "video" else None
        owner = handle if handle else "i"
        canonical = f"https://x.com/{owner}/status/{post_id}"
        return ValidatedUrl(canonical_url=canonical, post_id=post_id, handle=handle, video_index=video_index)

    raise AppError(
        ErrorCode.UNSUPPORTED_URL,
        "That link is not an X post. Use a URL like https://x.com/<user>/status/<id>.",
    )


def _validate_tiktok(host: str, path: str) -> ValidatedUrl:
    if host in TIKTOK_SHORT_HOSTS:
        match = _TT_SHORT_HOST_PATH.match(path)
        if match:
            return _tiktok_short(f"https://{host}/{match['code']}/")
    else:
        if match := _TT_VIDEO.match(path):
            return _tiktok_video(match["id"], match["user"])
        if match := _TT_MOBILE.match(path):
            return _tiktok_video(match["id"], "")
        if match := _TT_SHORT_PATH.match(path):
            return _tiktok_short(f"https://www.tiktok.com/t/{match['code']}/")
        if match := _TT_DRAMA_EPISODE.match(path):
            drama = match["drama"].lstrip("0")
            episode = int(match["ep"])
            return ValidatedUrl(
                canonical_url=f"https://www.tiktok.com/shortdrama/episode/{drama}/{episode}",
                post_id=drama,
                handle=None,
                video_index=None,
                platform=PLATFORM_SHORTDRAMA,
                episode=episode,
            )
        if _TT_DRAMA_ANY.match(path):
            raise AppError(
                ErrorCode.UNSUPPORTED_EPISODE_URL,
                "This Short Drama link format isn't supported yet. MediaLab expects an episode link like "
                "https://www.tiktok.com/shortdrama/episode/<series id>/<episode number>.",
            )
        if _TT_PHOTO.match(path):
            raise AppError(ErrorCode.UNSUPPORTED_URL, "TikTok photo slideshows aren't supported. MediaLab saves individual videos only.")
        if _TT_LIVE.match(path):
            raise AppError(ErrorCode.UNSUPPORTED_URL, "TikTok Live isn't supported. MediaLab saves individual videos only.")
        if _TT_PROFILE.match(path):
            raise AppError(ErrorCode.UNSUPPORTED_URL, "TikTok profiles aren't supported. Paste a link to an individual video.")
    raise AppError(
        ErrorCode.UNSUPPORTED_URL,
        "That link is not a TikTok video. Use a URL like https://www.tiktok.com/@user/video/<id>.",
    )


def _tiktok_video(video_id: str, user: str) -> ValidatedUrl:
    video_id = video_id.lstrip("0")
    if not video_id:
        raise AppError(ErrorCode.UNSUPPORTED_URL, "That link is not a TikTok video.")
    return ValidatedUrl(
        canonical_url=f"https://www.tiktok.com/@{user}/video/{video_id}",
        post_id=video_id,
        handle=user or None,
        video_index=None,
        platform=PLATFORM_TIKTOK,
    )


def _tiktok_short(canonical: str) -> ValidatedUrl:
    return ValidatedUrl(
        canonical_url=canonical, post_id="", handle=None, video_index=None, platform=PLATFORM_TIKTOK, short_link=True
    )


# -------------------------------------------------------------- host checks
def _https_host(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443):
        return None
    return (parts.hostname or "").lower().rstrip(".") or None


def is_allowed_media_url(url: str | None, host_suffixes: tuple[str, ...]) -> bool:
    """Return True if ``url`` is an https URL on one of the allowed media hosts."""
    host = _https_host(url)
    return bool(host) and any(host == s or host.endswith("." + s) for s in host_suffixes)


def is_allowed_tiktok_media_url(url: str | None) -> bool:
    """TikTok media/thumbnail CDN hosts (https only). Never www/m/vm/vt.tiktok.com."""
    host = _https_host(url)
    if not host:
        return False
    if _TIKTOK_EDGE_HOST.match(host):
        return True
    return any(host == s or host.endswith("." + s) for s in _TIKTOK_MEDIA_SUFFIXES)


def is_tiktok_redirect_hop(url: str | None) -> bool:
    """Short-link redirect hops may only stay on TikTok's own page/short-link hosts."""
    host = _https_host(url)
    return bool(host) and (host in TIKTOK_PAGE_HOSTS or host in TIKTOK_SHORT_HOSTS)
