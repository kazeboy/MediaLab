import pytest

from app.errors import AppError, ErrorCode
from app.validation import is_allowed_media_url, validate_post_url


@pytest.mark.parametrize(
    ("raw", "canonical", "video_index"),
    [
        ("https://x.com/example_user/status/1800000000000000001", "https://x.com/example_user/status/1800000000000000001", None),
        ("https://twitter.com/example_user/status/123", "https://x.com/example_user/status/123", None),
        ("http://www.twitter.com/example_user/status/123?s=20&t=abc", "https://x.com/example_user/status/123", None),
        ("https://mobile.twitter.com/example_user/status/123/", "https://x.com/example_user/status/123", None),
        ("https://m.x.com/example_user/status/123#frag", "https://x.com/example_user/status/123", None),
        ("x.com/example_user/status/123", "https://x.com/example_user/status/123", None),
        ("  https://x.com/example_user/status/123  ", "https://x.com/example_user/status/123", None),
        ("https://x.com/example_user/status/123/video/2", "https://x.com/example_user/status/123", 2),
        ("https://x.com/example_user/status/123/photo/1", "https://x.com/example_user/status/123", None),
        ("https://x.com/i/web/status/123", "https://x.com/i/status/123", None),
        ("https://x.com/i/status/123", "https://x.com/i/status/123", None),
        ("https://twitter.com/statuses/123", "https://x.com/i/status/123", None),
        ("https://X.COM/example_user/status/123", "https://x.com/example_user/status/123", None),
        ("https://x.com:443/example_user/status/123", "https://x.com/example_user/status/123", None),
    ],
)
def test_valid_urls(raw, canonical, video_index):
    result = validate_post_url(raw)
    assert result.canonical_url == canonical
    assert result.video_index == video_index
    assert result.post_id == canonical.rsplit("/", 1)[1]


@pytest.mark.parametrize(
    "raw",
    [
        "https://youtube.com/watch?v=abc",
        "https://x.com.evil.com/example_user/status/123",
        "https://evilx.com/example_user/status/123",
        "https://t.co/abcdef",
        "https://x.com/example_user",
        "https://x.com/home",
        "https://x.com/i/spaces/1ABCDEF",
        "https://x.com/i/broadcasts/1ABCDEF",
        "https://x.com/example_user/status/abc",
        "https://x.com/example_user/status/123/extra/path",
        "https://x.com/example_user/status/123456789012345678901",
        "https://x.com/search/status/123",
        "ftp://x.com/example_user/status/123",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://x.com:8080/example_user/status/123",
        "https://127.0.0.1/example_user/status/123",
        "https://169.254.169.254/latest/meta-data",
        "https://x.com/example_user/status/0",
    ],
)
def test_unsupported_urls(raw):
    with pytest.raises(AppError) as exc:
        validate_post_url(raw)
    assert exc.value.code in (ErrorCode.UNSUPPORTED_URL, ErrorCode.INVALID_URL)


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "https://x.com/example_user/status/1 23", "https://user:pw@x.com/example_user/status/123",
     "https://x.com/example_user/status/12\n3", "https://x.com/example_user/sta\x00tus/123","https://x.com:abc/example_user/status/1", "https://x.com/" + "a" * 3000],
)
def test_invalid_urls(raw):
    with pytest.raises(AppError) as exc:
        validate_post_url(raw)
    assert exc.value.code in (ErrorCode.INVALID_URL, ErrorCode.UNSUPPORTED_URL)


def test_credentials_rejected_specifically():
    with pytest.raises(AppError) as exc:
        validate_post_url("https://user:pw@x.com/example_user/status/123")
    assert exc.value.code == ErrorCode.INVALID_URL


def test_canonical_url_drops_query_injection():
    result = validate_post_url("https://x.com/example_user/status/123?url=http://169.254.169.254/")
    assert result.canonical_url == "https://x.com/example_user/status/123"


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://video.twimg.com/a.mp4", True),
        ("https://pbs.twimg.com/a.jpg", True),
        ("https://twimg.com/a.mp4", True),
        ("http://video.twimg.com/a.mp4", False),
        ("https://twimg.com.evil.com/a.mp4", False),
        ("https://eviltwimg.com/a.mp4", False),
        ("https://u:p@video.twimg.com/a.mp4", False),
        (None, False),
        ("", False),
    ],
)
def test_media_host_allowlist(url, ok):
    assert is_allowed_media_url(url, ("twimg.com",)) is ok
