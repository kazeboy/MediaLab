# Design decisions

Architecture Decision Records for MediaLab. Each record says where the decision came from:

- **Requirement:** specified in the project's release briefs (v1 … v1.6).
- **Evidence:** chosen after a documented investigation or measurement during development.
- **Implementation choice:** made while building; the rationale given is a **present-day architectural assessment**, not a recorded historical discussion.

---

## D1. React + TypeScript (Vite, Tailwind) frontend and FastAPI backend
*Origin: Requirement (v1 brief specified the stack).*

- **Problem:** a local GUI for analysing links, choosing formats and following progress.
- **Approach:** a React SPA talking JSON to a FastAPI backend on loopback.
- **Alternatives:** a desktop shell (Electron/Tauri); server-rendered pages (Jinja/HTMX); a CLI.
- **Reasoning (assessment):** the browser already provides the download/save UI MediaLab relies on (D8); FastAPI gives typed validation (Pydantic) and OpenAPI for free; the extraction ecosystem is Python.
- **Advantages:** no packaging/signing of a native app; strict request schemas; easy to test with `TestClient`.
- **Disadvantages:** two toolchains (Python + Node); two dev servers; the API is reachable by other local processes.
- **Risks:** browser-specific behaviour (folder saving is Chromium-only; multiple-download prompts).
- **Reconsider if:** MediaLab must run without a terminal (then a Tauri/Electron wrapper around the same API).

## D2. Python with yt-dlp for extraction
*Origin: Requirement (v1 brief).*

- **Problem:** X and TikTok change their delivery frequently.
- **Approach:** yt-dlp with only the platform's extractor (`allowed_extractors`), `process=False` first, then MediaLab's own sanitising.
- **Alternatives:** own scrapers; official APIs (the official X API was among the options investigated in v1.1 and was not adopted).
- **Reasoning:** yt-dlp is maintained by a large community and fixes breakage quickly (`make update-ytdlp`).
- **Disadvantages:** MediaLab inherits yt-dlp's assumptions (e.g. it labels TikTok streams "AAC" by default; see D11) and, for Short Drama, depends on two private yt-dlp methods.
- **Reconsider if:** yt-dlp drops TikTok/X support or the private methods change repeatedly.

## D3. Provider interface, router and chain
*Origin: Implementation choice (v1), extended for each platform.*

- **Problem:** several extraction strategies per platform, and the downloader must use the same strategy as the analysis.
- **Approach:** `VideoProvider` (`extract`, `download`, `provider_for`); `PlatformRouter` per platform; `ProviderChain` for primary + fallback; `PlatformSpec` to parameterise yt-dlp.
- **Alternatives:** if/else per platform in the routes; one class per platform without a shared interface.
- **Assessment:** keeps the API, job manager, media pipeline and UI platform-agnostic; adding a platform touches validation, one provider and the wiring (see [PROVIDERS.md](PROVIDERS.md#adding-a-provider)).
- **Disadvantages:** the Short Drama provider subclasses the yt-dlp provider and overrides protected hooks, which couples them.
- **Reconsider if:** a provider needs a fundamentally different download model (e.g. DASH with DRM, which is out of scope).

## D4. Optional FxTwitter fallback
*Origin: Requirement + Evidence (v1.1 investigation; removed, then restored at the user's direction in v1.1).*

- **Problem:** X returns empty "tombstones" to logged-out clients for some posts, including ones X classifies as sensitive.
- **Approach:** opt-in, X only, only after yt-dlp reports `no_video`/`not_found`; only the numeric post ID is sent; media still comes from X's CDN with per-hop validation. `possibly_sensitive` is informational, not an access control; FxTwitter's private/deleted/suspended/blocked tombstones are honoured.
- **Alternatives:** no fallback; signing in to X (rejected: no cookies/credentials for X).
- **Disadvantages:** sends post IDs to a third party; relies on an undocumented service.
- **Reconsider if:** FxTwitter changes terms/behaviour, or X serves these posts to logged-out clients again.

## D5. TikTok Short Drama via the user's own, explicitly linked cookies
*Origin: Requirement (v1.3 brief allowed reconsidering anonymity; constraints: no password entry, no silent cookie import) + Evidence (signed-in playback observed in the browser).*

- **Problem:** TikTok streams Short Drama episodes only to signed-in viewers.
- **Approach:** the user exports a `cookies.txt` and uploads it in Settings; MediaLab keeps only tiktok.com cookies (`0600`), loads them in memory for the Short Drama provider only, uses ordinary item pages and two unsigned web endpoints for series/episode mapping.
- **Alternatives considered:** anonymous extraction (proved impossible: locked previews without streams); reading the browser's cookie store automatically (rejected: "no silent import"); OAuth/official API (no TikTok API exposes Short Drama playback); generating TikTok request signatures (rejected: circumvention).
- **Disadvantages:** a bearer credential on disk; manual export/re-export when the session expires; removing it doesn't revoke the session.
- **Reconsider if:** TikTok offers an official authorised interface, or starts requiring signatures for the endpoints used.

## D6. Local-first, single user, loopback only
*Origin: Requirement (v1).*

- **Approach:** bind `127.0.0.1`; `TrustedHostMiddleware`; same-origin guard; no accounts; no database.
- **Advantages:** no hosting, no user data leaves the machine except the requests a download needs.
- **Disadvantages:** no API authentication (other local processes can call it); not shareable across devices.
- **Reconsider if:** multi-user or remote use is required. That would need authentication and a security redesign, not a config flag.

## D7. No permanent media storage
*Origin: Requirement (v1.2 replaced the v1 download folder).*

- **Approach:** files live only in a temp folder until the browser has received them (or retention expires); startup wipes leftovers.
- **Advantages:** no surprise disk use; no library to manage; nothing to leak later.
- **Disadvantages:** an unsaved file is lost after 30 minutes or a restart; batches can't resume after a restart (D15).

## D8. Browser-based delivery
*Origin: Requirement (v1.2 "Save Video"; v1.4 folder saving investigated).*

- **Approach:** `GET /api/files/{id}` streams an attachment once; the UI triggers a same-origin `<a download>` or, in Chromium, writes into a user-chosen folder via the File System Access API (never overwriting).
- **Alternatives:** backend writes to a user folder (v1; dropped by requirement); zip-on-the-fly streaming (would halve disk use for ZIPs but complicates retries and verification).
- **Disadvantages:** "Separate files" batches need the page open; Safari/Firefox can't target a folder; browsers may prompt for multiple downloads.

## D9. FFmpeg and FFprobe for processing and verification
*Origin: Requirement (v1).*

- **Approach:** FFmpeg remuxes/converts; FFprobe and decode passes verify. Always argument lists, never a shell.
- **Disadvantages:** an external binary whose build options matter (e.g. `libx264` for merge normalisation, now checked).
- **Reconsider if:** distribution requires a bundled binary (licensing: LGPL/GPL depending on build).

## D10. MP4-only output
*Origin: Requirement (v1).*

- **Approach:** only formats whose video can be stored in MP4 without re-encoding are offered; others are listed as unavailable.
- **Disadvantages:** sources only available as VP9/WebM wouldn't be offered (not encountered on X/TikTok so far).

## D11. AAC audio conversion when needed
*Origin: Evidence (v1.4 bug report; AVFoundation investigation).*

- **Problem:** HEVC + MP3 in MP4 played silently in QuickTime/Safari: AVFoundation ignores MP3 tracks in MP4, although FFprobe and FFmpeg see them.
- **Approach:** copy AAC/ALAC/AC-3/E-AC-3; convert MP3/Opus/Vorbis/FLAC/PCM to AAC 192k; validate the output (presence, codec, sync, non-silence). Never re-encode video.
- **Alternatives:** H.264+AAC renditions only (loses the higher HEVC qualities); MP3 in MOV (Apple-friendly, but not MP4 as required).
- **Disadvantages:** one lossy audio generation.
- **Related evidence-driven rules (v1.5/v1.6):** TikTok metadata can claim audio that isn't there (soundtrack fallback + `expect_audio`); TikTok's separate music track is only trusted for Short Drama when marked "original" (measured), never for ordinary TikTok videos.

## D12. Stream-copy merging
*Origin: Requirement (v1.5) + Evidence (identical codec configuration across episodes at one rendition).*

- **Approach:** plan one common rendition for all selected episodes; concat demuxer with `-c copy` only when every stream parameter (incl. extradata) matches.
- **Advantages:** lossless and near-instant; QuickTime gets one consistent sample description.
- **Disadvantages:** the common rendition may be lower than some episodes' best (e.g. 720p because one episode lacks 1080p).

## D13. Transcoding only when necessary
*Origin: Requirement (v1.5).*

- **Approach:** H.264 (libx264 CRF 20, `fast`) + AAC 192k at the smallest input size (no upscaling), highest input frame rate, per-episode audio pad/trim; verified per episode segment.
- **Alternatives:** upscale to the largest input (rejected: "do not upscale"); hardware encoding via VideoToolbox (faster, but quality control by bitrate rather than CRF; possible future option).
- **Disadvantages:** CPU-heavy for long series; generation loss.

## D14. ZIP packaging
*Origin: Requirement (v1.5).*

- **Approach:** stored (uncompressed) entries, streamed, ZIP64, CRC-verified, manifest for partial results; sources deleted only after verification.
- **Disadvantages:** needs about twice the episodes' size on disk while the archive is built.
- **Reconsider if:** disk use matters more than retry-ability (stream the ZIP directly to the browser instead).

## D15. In-memory job and batch state
*Origin: Implementation choice (v1, "no database"); trade-off reviewed in v1.6.*

- **Approach:** jobs, analyses and batches live in memory; temp files are wiped at startup.
- **Assessment (v1.6):** persisting job/batch *metadata* alone wouldn't let anything resume, because the media files it refers to are deleted at startup by design (D7), and TikTok's signed media URLs expire anyway. A useful resume would need: (a) a small JSON journal per batch (series, episode list, options, per-episode state) in the config folder, (b) keeping `job-batch-*` folders across restarts with an age limit, and (c) re-validating each collected file with FFprobe on startup. That is a moderate change to cleanup and lifecycle rules.
- **Recommendation:** keep in-memory state for now (a local tool, restarts are rare, the UI now reports a lost batch clearly). If long whole-series exports become common, implement the journal + kept batch folders as above, still without a database.

## D16. Batch queue design
*Origin: Requirement (v1.4: sequential by default, bounded concurrency) + implementation choices.*

- **Approach:** one daemon thread per batch ticking every 0.5 s; episodes reuse the normal `JobManager` pipeline; concurrency 1–2; at most 2 active batches; duplicate batches refused; failure policy "stop and ask" by default.
- **Alternatives:** a task queue library or message broker (rejected: unnecessary infrastructure for a local app); asyncio tasks (the work is thread-bound: yt-dlp, FFmpeg).
- **Disadvantages:** polling-based; thread per batch (bounded to 2).

## D17. Configuration persistence
*Origin: Requirement (v1.2 GUI settings).*

- **Approach:** infrastructure settings from environment/`.env` (immutable at runtime); three GUI preferences in `settings.json` (atomic, `0600`), seeded from the environment on first run. Paths, hosts, timeouts and allowlists can't be changed through the API.
- **Disadvantages:** two places to look; documented precedence rule (`settings.json` wins once saved).

## D18. One client-side activity registry for all jobs and batches
*Origin: Requirement (v1.7: downloads drawer, Save/Retry/Cancel from any tab) + implementation choice.*

- **Approach:** `ActivityProvider` (`lib/activity.tsx`) holds every job and batch the page started, polls the backend in **one** 800 ms loop only while something needs it, and exposes the actions (save, retry, cancel, batch control). Views and the Downloads drawer only render from it; a view unmounting or being hidden never stops tracking or auto-saving. Entries the backend no longer knows (after a restart) are marked `lost` once and stop polling.
- **Alternatives:** per-component polling as in v1.6 (rejected: work and Save buttons disappeared with their view; N loops); a state library such as Redux/Zustand (rejected: one context is enough); Server-Sent Events (not needed for a local app; could replace polling later without changing the views).
- **Disadvantages:** state lives for the page's lifetime only; a reload forgets the list (the backend still finishes running work, and files expire after the retention period).

## D19. Episode / Series split and a sticky batch action bar
*Origin: Evidence (v1.6 UI/UX review, finding U1) → v1.7 redesign.*

- **Approach:** the Short Drama tab has two views behind a segmented control. Series has the episode list as the page's content and a sticky bar holding the selection summary, the output choice, an Options popover and the primary action. Selection helpers are pure functions (`lib/selection.ts`) with unit tests. The selection is locked while the series' batch runs, so what's on screen matches what's downloading.
- **Alternatives:** keep one long page (rejected: series workflow below the fold); a separate route/page (no router in the app; tabs already provide the structure).
- **Disadvantages:** one more navigation level; mitigated by "Open series" and by preselecting the analysed episode.

## D20. Semantic design tokens and a small in-house UI kit
*Origin: Implementation choice (v1.7).*

- **Approach:** colours are CSS variables switched by `prefers-color-scheme` and exposed to Tailwind v4 via `@theme inline` (`bg-surface`, `text-muted`, `border-line`; the v1.7 `brand-*` = indigo accent was replaced by the amber `accent` tokens in v1.8, see D22); a dozen components in `components/ui` implement buttons, tabs, dialogs, popovers and disclosures with their ARIA patterns. The global focus style lives in `@layer base` so utilities can override it. See [FRONTEND_DESIGN_SYSTEM.md](FRONTEND_DESIGN_SYSTEM.md).
- **Alternatives:** a component library (Radix, Headless UI, MUI): rejected to keep dependencies minimal for a small local app; the needed patterns are few and covered by tests.
- **Disadvantages:** accessibility behaviour is ours to maintain (covered by `ui.test.tsx` and the visual audit); no manual light/dark switch in v1.7 (it followed the OS; replaced in v1.8 by D23).

## D21. Cancelling single downloads
*Origin: Requirement (v1.7 downloads drawer). **Superseded in v1.9 by [D27](#d27-immediate-final-cancellation)**; kept as a record.*

- **Approach:** `POST /api/jobs/{id}/cancel` sets an abort reason that the job checks at its next progress update (the same mechanism as timeouts and batch cancellation); idempotent; FFmpeg post-processing isn't interrupted. The job then fails with `download_cancelled` and its temporary folder is removed.
- **Disadvantages:** not instantaneous; a job in the final FFmpeg step completes first.

## D22. Black, charcoal and amber visual identity with a custom emblem
*Origin: Requirement (v1.8 brief: palette, logo direction, dark mode as flagship) + implementation choices noted below.*

- **Approach:** the indigo accent was replaced by MediaLab amber (`#FFB300`) on near-black/charcoal (dark) and, after D23, neutral white/cool-grey (light) surfaces, through the existing semantic tokens; components changed class names only, not structure or behaviour. New tokens separate amber as a *fill* (`--accent`), as *text* (`--accent-text`, darkened to `#8A5100` in light mode), the text *on* amber (`--on-accent`, near-black) and selection tints (`--accent-soft`, `--accent-line`).
- **Contrast-driven choices (implementation):** white on amber measures 1.79:1, so amber fills always carry dark text (9.7–10.8:1); amber text and focus rings are darkened in light mode (`#8A5100`, `#B45309`); dark mode uses amber directly (8.7–10.8:1).
- **Semantics kept:** success stays emerald, errors red; warnings moved from amber to orange so they don't read as "primary". The Save buttons became amber primary actions (per the brief) while the finished-file card stays green.
- **Logo:** an original emblem: an amber film frame with sprocket holes and a waveform over an offset orange frame (layered media, forward motion), drawn as plain SVG rectangles so it stays crisp from 16 px up; a simplified small variant for ≤ 32 px. The wordmark uses the system font (no web-font dependency), with "Lab" in amber.
- **Alternatives:** a gradient or glow treatment (rejected by the brief: refined, not flashy); amber text in light mode (fails contrast); a web font for the wordmark (an external dependency for one word).
- **Disadvantages:** the SVG wordmark files render with the viewer's system font, so they look slightly different per platform; converting the text to outlines would fix that if a fixed brand font is chosen later.

## D23. Dark by default, with a remembered header toggle
*Origin: Requirement (v1.8 theme update: dark default regardless of OS appearance, header toggle, localStorage persistence, no flicker, neutral light theme).*

- **Approach:** the dark tokens are the base (`:root`) and light is opt-in via `<html data-theme="light">`; the OS `prefers-color-scheme` is no longer consulted. The choice is stored in `localStorage` (`medialab.theme`) only when the user toggles, so "no explicit preference" stays distinguishable and means dark. An inline script in `index.html` applies the saved theme before the stylesheet and React, plus a two-rule inline style for the first paint. The light theme moved from warm off-white/beige to neutral white and cool grey.
- **Alternatives:** keep following the OS with an override (rejected: the brief makes dark the product default); store the choice in the backend `settings.json` (rejected: a per-browser display preference, and the backend would need a request before first paint, which would flash); a three-way Dark/Light/System switch (not requested; the two-state toggle is one click).
- **Disadvantages:** the preference is per browser profile and origin (`127.0.0.1` and `localhost` keep separate choices); the key, default and colours exist in two places (inline script and `lib/theme.ts`), guarded by a test.

## D24. Manrope and DM Sans, self-hosted
*Origin: Requirement (v1.8.1 visual polish: Manrope for headings, DM Sans for body and controls, no font CDN, wordmark unchanged).*

- **Approach:** the WOFF2 files for exactly the weights in use (Manrope 600/700, DM Sans 400/500/600; Latin and Latin Extended subsets) are committed under `frontend/public/fonts/` with their OFL licences, declared in `index.css` with `font-display: swap`, and the Latin files are preloaded. Fonts are assigned through tokens (`--font-sans`, `--font-heading`, `--font-wordmark`) and one base rule for `h1`–`h3`/`legend`, so components don't name typefaces.
- **Alternatives:** Google Fonts CDN (rejected: a local tool shouldn't depend on, or report page loads to, a third party); Fontsource as an npm dependency (rejected: it ships every weight, subset and a WOFF fallback, and the build would copy whatever the CSS references); variable fonts (two files, but larger per file and more than the needed weight range).
- **Disadvantages:** updating the fonts means copying files by hand; scripts outside Latin use the system font; the wordmark deliberately stays on the system font and so still differs slightly between platforms.

## D25. Favicon on a 16 px grid, with versioned links
*Origin: Evidence (v1.8.1: tabs showed the v1.6 purple icon although `/favicon.svg` already served the amber emblem).*

- **Approach:** a pixel-fitted favicon (`favicon.svg`, viewBox 16) plus `favicon.ico` (16 and 32 px), linked with `?v=2` so browsers fetch them fresh instead of reusing the icon cached for the unchanged URL.
- **Alternatives:** renaming the files (equivalent, but every reference changes); relying on users clearing their cache (unreliable: favicon caches survive normal reloads); serving long-lived `Cache-Control` headers from the backend (doesn't help an icon already cached).
- **Disadvantages:** the query must be bumped by hand when the artwork changes (a test pins the current value).

## D26. Link batches extend the batch manager instead of a second queue
*Origin: Requirement (v1.9: bulk X/TikTok downloads; reuse the existing job and batch infrastructure).*

- **Approach:** `Batch` gained a `source` (`shortdrama` or `urls`) and `platform`; a link item carries its `analysis_id`. Only "how to start an item" differs (`_episode_plan` vs `_url_plan`); the queue, concurrency, retry, failure decision, ZIP packaging, delivery and pruning are shared, and so is `BatchProgress` in the UI and the Downloads drawer. Every batch is served under `/api/batches`, with the old Short Drama paths as aliases.
- **Alternatives:** a separate `BulkManager` (rejected: duplicates the trickiest code, packaging and cancellation, and two activity models in the UI); running bulk items as plain jobs from the browser (rejected: no server-side limits, ordering or ZIP, and the queue would stop when the page closes).
- **Disadvantages:** `batches.py` keeps growing (it was already the largest module); a few behaviours branch on `source` (cancel policy, file names, manifest).

## D27. Immediate, final cancellation
*Origin: Requirement (v1.9 cancellation: really stop the work, including FFmpeg; no completed-after-cancel races).*

- **Approach:** a `cancelled` job state set under the job manager lock, a per-job cancel event, FFmpeg/FFprobe started with `Popen` and polled every 0.2 s inside a per-thread cancel scope (`MediaProcessor.cancellable`), and completion that re-checks the state under the same lock. Batch items and whole batches cancel through the same call.
- **Alternatives:** keep "cancel at the next progress update" (v1.6 to v1.8; FFmpeg steps couldn't be stopped, and the job ended as `failed`); killing the worker thread (impossible in Python, and unsafe for temporary files).
- **Disadvantages:** a stalled network read is only noticed at the next chunk or the socket timeout (20 s); an extraction (analysis) can't be interrupted, so its result is discarded instead.

## D28. Bulk analysis on the server
*Origin: Implementation choice (v1.9).*

- **Approach:** `POST /api/bulk-analyses` validates every line with the single-analysis rules, removes duplicates by post ID, enforces the link limit and analyses each link once in a two-worker pool; results go into the shared `AnalysisStore`, and the review list includes per-quality size estimates computed by the same `choose_option` the batch uses.
- **Alternatives:** the browser calling `/api/analyse` per line (simpler, but limits and deduplication would be client-side only, and a closed page would leave work half done); one synchronous request (too slow for 50 links within the analysis timeout).
- **Disadvantages:** another in-memory store that a restart loses; up to two bulk extractions run beside single analyses, which is more load on X/TikTok at once.

## D29. Cancelling a link batch keeps finished videos
*Origin: Requirement (v1.9: "preserve already completed outputs until their normal delivery or cleanup policy applies").*

- **Approach:** cancelling a link batch cancels what hasn't finished; finished separate files stay saveable until they expire, and a ZIP batch stops in `needs_decision` (`stopped`) so the user can build the ZIP from what finished or cancel again to discard it. Short Drama keeps its documented v1.4 behaviour (cancel deletes unsaved and collected files).
- **Alternatives:** one policy for both (rejected for now: changing Short Drama's tested, documented behaviour was out of scope); discard everything (loses finished work).
- **Disadvantages:** the two batch kinds react differently to Cancel; the UI labels the second step "Discard" to make that explicit.

## D30. Quality fallback for bulk downloads: lower first, then the closest higher
*Origin: Requirement (v1.9: explicit fallback, never upscale, keep audio).*

- **Approach:** `choose_option(..., above="closest")`: the exact resolution, else the highest one below it, else the lowest one above it; options with audio first. Every option is a resolution the source really offers, and the per-item note says what was used.
- **Alternatives:** Best Available when nothing lower exists (Short Drama's rule; for a 480p request on a 1080p-only video it jumps to the largest file); fail the item (strict mode; not offered for bulk to keep the options short).
- **Disadvantages:** "closest higher" can still be larger than the user expected; the review list shows the chosen resolution and size before starting.
