# HTTP API

Base URL: `http://127.0.0.1:8000` (in development the UI calls `/api/*` through the Vite proxy on `:5173`). Interactive OpenAPI docs: `http://127.0.0.1:8000/docs`.

All examples below were captured from the running application (with the test suite's fake provider/processor where noted, so IDs and sizes are illustrative). Long lists are shortened with `"…"`.

## Conventions

- **Security:** loopback only. `Host` must be `127.0.0.1`, `localhost` or `::1`. Any `/api` request a browser marks cross-site (`Sec-Fetch-Site: cross-site`) or with a non-loopback `Origin` is refused with `403 forbidden`; state-changing methods also refuse `Origin: null`. No CORS headers. No authentication (single local user).
- **Bodies:** JSON, strict schemas (`extra="forbid"`): unknown fields → `422 validation_error`.
- **Errors:** always

  ```json
  {"error": {"code": "wrong_platform", "message": "This is an X link, not a TikTok link.",
             "retryable": false, "action": "Switch to the X tab.",
             "details": {"detected_platform": "x", "url": "https://x.com/a/status/1"}}}
  ```
  `code` is stable; `action` and `details` are optional. Codes, HTTP statuses and retryability are defined in `backend/app/errors.py`; see [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for what each means.

## Endpoint summary

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/analyse` | Validate a URL and return metadata, formats and resolution options |
| `POST` | `/api/download` | Start a download job for an analysed video |
| `GET` | `/api/jobs/{job_id}` | Job state, progress, finished file and delivery state |
| `POST` | `/api/jobs/{job_id}/cancel` | Cancel a queued, downloading or processing job (immediate) |
| `GET` | `/api/files/{file_id}` | Stream a finished file once (browser download) |
| `GET` | `/api/settings` | GUI settings, limits, temporary-storage info |
| `PATCH` | `/api/settings` | Change GUI settings |
| `GET` | `/api/tiktok-account` | Status of the optional TikTok sign-in |
| `PUT` | `/api/tiktok-account` | Link a TikTok cookies.txt (Short Drama only) |
| `DELETE` | `/api/tiktok-account` | Unlink and delete the cookie file |
| `GET` | `/api/shortdrama/series/{series_id}` | Series details and episodes |
| `POST` | `/api/shortdrama/batches` | Start a Short Drama batch (separate files, ZIP or merged MP4) |
| `POST` | `/api/bulk-analyses` | Validate pasted X/TikTok links and analyse them in the background (v1.9) |
| `GET` | `/api/bulk-analyses/{bulk_id}` | Bulk analysis progress and per-link results |
| `POST` | `/api/bulk-analyses/{bulk_id}/cancel` | Stop a bulk analysis |
| `POST` | `/api/batches` | Start a link batch from analysed X/TikTok videos (ZIP or separate files) |
| `GET` | `/api/batches/{batch_id}` | Any batch's state and result (alias: `/api/shortdrama/batches/{batch_id}`) |
| `POST` | `/api/batches/{batch_id}/{pause\|resume\|cancel\|continue}` | Batch control (alias under `/api/shortdrama/batches`) |
| `POST` | `/api/batches/{batch_id}/items/{n}/{retry\|cancel}` | Retry or cancel one item (alias: `/api/shortdrama/batches/{id}/episodes/{n}/…`) |

---

## POST /api/analyse

Request (`AnalyseRequest`):
```json
{"url": "https://x.com/medialab_test/status/1800000000000000001", "platform": "x"}
```
`platform` (optional) is the UI tab: `"x" | "tiktok" | "tiktok_shortdrama"`. A valid URL for another platform returns `wrong_platform` with `details.detected_platform`. Short links are resolved first and checked after resolution.

Response `200` (`AnalyseResponse`, fake provider):
```json
{
  "analysis_id": "a173e9d39f0040a4a2c457403446b121",
  "platform": "x",
  "provider": "fake",
  "post": {"url": "https://x.com/medialab_test/status/1800000000000000001", "post_id": "1800000000000000001",
           "author_name": "Test Author", "author_handle": "medialab_test",
           "text": "A test post with a video https://t.co/abc", "possibly_sensitive": null, "drama": null},
  "videos": [{
    "index": 1, "video_id": "1800000000000000002", "title": "Test Author - A test post", "duration_seconds": 15.5,
    "thumbnail_url": "https://pbs.twimg.com/amplify_video_thumb/1/img/x.jpg?name=orig",
    "formats": [{"format_id": "http-288", "ext": "mp4", "protocol": "https", "width": 272, "height": 270,
                 "fps": null, "vcodec": null, "acodec": null, "has_video": true, "has_audio": null,
                 "tbr": 288.0, "filesize": 196863, "filesize_approx": null, "mp4_compatible": true}, "…"],
    "options": [{"option_id": "best", "label": "Best Available (1080p)", "is_best": true, "width": 1920,
                 "height": 1080, "fps": 30.0, "vcodec": "avc1.64001F", "acodec": "mp4a.40.2", "has_audio": true,
                 "video_format_id": "hls-4500", "audio_format_id": "hls-audio-128000-Audio", "requires_merge": true,
                 "tbr": 4628.0, "filesize": null, "filesize_approx": 8966750, "downloadable": true,
                 "too_large": false, "audio_converted": false, "fallback_audio_format_id": null, "note": null}, "…"]
  }],
  "selected_video_index": 1,
  "expires_at": "2026-11-12T17:19:09Z"
}
```
For Short Drama, `post.drama` is `{"series_id", "series_title", "episode", "episode_count", "account_used"}`.

Errors: `invalid_url` (400), `unsupported_url` (400), `unsupported_episode_url` (400), `wrong_platform` (400), `short_link_expired` (404), `not_found` (404), `no_video` (422), `login_required` (403), `auth_expired` (401), `account_access_unavailable` (403), `episode_not_in_series` (404), `episode_resolution_failed` (502), `region_restricted` (451), `rate_limited` (429), `network_error`/`extraction_failed` (502), `timeout` (504), `busy` (429), `media_host_blocked` (422).

## POST /api/download

Request (`DownloadRequest`): `{"analysis_id": "<32 hex>", "video_index": 1, "option_id": "best"}`

Response `202` (`JobResponse`):
```json
{"job_id": "5d19272bddb540ffb8ab18595952cd5f", "state": "queued", "video_index": 1, "option_id": "best",
 "option_label": "Best Available (1080p)", "created_at": "2026-11-12T16:19:09.083915Z",
 "updated_at": "2026-11-12T16:19:09.083915Z",
 "progress": {"stage": "Waiting for a free download slot", "downloaded_bytes": 0, "total_bytes": 8966750,
              "total_is_estimate": true, "percent": 0.0, "speed_bytes_per_second": null, "eta_seconds": null},
 "file": null, "error": null}
```
Errors: `analysis_expired` (410), `invalid_selection` (400), `incompatible_format` (422), `file_too_large` (413), `insufficient_space` (507), `too_many_jobs` (429), `ffmpeg_missing` (500), `forbidden` (403, FxTwitter analysis after the fallback was disabled).

## GET /api/jobs/{job_id}

Response `200` when completed:
```json
{"job_id": "5d19272bddb540ffb8ab18595952cd5f", "state": "completed", "video_index": 1, "option_id": "best",
 "option_label": "Best Available (1080p)", "created_at": "…", "updated_at": "…",
 "progress": {"stage": "Ready to save", "downloaded_bytes": 2000, "total_bytes": 2000, "total_is_estimate": false,
              "percent": 100.0, "speed_bytes_per_second": null, "eta_seconds": null},
 "file": {"file_id": "cb29f56a901e4f679a629413d7daf1b3",
          "filename": "medialab_test - A test post with a video [1800000000000000001] 1080p.mp4",
          "size_bytes": 2000, "width": 1280, "height": 720, "fps": 30.0, "video_codec": "h264", "audio_codec": "aac",
          "duration_seconds": 15.5, "audio_converted": false, "source_audio_codec": null,
          "audio_silent_source": false, "download_url": "/api/files/cb29f56a901e4f679a629413d7daf1b3",
          "delivery_state": "ready", "available_until": "2026-11-12T16:49:09.085132Z"},
 "error": null}
```
`state`: `queued → downloading → processing → completed | failed`. `delivery_state`: `ready | delivering | delivered | expired`. A failed job has `error` in the standard error shape (e.g. `cdn_url_expired`, `download_interrupted`, `audio_missing`, `audio_conversion_failed`, `av_sync_failed`, `mp4_compatibility`, `processing_failed`, `file_too_large`, `timeout`). Unknown ID: `job_not_found` (404).

## POST /api/jobs/{job_id}/cancel

Cancels a queued, downloading or processing job. No body. Used by the **Cancel** button next to the progress bar and by the Downloads drawer (same job).

```bash
curl -s -X POST http://127.0.0.1:8000/api/jobs/5d19272bddb540ffb8ab18595952cd5f/cancel
```

Response `200`: the `JobResponse`, already in its final state (v1.9; before, cancelled jobs ended as `failed`):
```json
{"job_id": "5d19272bddb540ffb8ab18595952cd5f", "state": "cancelled", "…": "…",
 "progress": {"stage": "Cancelled", "…": "…"}, "file": null,
 "error": {"code": "download_cancelled", "message": "The download was cancelled.", "retryable": false}}
```

- The state changes at once, under the job manager's lock. The worker then stops: the transfer at its next progress update (yt-dlp reports every chunk; a stalled connection is noticed at the next chunk or the 20 s socket timeout), a running **FFmpeg/FFprobe is killed** within 0.2 s, and the job folder is removed.
- A cancelled job can never become `completed`: completion re-checks the state under the same lock before the MP4 is handed to delivery, so a late callback can't revive it.
- **Idempotent:** cancelling twice, or cancelling a job that has already completed, failed or been cancelled, returns `200` and changes nothing (a completed file stays available until it is saved or expires).
- Job `state` values: `queued | downloading | processing | completed | failed | cancelled`.
- Unknown or malformed ID: `job_not_found` (404).
- Same-origin guard as every state-changing route: cross-site requests and `Origin: null` are refused with `403 forbidden`.

## GET /api/files/{file_id}

Streams the file once as an attachment:
```
HTTP 200
Content-Type: video/mp4            (application/zip for ZIP batches)
Content-Disposition: attachment; filename="…"; filename*=utf-8''…
Cache-Control: no-store
```
After a complete transfer MediaLab deletes its copy; a second request returns
```json
{"error": {"code": "file_not_found", "retryable": false, "action": "Click Download MP4 to fetch the video again.",
           "message": "This video was already saved. MediaLab deleted its temporary copy; download it again if needed."}}
```
`409 delivery_in_progress` while another transfer of the same file is running. An interrupted transfer returns the file to `ready` until it expires.

## GET /api/settings · PATCH /api/settings

`GET` response:
```json
{"fxtwitter_fallback": false, "fxtwitter_host": "api.fxtwitter.com", "max_file_size_mb": 8192,
 "file_size_limits": {"min_mb": 256, "max_mb": 65536, "presets_mb": [2048, 8192, 16384]},
 "batch_output_max_mb": 32768,
 "batch_output_limits": {"min_mb": 256, "max_mb": 262144, "presets_mb": [8192, 32768, 65536]},
 "temp_storage": {"auto_cleanup": true, "retention_minutes": 30, "usage_bytes": 0}, "saved": false}
```
`PATCH` accepts any subset of `{"fxtwitter_fallback": bool, "max_file_size_mb": int, "batch_output_max_mb": int}` (strict types, bounded) and returns the same shape. Example error:
```json
{"error": {"code": "validation_error", "retryable": false,
           "message": "Invalid request: max_file_size_mb: Input should be greater than or equal to 256"}}
```

## TikTok account

`GET /api/tiktok-account`:
```json
{"linked": false, "cookie_count": 0, "session_expires_at": null, "expired": false, "saved_at": null}
```
`PUT /api/tiktok-account` with `{"cookies_txt": "<Netscape cookies.txt text, ≤ 1 MB>"}` keeps only tiktok.com cookies and returns the status. Cookie values are never returned. Error example:
```json
{"error": {"code": "validation_error", "retryable": false, "action": "Check the request and try again.",
           "message": "This isn't a cookies.txt file. Export your tiktok.com cookies in Netscape format (cookies.txt)."}}
```
`DELETE /api/tiktok-account` deletes the local file (it does not sign the session out at TikTok).

## GET /api/shortdrama/series/{series_id}

`series_id`: 5–25 digits (else `invalid_url`). Uses the linked account if present; cached 5 minutes. Example (fake TikTok responses):
```json
{"series_id": "7100000000000000101", "title": "Harbor & Crown Example 2", "description": null,
 "episode_count": 5, "cover_url": "https://p16-common-sign.tiktokcdn-eu.com/c.jpg",
 "publisher_handle": "example.studio.a", "publisher_name": null, "account_used": true,
 "episodes": [{"number": 1, "item_id": "7100000000000001001", "title": "Harbor & Crown Example 2 EP1",
               "duration_seconds": 115.0, "thumbnail_url": "https://p16-common-sign.tiktokcdn-eu.com/tos/cover.image",
               "available": true, "availability": "available", "publisher_handle": "example.studio.a"}, "…"]}
```
`availability`: `available | login_required | locked`. Errors: `series_metadata_unavailable` (502), `auth_expired` (401), `busy`, `timeout`.

## POST /api/shortdrama/batches

Request (`BatchCreate`):
```json
{"series_id": "7100000000000000101", "episodes": [1, 2, 3], "quality": "best", "strict": false,
 "concurrency": 1, "output": "merge", "allow_partial": false}
```
| Field | Values |
|---|---|
| `episodes` | 1–500 episode numbers (order irrelevant) |
| `quality` | `"best"` or `"<digits>p"` (e.g. `"720p"`) |
| `strict` | fail episodes lacking the preferred resolution instead of falling back |
| `concurrency` | 1 (default) or 2 |
| `output` | `"files"` (each episode saved separately), `"zip"`, `"merge"` |
| `allow_partial` | package without failed episodes instead of stopping for a decision |

Response `202`: a `BatchResponse` (below). Errors: `episode_not_in_series` (404), `batch_in_progress` (409, `details.batch_id`), `too_many_jobs` (429), `validation_error` (422), `ffmpeg_missing`.

## POST /api/bulk-analyses

Validates pasted links and analyses each distinct one in the background (two at a time). Request (`BulkCreate`):
```json
{"platform": "x", "urls": ["https://x.com/a/status/1", "", "  https://twitter.com/b/status/1  ", "https://www.tiktok.com/@u/video/7"]}
```
| Field | Values |
|---|---|
| `platform` | `"x"` or `"tiktok"` (Short Drama uses series batches) |
| `urls` | 1–500 lines of at most 4096 characters; blank lines are ignored and whitespace trimmed |

Every line goes through the same validation as `POST /api/analyse`. At most `MEDIALAB_MAX_BULK_URLS` (default 50) **distinct** valid links per request; duplicates and invalid lines don't count. Two bulk analyses may run at once.

Response `202`, then poll `GET /api/bulk-analyses/{bulk_id}` (same shape):
```json
{"bulk_id": "9f…", "platform": "x", "state": "done", "limit": 50,
 "counts": {"waiting": 0, "analysing": 0, "ready": 1, "failed": 0, "invalid": 1, "duplicate": 1, "cancelled": 0},
 "items": [
  {"index": 1, "input": "https://x.com/a/status/1", "state": "ready", "canonical_url": "https://x.com/a/status/1",
   "duplicate_of": null, "analysis_id": "c3…", "title": "…", "author": "a", "duration_seconds": 15.5,
   "thumbnail_url": "https://pbs.twimg.com/…", "video_count": 1, "video_index": 1, "qualities": ["720p", "360p"],
   "estimates": {"best": {"label": "Best Available (720p)", "size_bytes": 1404023, "size_is_estimate": false, "note": null},
                 "480p": {"label": "360p", "size_bytes": 553404, "size_is_estimate": false,
                          "note": "480p isn't available; used 360p, the next lower resolution."}, "…": "…"},
   "error": null},
  {"index": 2, "input": "https://twitter.com/b/status/1", "state": "duplicate", "duplicate_of": 1, "…": "…"},
  {"index": 3, "input": "https://www.tiktok.com/@u/video/7", "state": "invalid",
   "error": {"code": "wrong_platform", "message": "This is a TikTok link, not an X link.",
             "action": "Switch to the TikTok Videos tab.", "details": {"detected_platform": "tiktok", "url": "…"}}}]}
```
- Item `state`: `waiting | analysing | ready | failed | invalid | duplicate | cancelled`; bulk `state`: `running | done | cancelled`.
- Duplicates are matched by post ID (X: plus the video number), so `x.com` and `twitter.com` links of one post match; TikTok share links are compared after they are resolved.
- `estimates` gives, per quality preference (`best`, `1080p`, `720p`, `480p`), the option a batch would use, its size and the fallback note.
- Errors: `validation_error` (422: nothing pasted, too many distinct links with `details.valid`/`limit`, other platforms), `invalid_url` (none of the lines is usable), `busy` (429, two analyses running).
- `POST /api/bulk-analyses/{bulk_id}/cancel`: waiting links become `cancelled`; a link already being extracted can't be interrupted, its result is discarded. Unknown ID: `bulk_not_found` (404). Results are kept for an hour after the analysis ends.

## POST /api/batches

Downloads analysed X or TikTok videos as one queue. Request (`UrlBatchCreate`):
```json
{"platform": "x", "analysis_ids": ["c3…", "d4…"], "quality": "720p", "output": "zip", "concurrency": 2, "allow_partial": false}
```
| Field | Values |
|---|---|
| `analysis_ids` | 1–100 IDs from a bulk analysis (at most `MEDIALAB_MAX_BULK_URLS`), in download order; all of `platform` |
| `quality` | `best`, `1080p`, `720p`, `480p`. Fallback: the next lower resolution the video offers, else the closest higher one; never upscaled; options with audio preferred |
| `output` | `zip` (one archive, entries `01 - <name>.mp4` in this order, plus `MediaLab manifest.txt` listing omitted videos when some are missing) or `files` (each video delivered on its own; the browser saves them as they finish) |
| `concurrency` | 1–4, capped by `MEDIALAB_MAX_CONCURRENT_DOWNLOADS` (default 2) |
| `allow_partial` | ZIP: build without failed videos instead of stopping for a decision |

Response `202`: a `BatchResponse` with `source: "urls"` and `platform`; items are numbered in input order and carry `title`, `author`, `duration_seconds` and `thumbnail_url`. Errors: `analysis_expired` (410), `wrong_platform`, `validation_error` (duplicates, `merge`, sizes), `batch_in_progress` (409, an identical batch is running; `details.batch_id`), `too_many_jobs` (429, two batches already active), `forbidden` (an FxTwitter analysis while the fallback is off), `ffmpeg_missing`.

Every item runs as a normal download job (same size limit, free-space check, audio verification). The batch output limit applies to the ZIP. If an analysis expires before its item starts (an hour), the item re-analyses its link once.

## GET /api/shortdrama/batches/{batch_id}

Also served as `GET /api/batches/{batch_id}` (every batch). Since v1.9 the response also has `source` (`shortdrama` or `urls`), `platform` and `stopped`.

Example (merge batch, ready; fake media):
```json
{"batch_id": "841470d6c07e41fc89c76b873ef1fd8a", "series_id": "7100000000000000101",
 "series_title": "Harbor & Crown Example 2", "quality": "720p", "strict": true, "concurrency": 1,
 "output": "merge", "allow_partial": false, "state": "ready", "stage": "Ready to save",
 "plan_note": "All episodes use 720p (H265), the highest quality every selected episode offers, so they can be joined without re-encoding.",
 "package_percent": 100.0,
 "counts": {"pending": 0, "resolving": 0, "downloading": 0, "processing": 0, "ready": 0, "saving": 0, "saved": 0,
            "downloaded": 3, "failed": 0, "skipped": 0, "cancelled": 0},
 "percent": 97.0, "estimated_duration_seconds": 345.0, "estimated_size_bytes": 12288,
 "episodes": [{"number": 1, "item_id": "7100000000000001001", "title": "Harbor & Crown Example 2 EP1",
               "state": "downloaded", "stage": "Downloaded", "percent": 100.0, "downloaded_bytes": 4096,
               "total_bytes": 4096, "option_label": "720p", "note": null, "attempts": 1, "file_id": null,
               "filename": "Harbor & Crown Example 2 - E01.mp4", "size_bytes": 4096, "download_url": null,
               "error": null}, "…"],
 "result": {"file_id": "acd156fd47754a78ab4bad9b19be350f", "filename": "Harbor & Crown Example 2 - E01-E03.mp4",
            "size_bytes": 12288, "kind": "mp4", "method": "stream_copy", "reason": null, "duration_seconds": 30.0,
            "included": [1, 2, 3], "omitted": [], "width": 1280, "height": 720, "video_codec": "h264",
            "audio_codec": "aac", "download_url": "/api/files/acd156fd47754a78ab4bad9b19be350f",
            "delivery_state": "ready"},
 "error": null}
```
Batch `state`: `planning | running | paused | needs_decision | packaging | ready | saving | completed | partial | failed | cancelled`. Episode `state`: `pending | resolving | downloading | processing | ready | saving | saved | downloaded | failed | skipped | cancelled`. `error` carries `batch_partial` (with `details.failed`/`downloaded`) in `needs_decision`, the packaging error in `failed`, and a summary in `partial`/`cancelled`. Unknown ID: `batch_not_found` (404).

## Batch control

- `POST …/pause`: no new episodes start; running ones finish.
- `POST …/resume`
- `POST …/cancel`: cancels waiting and running items (their jobs immediately, see job cancel) and kills packaging.
  - **Short Drama:** deletes unsaved and collected files (never a file being transferred); the batch ends `cancelled`.
  - **Link batches (v1.9):** finished videos are kept. `files`: ready videos stay saveable until they are saved or expire, and the batch ends `partial`. `zip`: the batch goes to `needs_decision` with `stopped: true`, so `continue` builds the ZIP from the finished videos; a second `cancel` deletes them. If nothing had finished, it ends `cancelled` as above. A ready or saving output is left alone (it expires normally).
- `POST …/continue`: in `needs_decision`: package without the failed or cancelled items; in `failed`: retry packaging.
- `POST /api/batches/{id}/items/{n}/retry` (alias `…/episodes/{n}/retry`): retry a failed, skipped or cancelled item (reopens a finished batch).
- `POST /api/batches/{id}/items/{n}/cancel` (alias `…/episodes/{n}/cancel`): cancel one waiting or running item; the others continue. Idempotent for an already cancelled item; a finished item gives `validation_error` (422); an unknown number `item_not_found` (404).

All return the updated `BatchResponse`.
