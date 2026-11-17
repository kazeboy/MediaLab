<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="frontend/public/brand/medialab-logo-on-dark.svg">
    <img src="frontend/public/brand/medialab-logo-on-light.svg" alt="MediaLab" width="260">
  </picture>
</p>

# MediaLab

**Save videos from X, TikTok and TikTok Short Drama as MP4: local downloads in their original quality.**

Version **1.9.0** · [Changelog](CHANGELOG.md)

MediaLab runs entirely on your Mac (`127.0.0.1`). You paste a link, see what the platform actually offers (resolutions, codecs, sizes), pick a quality, and your browser saves the finished MP4. There are no accounts, no database and no hosting; MediaLab keeps no permanent copies of what you download.

> Only download content you have the right to save. Respect creators' copyright and the platforms' terms of service.

## Supported platforms

| Tab | What | Sign-in |
|---|---|---|
| **X** | Videos in public X posts (optional FxTwitter fallback for posts X hides from logged-out visitors) | None |
| **TikTok Videos** | Individual public TikTok videos | None |
| **TikTok Short Drama** | Episodes and whole series of TikTok Short Dramas you can watch | Your own TikTok account (cookies you export and link once) |

## Features

- **Analyse before downloading:** author, text, thumbnail, duration and every format the source reports.
- **Real resolutions only**, Best Available first; nothing is upscaled.
- **MP4 that plays everywhere:** video is never re-encoded; audio that Apple players can't play from MP4 (e.g. MP3) is converted to AAC, and the option says so.
- **Verified output:** every file is checked for video, audio presence, sync and non-silent sound.
- **Bulk downloads (X and TikTok):** paste up to 50 links, review and select the videos, and save them as **one ZIP** or separate MP4s, two downloads at a time.
- **Short Drama series:** list all episodes, select any or all accessible ones, and download them as **one ZIP**, **one merged MP4**, or separate files.
- **Cancel that really stops:** cancel a download, one video of a batch, or a whole batch; the transfer and FFmpeg stop and temporary files are removed.
- **Progress and clear errors:** real bytes, speed and ETA; every error has a code, an explanation and a suggested action.
- **One Downloads list:** every download and batch, from any tab, with Save, Retry and Cancel in one drawer.
- **Accessible, responsive UI:** a cinematic black-and-amber dark theme by default and a clean light theme one click away (the sun/moon button in the header; your choice is remembered), phone to desktop, full keyboard support, WCAG AA contrast measured in both themes.
- **Nothing left behind:** temporary files are deleted after your browser has saved the file (or after 30 minutes).

## How it works (in one paragraph)

A React UI talks to a local FastAPI backend. The backend validates and canonicalises the link, extracts metadata with **yt-dlp** (or, for Short Drama, TikTok's own item pages with your linked session), builds resolution options, downloads the selected streams into a temporary folder, assembles and verifies the MP4 with **FFmpeg/FFprobe**, and streams it once to your browser. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requirements

- macOS (Apple silicon or Intel). The backend has run on Linux, but Linux isn't tested regularly; Windows isn't supported yet (see [docs/open-source/CODE_REVIEW_V1_9.md](docs/open-source/CODE_REVIEW_V1_9.md#cr-04-medium-the-backend-doesnt-run-on-windows-as-written))
- Python ≥ 3.11, Node.js 20.19+ or 22.12+, and FFmpeg with FFprobe: `brew install python node ffmpeg`
- A Chromium browser (Chrome, Edge, Arc, Brave) for saving batches into a chosen folder; Safari/Firefox work with normal downloads

## Install

```bash
git clone https://github.com/kazeboy/MediaLab.git
cd MediaLab
make setup            # or: make setup-locked  (exact tested versions)
cp .env.example .env  # optional; every value has a default
```

## Start and stop

```bash
make dev     # open http://127.0.0.1:5173 (stop with Ctrl+C)
make start   # alternative: one process, UI served from http://127.0.0.1:8000
```

## First-time setup

1. Open the app, click the **gear** for Settings: maximum file size (default 8 GB), maximum batch output size (default 32 GB), optional FxTwitter fallback (off).
2. For **Short Drama** only: sign in to tiktok.com in your normal browser, export that site's cookies as a Netscape `cookies.txt` (e.g. with a cookies.txt extension, "current site" only), then Settings → **TikTok account → Choose cookies.txt…**. Delete the exported file afterwards. MediaLab never asks for your password, keeps only tiktok.com cookies (owner-only file), and uses them only in the Short Drama tab. **Remove** deletes MediaLab's copy but doesn't sign you out at TikTok. Details: [docs/SECURITY.md](docs/SECURITY.md#tiktok-account).

## Supported links

| Tab | Examples |
|---|---|
| X | `https://x.com/<user>/status/<id>`, `twitter.com/…`, `…/status/<id>/video/2` |
| TikTok Videos | `https://www.tiktok.com/@<user>/video/<id>`, `https://vm.tiktok.com/<code>/`, `https://www.tiktok.com/t/<code>/` |
| TikTok Short Drama | share links `https://vm.tiktok.com/<code>/`, `https://www.tiktok.com/shortdrama/episode/<series>/<n>`, `https://www.tiktok.com/@<publisher>/video/<id>` |

Paste a link into the wrong tab and MediaLab offers to switch.

## Using it

**One video:** paste → **Analyse** → choose a resolution (Best Available is preselected) → **Download MP4** → **Save Video**. **Cancel** is next to the progress bar. **New Download** (next to Analyse) clears the result for the next link; a download that already started keeps going in **Downloads**.

**Several X or TikTok videos:** switch the tab to **Bulk** → paste links, one per line (MediaLab shows how many are usable, duplicates or for another tab) → **Analyse N videos** → untick any you don't want → choose the quality and **ZIP archive** or **Separate MP4 files** → **Download N videos**. Cancel single videos or the whole batch from the progress list or from Downloads. A quality a video doesn't offer falls back to the next lower one (or, if there is none, the closest higher one); nothing is upscaled.

**A Short Drama series:** analyse any episode → **Open series** (or switch to the **Series** view) → select episodes (click, Shift-click for a range, **Select a range**, or **Select all accessible**) → choose the output in the bar at the bottom:

| Output | You get |
|---|---|
| **ZIP archive** (default) | `Series - E01-E10.zip` with one MP4 per episode, in order |
| **Merged MP4** | `Series - E01-E10.mp4`, the episodes joined in order, without re-encoding when they share one format (MediaLab plans for that), otherwise converted to H.264 + AAC |
| **Separate files** | each episode saved as it finishes (into a chosen folder in Chromium browsers) |

Then **Download N** or **All accessible**, and **Save ZIP / Save Video** when it's ready. If an episode fails, MediaLab stops before packaging so you can retry it or continue without it; omitted episodes are always listed (and a partial result is never called "Complete Series"). Details: [docs/MEDIA_PIPELINE.md](docs/MEDIA_PIPELINE.md).

**Downloads** (header button): everything you started on any tab, with what needs your attention first. Save, Retry, Cancel or Continue from there, without going back to the tab. **Settings** (gear): temporary storage, download limits, FxTwitter, and your TikTok account.

## Testing

```bash
make test    # backend (pytest, 571 tests) + frontend type-check and unit/component tests (84)
```
No test needs the internet or a TikTok account. Live and audio checks: [docs/TESTING.md](docs/TESTING.md).

## Troubleshooting

Errors show a code; look it up in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). Most common: port already in use (stop the earlier run), `login_required`/`auth_expired` (link or re-link your TikTok cookies), `extraction_failed` (`make update-ytdlp`).

## Known limitations

- **Short Drama** needs your linked account; only episodes your account can play work, and TikTok doesn't say why an episode is locked. Direct episode links and series views depend on TikTok's web endpoints answering unsigned requests (share links don't). The provider uses private yt-dlp functions, so a yt-dlp update can require a code change.
- **TikTok Videos:** resolutions TikTok offers only without audio are shown as "No audio track"; MediaLab won't attach TikTok's separate music track to ordinary videos because it may be a song rather than the video's own sound.
- **Earlier versions:** Short Drama files from v1.3/v1.4 may play silently in QuickTime (MP3 in MP4, or HEVC without audio). Download them again.
- **State is in memory:** a backend restart loses running downloads, batches and bulk analyses (their temporary files are deleted); they can't be resumed and show as no longer available.
- **Bulk mode:** at most 50 links per batch (`MEDIALAB_MAX_BULK_URLS`, up to 100); one quality preference for the whole batch (no per-video choice); a post with several videos contributes the first one (or the one its `/video/N` link names); an analysis that is already talking to X or TikTok can't be interrupted, so its result is discarded when it returns; separate files need this page open, as for Short Drama.
- **Merging different formats re-encodes** (CPU-heavy, lossy); ZIP and same-format merges don't.
- **Public content only** for X and TikTok Videos; region-blocked, private and deleted content fails with a clear error.
- **The theme choice is per browser:** it lives in that browser's storage for the address you use, so `127.0.0.1` and `localhost` remember separate choices.
- **The FxTwitter fallback** (off by default) sends the X post ID to a third-party service when X itself returns no video.

## Documentation

| Document | Contents |
|---|---|
| [CHANGELOG.md](CHANGELOG.md) | What changed in each version since v1.6 |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, lifecycles, diagrams |
| [DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md) | Why things are the way they are, and when to revisit them |
| [PROVIDERS.md](docs/PROVIDERS.md) | Each extraction provider; adding a new one |
| [MEDIA_PIPELINE.md](docs/MEDIA_PIPELINE.md) | Format selection, AAC conversion, ZIP, merging, verification |
| [API.md](docs/API.md) | Every endpoint with examples |
| [SECURITY.md](docs/SECURITY.md) | Threat model, cookie handling, limits |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Setup, structure, debugging, updating dependencies |
| [TESTING.md](docs/TESTING.md) | Test suites, live checks, audio verification |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Error codes and fixes |
| [FRONTEND_DESIGN_SYSTEM.md](docs/FRONTEND_DESIGN_SYSTEM.md) | Visual identity and logo, colour tokens, components, navigation, accessibility conventions |
| [UI_UX_REVIEW.md](docs/UI_UX_REVIEW.md) | Interface review and what the v1.7 redesign implemented |
| [GITHUB_READINESS.md](docs/GITHUB_READINESS.md) | Historical (v1.6 to v1.9.0) publication checklist, superseded by `docs/open-source/` |
| [CODE_REVIEW_REPORT.md](docs/CODE_REVIEW_REPORT.md) | Historical v1.6 audit findings and fixes |
| [docs/open-source/](docs/open-source/README.md) | v1.9 code, security, licence and documentation audits; publication plan; maintainer guide; desktop app proposal |
| [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | How to contribute, report a vulnerability, and community standards |
| [BRAND_ASSETS.md](BRAND_ASSETS.md) · [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | Which files are reserved brand assets; third-party licences |

## Visual identity

MediaLab's emblem (an amber film frame carrying an audio waveform, layered over an orange frame) and its palette (amber `#FFB300` on near-black `#0B0D10` and charcoal `#171A20`) are described in [docs/FRONTEND_DESIGN_SYSTEM.md](docs/FRONTEND_DESIGN_SYSTEM.md#2-visual-identity). Assets: `frontend/public/brand/` (horizontal logos for dark and light backgrounds, emblem, small emblem, app icon) and `frontend/public/favicon.svg` / `favicon.ico`. The interface uses Manrope for headings and DM Sans for text, both self-hosted from `frontend/public/fonts/` under the SIL Open Font License 1.1 (no font CDN). The logo, wordmark, icons and favicon are reserved brand assets, not MIT-licensed ([BRAND_ASSETS.md](BRAND_ASSETS.md)).

## Security at a glance

- MediaLab listens only on `127.0.0.1` and refuses requests from other websites (Host and Origin checks). It has **no login or API token**, so any program or other user account on the same computer can use it while it runs. Run it only while you need it on a shared computer.
- Your TikTok cookies (Short Drama only) are stored in a file only your account can read, never shown, and never sent anywhere except TikTok.
- Details, limits and the threat model: [docs/SECURITY.md](docs/SECURITY.md).

## Running from source today, desktop app in the future

MediaLab currently runs **from source** (Python, Node.js and FFmpeg as described above). There is **no standalone installer yet**. A possible macOS and Windows desktop app is only a proposal at this stage, open for community feedback: see [docs/open-source/DESKTOP_APP_DISCUSSION_DRAFT.md](docs/open-source/DESKTOP_APP_DISCUSSION_DRAFT.md).

## Contributing and security

Bug reports, ideas and pull requests are welcome: start with [CONTRIBUTING.md](CONTRIBUTING.md). Please report security problems privately as described in [SECURITY.md](SECURITY.md), and never attach cookies, `settings.json` or downloaded media to an issue.

## Licence

- **Code:** the MediaLab source code and documentation are licensed under the [MIT licence](LICENSE).
- **Brand:** the MediaLab name as a product name, logo, wordmark artwork, application icons and favicon are **not** covered by the MIT licence and are reserved. Forks that distribute a modified version should use their own name and artwork. The exact files and what you may do are listed in [BRAND_ASSETS.md](BRAND_ASSETS.md).
- **Third-party components** keep their own licences: the bundled fonts are under the SIL Open Font License 1.1, and dependencies installed by `make setup` and FFmpeg (installed by you) have theirs. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
