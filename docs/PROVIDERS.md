# Providers

A provider turns a validated URL into `PostMetadata` (analysis) and downloads selected formats (download). All providers implement `providers/base.py`:

```python
class VideoProvider(ABC):
    name: str = "provider"
    def provider_for(self, name: str | None, platform: str | None = None) -> "VideoProvider": return self
    @abstractmethod
    def extract(self, url: ValidatedUrl) -> PostMetadata: ...
    @abstractmethod
    def download(self, url, video_index: int, format_ids: list[str], dest_dir: Path,
                 on_progress: ProgressCallback) -> dict[str, Path]: ...
```

Contract:
- `extract` never downloads media. It returns only formats whose URLs passed the platform's media-host check, and raises `AppError` on failure.
- `download` writes each requested format into `dest_dir` and returns `{format_id: path}`. Exceptions raised by `on_progress` (size/time limits, cancellation) must propagate.
- Unknown metadata stays `None`; providers never guess codecs or audio presence.

The wiring is in `main.build_default_provider`:

| Platform key | Provider |
|---|---|
| `x` | `ProviderChain(YtDlpProvider("x"), FxTwitterProvider, enabled=<GUI setting>)` |
| `tiktok` | `YtDlpProvider("tiktok")` (+ `drama_probe` for wrong-tab hints) |
| `tiktok_shortdrama` | `TikTokShortDramaProvider(settings, account_store)` |

`PlatformRouter` dispatches by `ValidatedUrl.platform` and stamps `post.provider` with the answering provider's name, which the job later uses (`provider_for`) so the same provider downloads what it analysed.

---

## yt-dlp provider (X and TikTok Videos)

`providers/ytdlp_provider.py`, `providers/ytdlp_normalise.py`

| | |
|---|---|
| **Purpose** | Extraction and download via yt-dlp's `twitter` or `tiktok` extractor |
| **URL formats** | X: `x.com|twitter.com/<handle>/status/<id>[/video/<n>]`, `/i/web/status/<id>`, `/statuses/<id>`; TikTok: `tiktok.com/@<user>/video/<id>`, `m.tiktok.com/v/<id>.html`, short links `vm.`/`vt.tiktok.com/<code>`, `tiktok.com/t/<code>` (resolved first by `resolve.py`) |
| **Dependencies** | `yt-dlp[curl-cffi]` (TikTok needs browser TLS impersonation), FFmpeg location passed to yt-dlp |
| **Authentication** | None. `cookiefile=None`, `cookiesfrombrowser=None`, `usenetrc=False`, no cache |

**Analysis**
1. `YoutubeDL(allowed_extractors=[extractor])`, `extract_info(url, download=False, process=False)`: metadata only.
2. `_sanitise`: reject URL-type results; drop formats not on the platform's media hosts; TikTok: drop "unplayable" (bytevc2), drop watermarked variants when clean ones exist, **drop the separate `audio` (music) track** (see below), and disambiguate mirrored duplicate IDs (`<id>-0`, `<id>-1`) exactly as yt-dlp would.
3. `process_ie_result(download=False)`; X progressive MP4s get exact sizes via `HEAD` (only to allowlisted URLs).
4. `normalise_info` → `PostMetadata` (TikTok: `uploader` → handle, `channel` → name).
5. Transient failures retry (3 attempts, 1 s/2 s).

**Format discovery.** yt-dlp lists TikTok's `bitrateInfo` renditions (`h264_540p_<bitrate>`, `bytevc1_720p_<bitrate>`, …) and X's HLS/progressive variants. Audio presence comes from yt-dlp's `acodec`; note that for TikTok yt-dlp *assumes* AAC unless the URL path marks the stream video-only, which is unreliable (see [MEDIA_PIPELINE.md](MEDIA_PIPELINE.md#when-metadata-lies-about-audio)).

**Download.** `format: "a,b"` downloads each selected format separately; MediaLab merges them itself. Up to 3 attempts: HTTP 403 → re-extract with fresh signed URLs (TikTok: the mirror); interrupted transfer → back off 2 s/4 s. When TikTok serves a different encode of the same rendition between analysis and download, the equivalent ID (same codec, resolution, mirror) is used.

**Errors.** `map_ytdlp_error` maps extractor messages to codes (TikTok rules first: region → `region_restricted`; "not available"/10204 → `not_found`; no formats → `no_video`; login → `login_required`; then shared rules for DRM, rate limits, 403, timeouts, network). Unrecognised messages become `extraction_failed` with yt-dlp's first line, so nothing is mislabelled.

**TikTok's separate `audio` track (v1.6).** TikTok items carry a `music.playUrl`. On ordinary videos it is **not reliably the video's own audio**: in a 2026-11-12 measurement it matched one video's audio exactly and differed from another's (loudness correlation 0.27) even though both were labelled "original sound", and on videos using a licensed song it is the song. The TikTok Videos tab therefore never pairs it with video-only streams; such streams are offered as "No audio track" and are never Best Available when a rendition with audio exists.

**Limitations.** TikTok changes often (keep yt-dlp updated); private, follower-only, region-blocked videos fail with specific errors; photo slideshows, Live, profiles are rejected at validation.

---

## FxTwitter provider (optional, X only)

`providers/fxtwitter_provider.py`, `providers/chain.py`

| | |
|---|---|
| **Purpose** | Metadata fallback when yt-dlp reports `no_video`/`not_found` for an X post (e.g. X's empty "tombstone" responses to logged-out clients) |
| **Enabled** | Settings → FxTwitter fallback (off by default), read live on every analysis |
| **Request** | `https://api.fxtwitter.com/2/status/<numeric id>`: only the post ID; no cookies; response capped at 2 MB |
| **Download** | Directly from X's CDN (`*.twimg.com`) through `net.open_url` (every redirect hop validated, Content-Type/Length checked) |
| **Errors** | FxTwitter tombstones `private`/`deleted`/`suspended`/`blocked` and HTTP 401/404 are honoured as access controls; `possibly_sensitive` is informational only |

The chain consults the fallback only for `no_video`/`not_found` from yt-dlp; any other error is returned as is. If the fallback is disabled after an FxTwitter analysis, the download is refused (`forbidden`).

---

## TikTok Short Drama provider

`providers/tiktok_shortdrama.py`, `tiktok_account.py`

| | |
|---|---|
| **Purpose** | Episodes of TikTok Short Drama series: single episodes, series listings, direct episode links |
| **URL formats** | share links (`vm.tiktok.com/…`), item links (`tiktok.com/@<publisher>/video/<item>`), direct links (`tiktok.com/shortdrama/episode/<series>/<n>`) |
| **Dependencies** | yt-dlp TikTok extractor (two private methods: `_extract_web_data_and_status`, `_parse_aweme_video_web`), `curl-cffi` |
| **Authentication** | Optional linked TikTok cookies (see [SECURITY.md](SECURITY.md#tiktok-account)); without them, episodes are locked previews |

**How episodes are represented (observed 2026-11-12).** An episode is an ordinary TikTok item whose data has `dramaInfo` (series ID/title, `numVideos`) and `DramaVideoData` (`EpisodeNumber`, `IsPreview`, `PreviewType`, `LinkedEpisodeID`). Logged out, items are locked previews without streams; signed in, the same item lists progressive MP4 renditions (HEVC video-only + a separate MP3 "original sound" track, and H.264 with AAC).

**Analysis.**
1. Direct links → `series(series_id)` → find episode `n` → item URL. Share links are resolved by `resolve.py`; item links are adopted by the tab.
2. `_raw_info`: fetch the item page via the yt-dlp TikTok IE (one page load), map status codes (`203008` → `not_found`, `10216/10222` → `unavailable`, `10204` → `not_found`), require `dramaInfo` (else `wrong_platform`), require a stream (else `login_required` without account / `account_access_unavailable` with account), then parse with yt-dlp's own parser.
3. The separate `audio` track is kept only when TikTok marks the item's music as `original: true`. Measured 2026-11-12 on episodes 1, 2, 5 and 14 of one series: the track has the same length as the episode and its loudness pattern matches the H.264 rendition's built-in AAC audio (r = 0.969–0.977).
4. The shared yt-dlp sanitising/processing path runs; `DramaInfo` (series, episode, count, account used) is attached.

**Series.** `series(series_id)` calls `GET https://www.tiktok.com/api/drama/detail/?dramaID=…` and `…/api/drama/episode/item_list/?dramaID=…&count=24&cursor=…` (plain requests, no signatures), paginates up to 500 episodes, filters thumbnails to TikTok's CDN, orders by episode number and caches the result for 5 minutes per (series, signed-in?).

**Errors.** `login_required`, `auth_expired`, `account_access_unavailable`, `episode_not_in_series`, `episode_resolution_failed`, `series_metadata_unavailable`, `not_found`, `wrong_platform`. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

**Limitations / maintenance.**
- Depends on private yt-dlp methods; on a yt-dlp upgrade, run `make test` and a live check (see [TESTING.md](TESTING.md#live-checks)).
- Depends on TikTok's web endpoints answering unsigned requests; if that changes, direct links and series views fail with `series_metadata_unavailable` while share links keep working.
- TikTok doesn't say why an episode is locked (coins, ads, subscription), so MediaLab doesn't claim a payment requirement.

---

## Adding a provider

Example: a new platform `example`.

1. **Validation** (`validation.py`): add `PLATFORM_EXAMPLE`, its label/tab name, an allowlist of page hosts and a path pattern that **rebuilds** the canonical URL from parsed IDs; add a media-host predicate for its CDN. Add tests in `tests/test_validation.py`.
2. **Provider** (`providers/example_provider.py`): implement `extract`/`download` (or, for a yt-dlp-supported site, add a `PlatformSpec` in `platform_spec()` with the extractor name, host predicate and filters). Map failures to `AppError` codes; never return formats on unvalidated hosts.
3. **Wiring** (`main.build_default_provider`): add the provider to the `PlatformRouter` dict.
4. **API schema** (`schemas.AnalyseRequest.platform`) and **frontend** (`lib/types.ts` `Platform`, `lib/platform.ts` `PLATFORM_INFO` + detection): add the platform key. Nothing else in the API, jobs, media pipeline or UI flow needs to change.
5. **Tests**: a fake-network provider test like `tests/test_tiktok.py` (inject a fake `YoutubeDL`), plus error-matrix entries.
6. **Docs**: this file, [SECURITY.md](SECURITY.md) (new hosts), [API.md](API.md).

Keep the security properties: no user-controlled URLs reach the network layer; redirects are validated; credentials (if any) are opt-in, scoped to the provider and never returned or logged.
