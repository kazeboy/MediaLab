# MediaLab v1.6: Code Review Report

> **Historical document.** Creator handles from the original live evidence have been replaced with neutral descriptions for publication. This is the v1.6 review as written on 2026-11-12; statuses reflect that date. The current review is [open-source/CODE_REVIEW_V1_9.md](open-source/CODE_REVIEW_V1_9.md).

Date: 2026-11-12. Scope: whole repository (backend, frontend, scripts, docs), security, reliability, UI/UX, release readiness. Method: source reading, static analysis (`ruff`, `vulture` in a throwaway environment), targeted reproductions, live checks against X/TikTok with the owner's linked TikTok account, and Apple AVFoundation decoding for audio.

Legend: **Verified** = reproduced or measured; **Fixed** = changed and covered by a test that passes; **Open** = not changed (recommendation).

## 1. Executive summary

MediaLab is a well-structured local application: a clear provider abstraction, strict URL canonicalisation and host allowlists, a structured error model, and an unusually thorough media-verification pipeline. The review found **no critical issues** (no credential exposure, no path traversal, no injection). It found and fixed:

- **2 high-severity issues:** a stalled FFmpeg could ignore cancellation and its timeout indefinitely (REL-1); ordinary TikTok videos could be given the wrong soundtrack from TikTok's separate music track (MED-1).
- **4 medium issues:** cross-site `GET`s were served (SEC-1); merge re-encoding assumed `libx264` without checking (REL-2); a batch's Save button could become unreachable (UI-1); quadratic audio checking for long merges (PERF-1).
- several low-severity reliability, hygiene, accessibility and maintainability issues.

Baseline before changes: **518** backend tests passing. After: **535** backend + **17** new frontend tests passing; live X, TikTok and Short Drama downloads verified with audible audio. The documentation set was rewritten into `docs/`. The repository is close to publishable; a licence choice and Git initialisation remain (see §10).

## 2. Architecture assessment

**Strengths**
- *Separation of concerns:* validation → provider → selection → jobs → media → delivery, with platform-specific logic confined to `providers/` and `validation.py`. The API, job manager and UI are platform-agnostic.
- *Security by construction:* URLs are rebuilt from parsed IDs; providers return only formats on allowlisted hosts; clients only ever send IDs; files are addressed by random IDs.
- *Honest metadata:* unknown values stay `None`; options say when audio is converted; errors only claim what was established.
- *Verification culture:* outputs are probed and decoded; merges are checked per episode segment.

**Weaknesses**
- *Size of a few modules:* `batches.py` (≈830 lines) mixes scheduling, planning and packaging orchestration; `ytdlp_provider.py` (≈570). Cohesive, but the next feature should split `batches.py` into scheduler / planner / packager.
- *Coupling to yt-dlp internals:* the Short Drama provider calls two private yt-dlp methods; acceptable and documented, but a recurring maintenance risk.
- *Subclass-by-override:* `TikTokShortDramaProvider` overrides protected hooks of `YtDlpProvider` (`_raw_info`, `_finish`, `_ydl`, `_keep_separate_audio`). Works and is tested; a composition-based "page source" strategy would be cleaner if a third yt-dlp-based provider appears.
- *Polling everywhere:* job (500 ms) and batch (1 s) polling plus a 0.5 s batch tick. Simple and robust for a local app; Server-Sent Events would reduce chatter but aren't needed.
- *In-memory state* (see D15 in DESIGN_DECISIONS.md).

**Not found:** circular imports (lazy imports are used deliberately in two places to avoid them: `schemas.batch_to_response`, `batches._package`); unused dependencies; duplicate implementations (one duplicated save helper, now fixed).

## 3. Findings

### 3.1 Security

| ID | Sev. | Status | Location | Finding |
|---|---|---|---|---|
| SEC-1 | Medium | **Fixed** | `main.same_origin_guard` | Cross-site `GET`s were served. A page in the user's browser couldn't read responses (no CORS), but could trigger side effects, e.g. `GET /api/shortdrama/series/{id}` makes MediaLab call TikTok with the linked session. *Evidence:* `GET /api/settings` and `/api/tiktok-account` with `Sec-Fetch-Site: cross-site` returned 200. *Fix:* refuse any `/api` request marked cross-site or with a foreign `Origin` (all methods). *Tests:* `test_api.py::test_cross_site_get_requests_are_refused` (8 cases), same-origin/headerless still work; UI verified live. *Regression risk:* low; non-browser clients unaffected. |
| SEC-2 | Low | **Fixed** | `config.prepare_directories`, `storage`, `jobs` | Temp/config folders and working subfolders were created `0755`. Private in practice only because macOS's per-user temp parent is `0700`; with `MEDIALAB_TEMP_DIR=/tmp/…` other users could list/read media. *Fix:* `ready/`, `job-*`, `job-batch-*` created `0700`; temp/config created `0700` when MediaLab creates them; shared existing folders untouched (logged). *Test:* `test_storage.py::test_working_folders_are_owner_only`. |
| SEC-3 | Info | Verified OK | `tiktok_account.py`, routes, logs | Cookie handling reviewed: values never in responses/logs/errors (tests assert), file `0600` (checked on disk), removal deletes the file, used only by the Short Drama provider (test asserts the TikTok Videos provider has no cookie params), never sent to FxTwitter. Documented that removal doesn't revoke the TikTok session. |
| SEC-4 | Info | Verified OK | validation, `net.py`, `resolve.py`, media-host checks, subprocess calls, delivery | SSRF, redirect validation, DNS rebinding (TrustedHost), subprocess argument lists, ID-only file access, ZIP name checks: no issues found. |

### 3.2 Media and audio

| ID | Sev. | Status | Location | Finding |
|---|---|---|---|---|
| MED-1 | High | **Fixed** | `ytdlp_provider._sanitise_entry`, `tiktok_shortdrama` | Ordinary TikTok videos: TikTok's separate `music` track was paired with video-only streams. *Evidence (live, 2026-11-12):* on a public creator's video (labelled "original sound") the track's loudness pattern correlated only 0.27 with the video's own audio; on @pokemonlife22's it matched (1.0). It can also be a licensed song. *Fix:* the TikTok Videos tab never offers the separate track (video-only renditions become "No audio track", never Best); Short Drama uses it only when TikTok marks it `original: true` (measured to match episodes' built-in audio (r = 0.969–0.977, episodes 1, 2, 5, 14). *Tests:* `test_tiktok.py::test_tiktok_videos_never_pair_the_separate_music_track`, `test_shortdrama.py::test_short_drama_uses_separate_track_only_when_marked_original[…]`. |
| MED-2 | High | Fixed in v1.5, **re-verified** | `selection`, `jobs`, `media` | Source metadata can claim audio that isn't there: yt-dlp labels TikTok HEVC streams "AAC" unless the URL is marked video-only, and TikTok varies URLs (all 52 episodes unmarked in one listing). v1.5 added the soundtrack fallback; v1.6 additionally sets `expect_audio` whenever the source explicitly promised audio, so such a file fails `audio_missing` instead of being saved silently. |
| MED-3 | Info | Verified | n/a | FFprobe vs. playback: FFprobe and FFmpeg accept MP3-in-MP4 that AVFoundation ignores (v1.3/v1.4 bug). Documented the AVFoundation and by-ear checks in TESTING.md; in-app validation remains FFmpeg-based and is described honestly as such. |

### 3.3 Reliability and performance

| ID | Sev. | Status | Location | Finding |
|---|---|---|---|---|
| REL-1 | High | **Fixed** | `packaging.run_ffmpeg` | Cancel and timeout were only checked when FFmpeg printed a progress line; a stalled FFmpeg (blocked input, hung filesystem) never returned. *Evidence:* with a FIFO input, cancel at 1 s and timeout 3 s, the call was still blocked after 8 s. *Fix:* watchdog thread kills FFmpeg on cancel/timeout every 0.2 s. *Tests:* `test_packaging.py::test_stalled_ffmpeg_is_stopped_by_cancel_and_timeout[cancel|timeout]` (return < 5 s). |
| REL-2 | Medium | **Fixed** | `packaging.merge_mp4` | The normalising merge used `libx264` unconditionally; `has_encoder()` existed but was never called. *Fix:* checked (cached per binary); a clear non-retryable `transcode_failed` suggesting ZIP. *Test:* `test_missing_libx264_gives_a_clear_error`. |
| PERF-1 | Medium | **Fixed** | `packaging._segment_peak` | Per-episode audio verification decoded the merged audio from the start for each episode (O(N²)). *Evidence:* 20 segments of a 10-min file: 3.4 s before, 0.8 s after (input seeking). *Tests:* existing per-segment tests pass on real media. |
| REL-3 | Low | **Fixed** | `BatchManager.create` | Duplicate-batch check and insertion weren't atomic (series lookup runs unlocked in between). *Fix:* re-check under the lock before inserting. |
| REL-4 | Low | **Fixed** | `routes.get_series` | Series lookups bypassed the analysis concurrency semaphore. *Fix:* same semaphore and shielded timeout as `/api/analyse`. |
| REL-5 | Info | Open (documented) | n/a | State is lost on restart (D15). Analysis and recommendation in DESIGN_DECISIONS.md: persisting metadata alone can't resume anything because media is wiped by design; a journal + kept batch folders would be needed. |

### 3.4 Frontend

| ID | Sev. | Status | Location | Finding |
|---|---|---|---|---|
| UI-1 | Medium | **Fixed** | `SeriesPanel` | Hiding the series list, or analysing another series, hid the active batch, including its final Save button (the file then expired unseen). *Fix:* batch progress always renders. Verified by type-check/build; manual UI check. |
| UI-2 | Medium | **Fixed** | `SeriesPanel` polling | After a backend restart the panel polled forever, showing `batch_not_found` every second. *Fix:* stop and mark the batch as no longer available. |
| UI-3 | Medium | **Fixed** | `index.css`, `SettingsPanel` | Contrast below WCAG AA: dark-mode small text 3.75:1, light-mode hints 2.56:1. *Fix:* 6.96:1 and 4.76:1. |
| UI-4 | Low | **Fixed** | `SeriesPanel` | Output-format radios had no accessible name ("on"). |
| UI-5…UI-12 | M/L | Open | various | Overloaded Short Drama tab, three save models, long settings dialog without focus trap, tabs without ARIA keyboard pattern, episode list scaling. See UI_UX_REVIEW.md. |

### 3.5 Maintainability

| ID | Sev. | Status | Finding / change |
|---|---|---|---|
| MNT-1 | Low | **Fixed** | Private helpers used across modules made public: `storage.free_bytes`, `selection.short_side`, `MediaProcessor.run/require`. |
| MNT-2 | Low | **Fixed** | Dead code removed: `StreamProgress.finished`, `StreamInfo.copy_key`, unused import in `jobs.py`. (`net._ValidatingRedirectHandler.max_redirections` flagged by vulture is used by `urllib`, so it was kept.) |
| MNT-3 | Medium | **Fixed** | `SeriesPanel.tsx` (696 lines) split: `lib/save.ts` (save helpers, shared with `Workspace`, which duplicated one), `components/BatchProgress.tsx`; `SeriesPanel` 466 lines. No behaviour change. |
| MNT-4 | Low | **Fixed** | Versions aligned at 1.6.0 (`pyproject.toml` description updated, FastAPI app, `package.json`). |
| MNT-5 | Medium | **Fixed** | No frontend tests → Vitest with 17 tests (platform detection, formatting, never-overwrite naming). No Python lock → `backend/requirements.lock` + `make setup-locked`; `make test` now runs both suites. |
| MNT-6 | Low | **Fixed** | Delivered ZIPs were stored as `<id>.mp4`; now `<id>.zip`. |
| MNT-7 | Low | Open | `batches.py` size (see §2). `ruff` style items (e.g. `str`+`Enum` → `StrEnum`, `datetime.UTC`) left as is (no functional value). |
| MNT-8 | Low | Open | `httpx` with Starlette's `TestClient` emits a deprecation warning (1 warning in the test run). |

## 4. Reliability under realistic workloads (assessment)

| Scenario | Behaviour |
|---|---|
| One short download | Seconds; temp ≈ 2× file briefly; deleted after save |
| One large download (multi-GB) | Streamed to disk and to the browser (1 MiB chunks; no full-file memory use); ≈2× disk during remux; 3 h download limit; FFmpeg steps bounded by `MEDIALAB_FFMPEG_TIMEOUT_SECONDS` (copy-remux is disk-speed) |
| 10 / 50 episodes | Series listing: 3 requests, cached; downloads sequential by default (2 max); "Separate files" keeps ≤ 2 unsaved episodes; ZIP/merge keep all collected episodes plus the output (≈ 2× total), checked before packaging |
| Merge planning for 50 episodes | One item-page load per episode before downloading starts (≈1 min); results reused for the downloads (no second analysis) |
| Compatible merge | Stream copy; ≈3 s incl. verification for 5½ min 1080p |
| Mixed-codec merge | libx264 CRF 20: ≈4 s per minute of 720p measured; a 100-min 1080p series ≈15–20 min (estimate); cancellable; 6 h cap |
| Insufficient disk | Refused before each download and before packaging (`insufficient_space`); episodes kept for retry |
| Slow network | Socket timeout 20 s; retries for transient errors; 3 h whole-download limit |
| Expired media URLs | 403 → fresh URLs (mirror), ≤ 3 attempts; changed TikTok encodes mapped to equivalents |
| Interrupted download / browser transfer | Retried with backoff / file returns to "ready" until expiry |
| Backend restart | Jobs/batches lost; temp wiped; UI now reports it cleanly (UI-2) |
| Concurrent requests | Analyses/series ≤ 4 (semaphore → `busy`); downloads ≤ 2 running + ≤ 10 queued; batches ≤ 2; duplicates refused |
| Event loop | No blocking work on the loop (extraction, FFmpeg, file I/O run in threads) |

## 5. Refactoring performed (v1.6)

Backend: `packaging.py` (watchdog `run_ffmpeg`, `has_encoder` check, seeked segment checks, dead code), `providers/ytdlp_provider.py` (`_keep_separate_audio`), `providers/tiktok_shortdrama.py` (original-sound flag), `jobs.py` (`expect_audio` rule, `cancel`-safe dirs, dead field), `media.py` (public `run`/`require`, message), `main.py` (same-origin guard for all methods, version), `config.py` (owner-only folders), `storage.py` (`0700`, `.zip` suffix, public `free_bytes`), `selection.py` (public `short_side`), `batches.py` (atomic duplicate check), `api/routes.py` (series semaphore). Frontend: `lib/save.ts`, `components/BatchProgress.tsx`, `SeriesPanel.tsx` (split, UI-1, UI-2, a11y), `Workspace.tsx` (shared helper), `index.css` (contrast), `App.tsx` (subtitle). Tooling: `requirements.lock`, Makefile targets, Vitest. Docs: new `docs/` set; root `ARCHITECTURE.md`/`SECURITY.md` replaced by `docs/` versions; README rewritten.

No public API contract was removed or renamed. Behavioural changes: cross-site `GET`s now return 403; TikTok Videos no longer lists the separate `audio` format; files that promised audio but have none now fail `audio_missing`.

## 6. Testing results (commands actually run)

| Command | Result |
|---|---|
| Baseline `cd backend && .venv/bin/python -m pytest` (before changes) | 518 passed |
| `cd frontend && npx tsc --noEmit -p . && npm run build` (before) | OK |
| `make test` (final) | backend **535 passed** (1 deprecation warning); frontend type-check OK; Vitest **17 passed** |
| `npm run build` (final) | OK |
| `ruff check backend/app --select F` (final) | All checks passed |
| Live: X post 320p | 867,259 bytes, H.264 + AAC, AVFoundation audio −19.8 dBFS |
| Live: a public TikTok video, 576p | 5,076,763 bytes, H.264 + AAC, −16.7 dBFS; no separate `audio` format listed |
| Live: Short Drama share link analysis | separate track kept (original sound); 720p option "converted from MP3" |
| Live: Short Drama ZIP, episodes 12–13 at 720p | ZIP 16,013,451 bytes; both MP4s HEVC (`hvc1`) + AAC, audible (−25.2, −24.0 dBFS) |
| Live: cross-site GET of the series endpoint | 403; UI's own requests 200 |
| Live: temporary storage after runs | 0 bytes |
| Live measurement: TikTok separate track vs. built-in audio | Short Drama ep. 1/2/5/14 r = 0.972/0.977/0.969/0.970; public video A r = 0.27; public video B r = 1.0 |

The by-ear QuickTime check was done by the owner in v1.4 (single 720p episode) and v1.5 (merged MP4); not repeated for v1.6 since media commands didn't change except the segment check.

## 7. Remaining technical debt (prioritised)

| Priority | Item | Impact | Effort |
|---|---|---|---|
| 1 | Initialise Git with a reviewed first commit (licence: MIT, done); CI on macOS | Release blocker (Git) | S |
| 2 | Split the Short Drama UI into Episode/Series views with a sticky action bar; Downloads drawer (UI_UX_REVIEW.md) | High UX | M–L |
| 3 | Settings dialog focus trap/scroll lock; ARIA tabs keyboard pattern | Accessibility | S |
| 4 | Split `batches.py` (scheduler, planner, packager) | Maintainability | M |
| 5 | Optional batch journal + kept batch folders for resume after restart (D15) | Reliability for long exports | M |
| 6 | Replace real TikTok IDs/handles in tests/docs with synthetic ones | Publication hygiene | S |
| 7 | Hardware (VideoToolbox) encoding option for long mixed merges | Performance | M |
| 8 | Component tests (React Testing Library) for Workspace/SeriesPanel | Test coverage | M |
| 9 | Move `TestClient` to the non-deprecated httpx transport | Hygiene | S |

## 8. UI/UX roadmap (summary)

Short term: focus trap and ARIA tabs; episode range selection; summary-first batch progress; planning visibility. Medium term: Episode/Series split for Short Drama, sticky selection/action bar, Downloads drawer across tabs, settings as sections. Implemented now: contrast fixes, accessible radio names, always-visible batch progress, clean handling of lost batches. Details: [UI_UX_REVIEW.md](UI_UX_REVIEW.md).

## 9. Verified vs. fixed vs. open (at a glance)

- **Fixed and tested:** SEC-1, SEC-2, MED-1, REL-1, REL-2, REL-3, REL-4, PERF-1, UI-1, UI-2, UI-3, UI-4, MNT-1…MNT-6.
- **Verified OK (no change needed):** SEC-3, SEC-4, MED-2 (fixed in v1.5, tightened in v1.6), MED-3.
- **Open / recommendations:** REL-5 (restart resume), UI-5…UI-12, MNT-7, MNT-8, items in §7.

## 10. GitHub readiness

Not yet published and not a Git repository. No secrets found; ignore rules, locks and docs are in place; licensed under **MIT** (owner's choice). Blocking: a reviewed first commit. Recommended: CI, CONTRIBUTING, CHANGELOG, synthetic test IDs. See [GITHUB_READINESS.md](GITHUB_READINESS.md).
