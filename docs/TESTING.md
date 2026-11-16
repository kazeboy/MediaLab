# Testing

## Summary

| Suite | Command | Count (v1.8) | Network | Needs |
|---|---|---|---|---|
| Backend (pytest) | `make test-backend` | 571 | none | Python venv; FFmpeg for the media integration tests (skipped otherwise) |
| Frontend type-check | `cd frontend && npm run typecheck` | n/a | none | Node |
| Frontend unit + component tests (Vitest) | `cd frontend && npm test` | 84 (14 files) | none | Node (jsdom is a dev dependency) |
| Frontend production build | `cd frontend && npm run build` | n/a | none | Node |
| Everything | `make test` | n/a | none | n/a |
| Live checks | manual (below) | n/a | yes | Internet; a linked TikTok account for Short Drama |

No automated test contacts X, TikTok or FxTwitter, and none needs a TikTok account.

## Backend test structure (`backend/tests/`)

| File | Tests | Covers |
|---|---|---|
| `test_validation.py` | 52 | URL allowlists, canonicalisation, rejected forms |
| `test_analysis.py` | 20 | Normalisation, option building, Best Available, size limits |
| `test_api.py` | 39 | Endpoints (incl. job cancel), error shapes, Host/Origin/cross-site guard |
| `test_jobs.py` | 12 | Job state machine, progress, limits |
| `test_delivery.py` | 22 | Streaming delivery, exactly-once deletion, interrupted transfers, expiry |
| `test_storage.py` | 16 | Filenames, cleanup roots, free space, folder permissions |
| `test_settings.py` | 19 | GUI settings bounds, persistence, precedence |
| `test_ytdlp_provider.py` | 19 | yt-dlp parameters, sanitising, error mapping |
| `test_fxtwitter.py` | 47 | FxTwitter parsing, tombstones, redirect validation, chain |
| `test_tiktok.py` | 74 | TikTok URLs, short links, formats/mirrors/watermarks, 403 retry, separate-track policy |
| `test_shortdrama.py` | 80 | Account linking/privacy, episodes, series, direct links, batches (files/ZIP/merge), failure policy, cancellation, limits |
| `test_media.py` | 9 | FFprobe parsing, assembling, `hvc1` tagging (real FFmpeg) |
| `test_audio.py` | 31 | Audio matrix with real FFmpeg (HEVC/H.264 × AAC/MP3/Opus, video-only, missing, silent, mismatch, unsupported), output validation, soundtrack fallback |
| `test_packaging.py` | 25 | ZIP integrity/order/names/cancel/ZIP64, merging (copy, mixed codecs, resolutions, frame rates, timestamps, missing audio), per-segment audio, cancellation, stalled FFmpeg, missing libx264 |
| `test_error_matrix.py` | 68 | Every analysis/job error path across platforms, retries, wording |
| `test_config.py` | 3 | Environment parsing |
| `test_bulk.py` | 32 | v1.9: bulk analysis (blank lines, duplicates across x.com/twitter.com, wrong platform, invalid, limit of 50 distinct links, one extraction per link, cancel during analysis), link batches (input order and names in the ZIP, two concurrent downloads, server-side concurrency cap, separate files, expiry and retry, partial failure decision and manifest without links, retry, nothing downloaded gives no archive, batch output limit, request validation, duplicate batches and jobs), cancellation (waiting and running item, double cancel, whole batch keeps finished videos for ZIP and separate files, second cancel discards, cancel during ZIP packaging, during FFmpeg processing with a late completion, queued job never starts, a running subprocess killed), quality fallback, restart wording |
| `test_version.py` | 2 | Version declarations aligned (1.9.0 in `app`, API, `pyproject.toml`, `package.json`, lockfile); `/openapi.json` builds and lists every route |

### Mocked vs. integration

- **Network is always faked.** Providers get a fake `YoutubeDL` (`test_tiktok.FakeYDL`, `test_shortdrama.make_ydl_class`). The Short Drama tests run yt-dlp's **real** TikTok parser on item data shaped like what TikTok returned live (logged-out locked preview vs. signed-in renditions) and fake the series endpoints.
- **Media is real where it matters.** `test_media.py`, `test_audio.py` and `test_packaging.py` generate small clips with FFmpeg (`testsrc`, `sine`, `anullsrc`) and run the real `MediaProcessor` / packaging code. They're skipped when FFmpeg (or a specific encoder such as `libx265`, `libmp3lame`, `libopus`) is missing.
- **API tests** use FastAPI's `TestClient` with `FakeProvider`/`FakeProcessor` (`conftest.py`), which write small fake files.

## Frontend tests

Vitest; pure-logic tests run in Node, component tests opt into jsdom (`// @vitest-environment jsdom`) and use Testing Library + user-event. The network is mocked at the `lib/api` module boundary; saving is mocked at `lib/save.saveWithBrowser`. Setup: `src/test/setup.ts`; response builders: `src/test/fixtures.ts`.

| File | Tests | Covers |
|---|---|---|
| `lib/__tests__/platform.test.ts` | 11 | Platform detection, wrong-tab suggestions |
| `lib/__tests__/selection.test.ts` | 6 | Shift-click ranges, "from episode N", keep-accessible, selection summary |
| `lib/__tests__/format.test.ts` | 3 | Size/duration formatting |
| `lib/__tests__/save.test.ts` | 3 | Folder saving never overwrites (unique names) |
| `components/__tests__/ui.test.tsx` | 5 | Tabs (roving tabIndex, arrows/Home/End, short labels), Dialog (focus trap, Escape, focus and scroll restore), ErrorAlert (message first, details second, Switch button) |
| `components/__tests__/activity.test.tsx` | 5 | Downloads drawer + registry: empty state, polling to "ready to save" and Save, Retry, Cancel, lost entries after a backend restart |
| `lib/__tests__/theme.test.tsx` | 6 | The **inline pre-render script from `index.html`**: dark when nothing is saved (even with a light OS appearance), saved light/dark applied, unknown values and blocked storage → dark, key/colours match `lib/theme.ts`; `useTheme` toggles, applies to `<html>`, persists across a simulated reload, still switches if storage can't be written |
| `components/__tests__/app.test.tsx` | 8 | The whole `App`: header branding (one `h1` named "MediaLab", decorative emblem); **theme toggle** (starts dark with a sun and "Switch to light theme" label/tooltip, click and Enter/Space switch, choice persists across remount, placed next to Settings); drawer from the header (Escape, focus return); **Save Video, Cancel and Retry from another platform tab** after switching with the keyboard; Settings focus return and section keyboard navigation |
| `components/__tests__/shortdrama.test.tsx` | 7 | Series list order, locked episodes, current-episode preselection, Shift-click, select all/clear/quick range/from N, output change, Options rules, Episode ↔ Series with the analysis kept, **a running batch keeps its progress and Save ZIP across Episode/Series switches** (selection locked while it runs) |
| `lib/__tests__/bulk.test.ts` | 4 | Bulk preview parsing: blank lines, trimming, duplicates, other tabs, empty paste |
| `components/__tests__/workflows.test.tsx` | 13 | v1.9: New Download (reset and focus, running job kept in Downloads, unsaved file still saveable, stale analysis ignored, same URL reused, other tabs untouched, failed analysis cleared); Cancel during processing and the cancelled state; duplicate start follows the running job; Single/Bulk switching; bulk limit and line counts; review, deselect, quality and the batch request; item and batch cancel and New Bulk Download; build the ZIP after a stop; cross-tab (X bulk batch, TikTok download, cancel the X batch from Downloads) |
| `components/__tests__/settings.test.tsx` | 2 | Sections and saving limits; TikTok section shows status only (never cookie values) |

Not covered by automated frontend tests: real browser saving (download prompts, the folder picker), layout and contrast (see the audit below), and timing against a real backend (see live checks).

## Visual and accessibility audit

Done in the in-app Chromium browser against the running app (`make dev`) for each release that changes the UI. **v1.8.1** (fonts, favicon, copy) repeated the measured audit at all four widths in both themes, adding a check of the computed font family of every text node (headings Manrope, everything else DM Sans or monospace, wordmark system font) and the layout shift while fonts load (0.002): no failures. **v1.8** covered the same views plus live **error**, **batch progress**, **batch ready** and **single download ready** states and the header/logo, at **1600×1000, 1280×900, 768×1024 and 375×812** in light and dark: no contrast failures, no overflow, no clipped text, sticky bar pinned; lowest body text 5.46:1 (light) / 5.33:1 (dark), large wordmark 3.9:1 (needs 3:1); light-mode focus ring `#B45309` confirmed with real Tab presses. After the theme update (dark default, toggle, cool-grey light palette) the audit was repeated through the header toggle rather than OS emulation, at all four widths for the header, X, TikTok, Episode, Series, Downloads and Settings: no failures; light body text ≥ 5.3:1, light wordmark 3.82:1, dark unchanged. Dark-by-default was confirmed with the browser emulating a light OS appearance, and a saved light choice survived a reload with a dark OS appearance. Logo assets were rendered with headless Chrome at 16–512 px on light and dark backgrounds. v1.7 covered **X, TikTok Videos, Short Drama Episode, Short Drama Series, the Downloads drawer and all three Settings sections**, at **1280×900, 768×1024 and 375×812**, in **light and dark** (`prefers-color-scheme` emulation):

1. **Measured (script in the page):** horizontal overflow of the document; text clipped by its box (excluding `.sr-only`); WCAG contrast of every visible text node against its effective background (with transitions disabled so mid-animation colours aren't sampled); active-tab background; sticky bar pinned to the viewport bottom without covering the last row; dialog/drawer size per breakpoint; heading order; hit-target sizes.
2. **Keyboard:** real Tab key presses (programmatic `focus()` doesn't trigger `:focus-visible`) to check the focus ring; arrow keys on tabs; Escape and focus return for dialogs.
3. **Screenshots** of every view per width/theme, reviewed by eye.

v1.7 results: no overflow, no clipped text, minimum contrast 4.91:1 (light) / 6.33:1 (dark); defects found and fixed: disclosure summaries were 20 px tall (now ≥ 36 px), and the global focus style overrode `outline-none`, drawing a ring around the whole drawer/dialog container when it opened (moved into `@layer base`). Screenshots were taken at the pane's reduced scale, which is enough for layout and colour but not for pixel-level detail.

## Security regression tests

- Cross-site requests of every method refused; Host header checks (`test_api.py`).
- URL rejection: credentials, ports, IPs, foreign hosts, unsafe paths (`test_validation.py`).
- Redirect validation hop by hop (`test_fxtwitter.py`, `test_tiktok.py`).
- Cookie handling: only tiktok.com cookies kept, `0600`, values never in responses, in-memory loading, never used by the TikTok Videos provider (`test_shortdrama.py`).
- Unsafe ZIP entry names refused; owner-only working folders (`test_packaging.py`, `test_storage.py`).

## Audio verification

Automated tests check audio **presence, codec, sync and non-silence** with FFmpeg. They can't prove that a particular player plays the file, or that the sound is the *right* sound. For media changes, also do:

1. **AVFoundation decode (macOS):** the framework QuickTime and Safari use. A small Swift program can load the file with `AVURLAsset`, list its tracks (an MP3-in-MP4 track simply doesn't appear) and decode the audio with `AVAssetReader` to measure its RMS level. This is how the v1.3/v1.4 silent-audio bug was confirmed and how v1.4–v1.6 outputs were checked during development.
2. **Right soundtrack:** compare the loudness envelope of the output's audio with a reference rendition of the same video (e.g. TikTok's H.264 rendition with built-in audio); a high correlation (≥ 0.95) with equal lengths indicates the same soundtrack. This is how the TikTok separate-track policy was established.
3. **By ear in QuickTime Player:** open the MP4, play the start, middle and end; for merged files, listen across at least one episode boundary.

## Live checks

Run after updating yt-dlp, FFmpeg or provider code (small selections only):

| Check | Expected |
|---|---|
| X: analyse + download a public video post, smallest option | MP4 with H.264 + AAC, plays with sound |
| TikTok Videos: analyse + download a public video | H.264 + AAC; no separate "audio" format listed |
| Short Drama (linked account): share link, 720p | HEVC (`hvc1`) + AAC "converted from MP3"; audible |
| Short Drama: direct `/shortdrama/episode/<series>/<n>` | Same item as the share link |
| Series: Open series | All episodes in order with durations/availability; the analysed episode preselected |
| Downloads drawer: Save / Cancel from another tab | Works without returning to the tab; temp storage 0 after Save or Cancel |
| Batch ZIP of 2–3 episodes | One ZIP, correctly named MP4s, each audible |
| Batch merge of 2–3 episodes | "joined without re-encoding", duration = sum, audio across boundaries |
| After each | Settings → temporary storage 0 bytes |

## Release verification (v1.8.0, 2026-11-13)

Live checks against the running backend through the same endpoints the UI uses (analyse → download/batch → poll → one-time `GET /api/files/…` delivery), each output checked with FFprobe (streams, duration), FFmpeg `silencedetect` (−50 dB, ≥ 2 s) and an AVFoundation decode (the framework QuickTime uses):

| Flow | Result |
|---|---|
| X, yt-dlp, smallest option (270p) | H.264 + AAC, 15.6 s; AVFoundation playable, audio decoded (RMS −8.2 dBFS); no silences; delivered once |
| X, FxTwitter fallback (a post X serves no video for), 270p | Provider `fxtwitter`; H.264 + AAC; AVFoundation playable and decoded. The post was a 102-min film (79.5 MB); its short pauses are content, not dropouts |
| TikTok Videos, 576p | H.264 + AAC from the video's own rendition (no separate music track offered or attached); decoded, −16.7 dBFS; no silences |
| Short Drama share link, Best (720p) | HEVC `hvc1` + AAC, 116 s; decoded, −19.1 dBFS; no silences |
| Short Drama direct `/shortdrama/episode/<series>/2` | Same item as the share link |
| Series | 52 episodes, in order, all accessible with the linked account |
| Batch ZIP E03–E04 | ZIP integrity OK; two correctly named MP4s in order (118.3 s, 178.6 s); each HEVC + AAC, decoded, no silences |
| Batch merge E05–E06 | `stream_copy` (no re-encode), 288.1 s vs 287 s listed (whole-second listing); HEVC + AAC; decoded; no silences ≥ 2 s; audio level 3-s windows across the episode boundary −17.6 … −21.0 dB |
| Cleanup | Temporary storage returned to its prior level after every delivery; an undelivered file was removed at its 30-minute expiry |

**Not performed in this release cycle:** a human listening check in QuickTime (last done by the owner in v1.4/v1.5); Save via the browser's download prompt (the same delivery endpoint was exercised directly; browser Save from the drawer was last checked in v1.7).

## Release verification (v1.9 work, 2026-11-13, `feature/v1.9-download-workflows`)

Automated: backend 571 passed; frontend 84 passed; TypeScript clean; production build OK; `npm audit` 0. Ruff: the new findings are four FastAPI `Depends` defaults on the new routes (B008, the project's pattern) and `noqa: BLE001` markers matching existing code.

Live, against the running app with public samples (yt-dlp's own test posts and earlier samples; small files only). Audio was checked with FFprobe, FFmpeg `silencedetect` and an AVFoundation decode. **No human listening test was done.**

| Check | Result |
|---|---|
| X bulk analysis of 6 lines (2 valid, a twitter.com duplicate, a TikTok link, an X post without video, text) | Counts shown before analysing; duplicate and wrong-platform flagged ("Open in TikTok Videos"); the post without video failed alone (`no_video`); 2 ready and selected |
| X bulk ZIP, 480p preference (videos offer 720/360) | Note "480p isn't available; used 360p"; ZIP passes `testzip`, entries `01 -`, `02 -` in input order; both H.264 + AAC, AVFoundation decodes audio (RMS -8.2 and -29.8 dBFS), no silences ≥ 2 s; batch `completed` at 100% after delivery |
| TikTok bulk, separate files (2 videos + 1 region-restricted link) | Restricted link failed at analysis only; both MP4s delivered, H.264 + AAC, AVFoundation RMS -16.7 and -15.7 dBFS; batch `completed`; temp storage 0 |
| Cancel one running video (3 X videos, 1 at a time) | Item cancelled while downloading, the other two finished; decision before packaging; Continue gave `… (partial, 2 of 3).zip` with a manifest naming the cancelled video and no links; both MP4s decode with audio |
| Cancel the whole queue during the first download | All items `cancelled`, no job folders left, temp storage 0 |
| Single download: double start, then Cancel | Second start `409 already_downloading` with the running job ID; cancel returns `cancelled` at once, still `cancelled` 3 s later, no file |
| Short Drama regression (linked account, old `/api/shortdrama/batches` paths) | ZIP E03-E04: valid, HEVC (`hvc1`) + AAC, both decode. Merge E05-E06: stream copy, 288.1 s vs 287 s listed, audio decodes, no silences |
| UI | New Download resets X with focus in the URL field while the download continues (Save in Downloads); X bulk ZIP, a TikTok download and an X single download all shown and saveable in Downloads from the TikTok tab. The page-script audit (overflow, clipping, contrast with transitions off, fonts, target sizes) at 1600, 1280, 768 and 375 px in dark and light for X Single, X Bulk (progress), TikTok Single (result), TikTok Bulk (review), Short Drama and the drawer: no failures after enlarging the review checkboxes' hit area to 44 px |

Observations: a script that closes the connection as soon as it has read every byte can leave a file "ready to save" (the transfer isn't confirmed complete); it stays saveable until it expires. Browsers and curl confirm normally. This predates v1.9. One run of the TikTok live script stalled in the test client; the batch itself had finished and stayed deliverable, and a rerun passed.

## What the tests do not prove

- That X/TikTok still serve content the way the fakes model it (only live checks show that).
- Subjective playback quality, or correct audio in a specific player other than via the manual checks above.
- Behaviour under real slow/flaky networks, very large files (multi-GB) or long series (50+ episodes): exercised only with small samples.
- Browser-specific saving (folder picker, multiple-download prompts): manual.
- Screen-reader output (VoiceOver/NVDA): the ARIA structure is tested, but announcements were not checked with a real screen reader.
- Concurrency at scale (two simultaneous batches with many episodes).
