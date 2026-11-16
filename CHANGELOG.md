# Changelog

All notable changes to MediaLab. Versions are local releases (tags `v1.6.0`, `v1.7.0`, `v1.8.0`, `v1.8.1`, `v1.9.0`); earlier versions (v1.0–v1.5) predate the Git repository and are summarised in [docs/CODE_REVIEW_REPORT.md](docs/CODE_REVIEW_REPORT.md) and [docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md).

## [Unreleased]

## [1.9.0] (2026-11-14): Bulk downloads, cancellation and workflow improvements

Verified before tagging: 571 backend and 84 frontend tests, typecheck, production build and `npm audit` on the merged `main`, plus the live X, TikTok and Short Drama checks recorded in [docs/TESTING.md](docs/TESTING.md).

### Added
- **Bulk downloads for X and TikTok Videos:** a Single | Bulk switch on both tabs. Paste up to 50 links (one per line); MediaLab drops blank lines, trims spaces, flags duplicates (by post ID, so x.com and twitter.com links of one post match) and links for another tab, then analyses each distinct link once. Review the list (thumbnail, title, creator, duration, qualities, size), untick what you don't want, pick a quality preference (Best available, 1080p, 720p, 480p) and save as **one ZIP** (`01 - …mp4` in your order) or **separate MP4 files** (optionally into a chosen folder).
- **New Download** on the X, TikTok Videos and Short Drama Episode views: clears the link and result and focuses the URL field; a download that already started keeps running in Downloads.
- **Queue controls:** cancel one waiting or running video (the rest continue), cancel the whole batch, retry failed or cancelled items; two downloads in parallel by default (1 or 2, capped by the server).
- API: `POST /api/bulk-analyses` (+ `GET`, `…/cancel`), `POST /api/batches` for link batches, `/api/batches/{id}` for every batch with `/items/{n}/retry` and `/items/{n}/cancel` (the `/api/shortdrama/batches` paths stay as aliases). New error codes `already_downloading`, `item_not_found`, `bulk_not_found`. Setting `MEDIALAB_MAX_BULK_URLS` (default 50, at most 100).

### Changed
- **Cancelling is immediate and real:** jobs have a `cancelled` state (previously `failed` with `download_cancelled`). The transfer stops at its next progress update, a running FFmpeg/FFprobe is killed within 0.2 s (also during audio conversion and output checks), temporary files are removed, and a cancelled job can never turn into a finished one. Cancel sits next to the progress bar and also works while processing.
- **Duplicate protection on the server:** the same video in the same quality can't download twice at once (`already_downloading`; the UI follows the running job), and identical batches are refused (`batch_in_progress`).
- **Cancelling a link batch keeps finished videos:** separate files stay saveable; a ZIP batch waits so you can build the ZIP from what finished or discard it. Short Drama cancel behaviour is unchanged.
- Collected videos are deleted only after the ZIP or merged MP4 has been verified and handed over, so a stopped or failed packaging run can be retried.
- Downloads drawer: link batches next to single downloads and Short Drama, with a per-video list (Cancel, Retry), Retry for cancelled downloads and Cancel during processing.
- Tests: backend 539 → 571, frontend 67 → 84.
- Versions aligned to **1.9.0**.

## [1.8.1] (2026-11-13): Visual polish

### Fixed
- **Favicon:** browser tabs could still show the v1.6 purple play button, because browsers had cached it under the same `/favicon.svg` URL that v1.8 reused. The icon links now carry `?v=2`, the favicon is the amber emblem redrawn on a 16 px grid (sharp at 16 and 32 px), and a `favicon.ico` (16 + 32 px) answers browsers that ask for `/favicon.ico`.

### Changed
- **Typography:** Manrope (600, 700) for headings and titles, DM Sans (400, 500, 600) for body text and controls, monospace kept for codes. Self-hosted WOFF2 files in `frontend/public/fonts/` with their SIL Open Font License texts, preloaded, `font-display: swap`; no font CDN. The MediaLab wordmark keeps its system font.
- **Copy:** em dashes removed from all MediaLab-authored text (UI, docs, comments) and rewritten as separate sentences, colons, commas or parentheses. Empty format-table cells now read "unknown" or "none".
- Versions aligned to **1.8.1** (`backend/pyproject.toml`, `app.__version__`, `frontend/package.json`, `package-lock.json`).

### Added
- Tests for the favicon links and files, the font files, tokens and assignments, and the absence of em dashes in project copy. Frontend 56 → 67 tests, backend 538 → 539.

## [1.8.0] (2026-11-13): Custom branding, amber theme and theme toggle

### Added
- **MediaLab logo:** an original emblem (amber film frame with sprocket holes and an audio waveform, layered over an offset orange frame) and a "Media**Lab**" wordmark. SVG assets in `frontend/public/brand/` (emblem, small emblem for ≤ 32 px, horizontal logos for dark and light backgrounds, app icon), `favicon.svg`, a 180 px `apple-touch-icon.png` and a 512 px app icon PNG.
- **Theme toggle** in the header next to Settings (sun in dark mode, moon in light mode; accessible label and tooltip; keyboard operable). The choice is stored in `localStorage` (`medialab.theme`).
- Tests: theme default/switching/persistence (including the real pre-render script from `index.html`), header branding, version alignment, OpenAPI schema generation. Frontend 47 → 56 tests, backend 536 → 538.

### Changed
- **Black, charcoal and amber identity** replaces the indigo accent: amber `#FFB300` primary actions (Analyse, Download, Save Video, Save ZIP), active tabs, selection, progress and toggles; dark text on amber (≥ 9.7:1). Success stays green, errors red; warnings use orange instead of amber.
- **Dark mode is the default** for everyone, regardless of the macOS/browser appearance; light mode applies only when chosen. The saved theme is applied before the stylesheet and React load (no flash).
- **Light theme** uses neutral white and cool-grey surfaces (no cream/beige), with amber deepened where it is text (`#8A5100`) or a focus ring (`#B45309`).
- Sticky batch bar is solid (no blur); "needs attention" items in the Downloads drawer keep their Save button distinct in light mode.
- Versions aligned to **1.8.0** (`backend/pyproject.toml`, `app.__version__` used by the API, `frontend/package.json`, `package-lock.json`); previously 1.6.0 throughout v1.7.

### Fixed
- `GET /openapi.json` returned 500 (since v1.6), so the interactive API docs at `/docs` showed no endpoints: the streaming file route now declares its status code.

## [1.7.0] (2026-11-13): Frontend redesign and improved UX

### Added
- **Downloads drawer** (header button with a count badge): every job and batch from every tab, grouped into *Needs attention*, *In progress* and *Finished*, with Save, Retry, Cancel, Continue, Dismiss and Clear finished.
- `POST /api/jobs/{job_id}/cancel` (idempotent; stops a queued or downloading job at its next progress update; same-origin guarded).
- **Short Drama Episode | Series views**; "Open series" from an analysed episode with that episode preselected.
- Series selection: Shift-click ranges, "Select a range" (from/to, from episode N), select all accessible, clear; selection locked while the series' batch runs.
- **Sticky batch action bar** with selection summary, output choice (remembered), an Options popover (quality, strict, parallel, partial, folder) and the primary action.
- Sectioned **Settings** (General · Download limits · TikTok account) with a cookies.txt how-to behind a disclosure.
- Component tests with Testing Library (drawer, cross-tab Save/Retry/Cancel, series selection, view switching during a batch, dialogs and focus return): frontend 17 → 47 tests.
- `docs/FRONTEND_DESIGN_SYSTEM.md`.

### Changed
- One activity registry (`lib/activity.tsx`) polls all jobs and batches; views no longer own polling, so work and Save buttons survive tab and view changes.
- Shared UI kit (`components/ui`): buttons, cards, badges, alerts, disclosures, progress, WAI-ARIA tabs (roving tabIndex, arrows, Home/End, short labels on phones), modal dialogs (focus trap, Escape, focus return, scroll lock; full-height sheet on phones), drawer, popover.
- Summary-first batch progress (failures first, finished episodes collapsed; "Checking qualities" during merge planning); errors show message and action first, technical details collapsed.

### Fixed
- Contrast (subtle text and the success button) to WCAG AA in both themes; 20 px disclosure targets raised to 36 px; dialog containers no longer drew a focus ring on open; `.gitignore` no longer hid `components/downloads/`.

## [1.6.0] (2026-11-12): Architecture audit, security and documentation

Audited baseline (first commit of the Git repository; licence MIT).

### Security
- Same-origin guard for every `/api` method: cross-site requests, non-loopback `Origin` and `Origin: null` on state-changing requests are refused with 403 (previously cross-site `GET`s were served).
- Owner-only (`0700`) temporary and working folders.

### Fixed
- A stalled FFmpeg could ignore cancellation and timeouts (watchdog added).
- Ordinary TikTok videos could be paired with TikTok's separate music track instead of their own sound; only built-in audio is used for TikTok Videos.
- The normalising merge assumed `libx264` without checking; per-episode audio verification was quadratic for long merges.
- Duplicate-batch race; series lookups now share the analysis concurrency limit.
- A batch's Save button could become unreachable; polling stops cleanly when the backend no longer knows a batch; contrast and accessible names in the UI.
- Delivered ZIPs are stored with a `.zip` suffix.

### Added
- `backend/requirements.lock` and `make setup-locked`; Vitest frontend tests (17); the `docs/` set (architecture, design decisions, providers, media pipeline, API, security, development, testing, troubleshooting, UI/UX review, readiness, code review report). Backend 518 → 535 tests.
