"""Mocked yt-dlp output modelled on real X posts (no network needed)."""

from __future__ import annotations

import copy

POST_URL = "https://x.com/medialab_test/status/1800000000000000001"


def _progressive(tbr: int, w: int, h: int, size: int | None = None) -> dict:
    f = {
        "format_id": f"http-{tbr}",
        "url": f"https://video.twimg.com/amplify_video/1/vid/avc1/{w}x{h}/x.mp4?tag=16",
        "ext": "mp4",
        "protocol": "https",
        "tbr": float(tbr),
        "width": w,
        "height": h,
    }
    if size is not None:
        f["filesize"] = size
    return f


def _hls_video(tbr: float, w: int, h: int, vcodec: str = "avc1.64001F", fps: float | None = 30.0) -> dict:
    return {
        "format_id": f"hls-{int(tbr)}",
        "url": f"https://video.twimg.com/amplify_video/1/pl/avc1/{w}x{h}/x.m3u8",
        "manifest_url": "https://video.twimg.com/amplify_video/1/pl/master.m3u8",
        "ext": "mp4",
        "protocol": "m3u8_native",
        "tbr": tbr,
        "width": w,
        "height": h,
        "fps": fps,
        "vcodec": vcodec,
        "acodec": "none",
    }


def _hls_audio(tbr: float, acodec: str = "mp4a.40.2") -> dict:
    return {
        "format_id": f"hls-audio-{int(tbr * 1000)}-Audio",
        "url": "https://video.twimg.com/amplify_video/1/pl/mp4a/128000/a.m3u8",
        "manifest_url": "https://video.twimg.com/amplify_video/1/pl/master.m3u8",
        "ext": "mp4",
        "protocol": "m3u8_native",
        "tbr": tbr,
        "vcodec": "none",
        "acodec": acodec,
    }


BASE = {
    "id": "1800000000000000002",
    "display_id": "1800000000000000001",
    "title": "Test Author - A test post",
    "description": "A test post with a video https://t.co/abc",
    "uploader": "Test Author",
    "uploader_id": "medialab_test",
    "duration": 15.5,
    "thumbnail": "https://pbs.twimg.com/amplify_video_thumb/1/img/x.jpg?name=orig",
    "extractor": "twitter",
    "extractor_key": "Twitter",
    "webpage_url": POST_URL,
}


def single_video_info() -> dict:
    return copy.deepcopy(
        {
            **BASE,
            "formats": [
                _progressive(288, 272, 270, 196863),
                _hls_video(191.8, 272, 270),
                _progressive(832, 640, 360, 553404),
                _progressive(2176, 1280, 720, 1404023),
                _hls_video(716.1, 1280, 720),
                _hls_video(4500.0, 1920, 1080),
                _hls_audio(128.0),
                _hls_audio(64.0),
                # Must be dropped: not on an allowlisted media host.
                {**_progressive(9999, 3840, 2160), "url": "https://evil.example.com/x.mp4"},
            ],
        }
    )


def multi_video_info() -> dict:
    first = {**BASE, "id": "111", "title": "Test Author - post #1", "formats": [_progressive(832, 640, 360, 1000)]}
    second = {
        **BASE,
        "id": "222",
        "title": "Test Author - post #2",
        "duration": 30,
        "formats": [_progressive(2176, 1280, 720, 5000), _progressive(832, 640, 360, 2000)],
    }
    return copy.deepcopy({**BASE, "_type": "playlist", "entries": [first, second]})


def vp9_only_info() -> dict:
    return copy.deepcopy(
        {
            **BASE,
            "formats": [
                {**_hls_video(3000, 1920, 1080, vcodec="vp09.00.40.08"), "format_id": "hls-vp9"},
                _hls_audio(128.0, acodec="opus"),
            ],
        }
    )
