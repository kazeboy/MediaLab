# Dependency and licence audit

*Audit date: 2026-11-14, tag `v1.9.0`. Licences were read from installed package metadata (`importlib.metadata` in `backend/.venv`; `package.json`/`package-lock.json` in `frontend/node_modules`), from licence files shipped in the repository, and from the upstream projects' official pages where noted. This is a technical audit, not legal advice; items marked **to verify** should be checked by the owner (and counsel for anything commercial) before a binary is distributed.*

## Verdict

- **Publishing the source under MIT is compatible with everything the repository contains or installs.** All runtime dependencies are under permissive licences (MIT, BSD, Apache-2.0, PSF, ISC, Unlicense) or MPL-2.0 used unmodified. The fonts are under the SIL Open Font License 1.1 with their licence texts committed. The logo, icons and favicon were drawn for MediaLab.
- **A future desktop installer changes the picture:** it would *redistribute* Python, the Python packages, native libraries inside `curl_cffi`, and FFmpeg. FFmpeg's licence (LGPL or GPL depending on the build) is the main question. See section 4.
- The MIT licence was **not** changed.

## 1. Three distribution situations

| Situation | Who installs what | MediaLab's obligations |
|---|---|---|
| **A. Developer tools** | Contributors install test and build tools (`pytest`, Vite, TypeScript, Tailwind, Vitest, jsdom…) | None beyond not committing them; they never ship to users |
| **B. Running from source** | Users run `make setup`: pip and npm download dependencies from PyPI/npm themselves; users install FFmpeg (e.g. Homebrew) themselves | MediaLab distributes only its own code; each package arrives with its own licence. Listing them (this file) is good practice, not a requirement |
| **C. Desktop installer (future)** | MediaLab's release would *contain* Python, every runtime package, native libraries, the built frontend, fonts and FFmpeg | MediaLab must comply with each bundled component's licence: include notices and licence texts, and for LGPL/GPL/MPL parts meet their source-availability terms |

## 2. Python runtime dependencies (situations B and C)

From `backend/requirements.txt` (direct: `fastapi`, `uvicorn`, `yt-dlp[curl-cffi]`, `certifi`) and their installed dependencies:

| Package | Version tested | Licence | Notes |
|---|---|---|---|
| yt-dlp | 2026.10.26 | Unlicense (public-domain dedication) | See 4.3: yt-dlp's own *standalone executables* are GPLv3+ because of what *they* bundle |
| curl_cffi | 0.17.0 | MIT | Ships a compiled module (`_wrapper.abi3.so`) that statically includes curl-impersonate (libcurl, BoringSSL and compression libraries). **To verify** for situation C: the exact third-party notices required for those libraries (curl licence, BoringSSL/OpenSSL-style licences) |
| cffi | 2.1.1 | MIT-0 | |
| pycparser | 3.12 | BSD-3-Clause | |
| certifi | 2026.10.23 | MPL-2.0 | File-level copyleft: redistributing it unmodified is fine; keep its licence and note where its source is available |
| fastapi | 0.162.4 | MIT | |
| starlette | 1.10.0 | BSD-3-Clause | |
| uvicorn | 0.54.0 | BSD-3-Clause | |
| pydantic / pydantic_core | 2.14.3 / 2.50.4 | MIT | `pydantic_core` is a compiled Rust extension |
| anyio, h11, annotated-types, annotated-doc, typing-inspection | | MIT | |
| typing_extensions | 4.16.0 | PSF-2.0 | |
| click, idna, httpcore | | BSD-3-Clause | |
| opentelemetry-api | 1.45.2 | Apache-2.0 | Required by the installed FastAPI version (`pip show`: required by `fastapi`); a genuine runtime dependency |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | |

Test/development packages also present in `requirements.lock` (`pytest`, `httpx`, `Pygments`, `iniconfig`, `pluggy`; MIT/BSD) belong to situation A and should move to a separate dev lock (CR-08).

`pip-audit -r backend/requirements.lock` (2026-11-14): no known vulnerabilities.

## 3. JavaScript dependencies

- **Shipped to the browser (situations B and C):** only `react` 19.3.1, `react-dom` 19.3.1 and `scheduler` 0.28.0, all MIT. They are compiled into `frontend/dist/assets/*.js`.
- **Build and test tools (situation A):** 175 packages in `package-lock.json`: MIT 128, Apache-2.0 25, MPL-2.0 12 (the Tailwind CSS compiler `lightningcss` and its platform binaries), ISC 3, BSD-2/3-Clause 4, 0BSD 2, BlueOak-1.0.0 1. None is GPL, AGPL, SSPL or non-commercial; none ends up in the built page.
- `npm audit` (2026-11-14): 0 vulnerabilities (all and production-only).

If the built bundle is ever distributed (situation C), MIT requires keeping React's copyright notice: include a third-party notices file that lists React, React DOM and Scheduler.

## 4. Media tools and bundled assets

### 4.1 Fonts (verified)

Manrope (weights 600, 700) and DM Sans (400, 500, 600), WOFF2 from Fontsource 5.3.0, are licensed under the **SIL Open Font License 1.1**. The licence texts with copyright lines are committed and served with the app (`frontend/public/fonts/OFL-Manrope.txt`, `OFL-DMSans.txt`). OFL allows bundling with software, including commercially, as long as the fonts aren't sold on their own and the licence travels with them. Nothing more is needed.

### 4.2 Logo, icons, favicon (verified from history)

The emblem, logos, app icons and favicon (`frontend/public/brand/`, `favicon.svg`, `favicon.ico`, `apple-touch-icon.png`) were created for MediaLab in commits `7d36cdb` and `56f9c03`. UI icons are hand-written inline SVG paths in `components/ui/primitives.tsx`. No third-party icon set is used. They fall under the repository's MIT licence unless the owner decides to treat the brand separately (common practice: code MIT, logo "all rights reserved" so forks rename). **Open question for the owner.**

### 4.3 yt-dlp distribution note (official README)

yt-dlp itself is Unlicense, but its project states that its PyInstaller-built standalone executables include GPLv3+ code, so those executables are GPLv3+ as a whole ([yt-dlp README](https://github.com/yt-dlp/yt-dlp/)). MediaLab installs yt-dlp from PyPI, not those executables. A MediaLab installer would be built from MediaLab's own dependency set, which (section 2) contains no GPL Python package today. **To verify** at packaging time with a licence scan of the frozen bundle, because optional extras can change this.

### 4.4 FFmpeg (the main question for situation C)

- Today MediaLab doesn't distribute FFmpeg: users install it (Homebrew's build includes GPL components such as libx264).
- FFmpeg is LGPL 2.1+ by default; builds configured with `--enable-gpl` (needed for libx264) are GPL 2+, and `--enable-nonfree` builds may not be redistributed at all ([FFmpeg legal page](https://ffmpeg.org/legal.html)).
- MediaLab needs FFmpeg for: remuxing (stream copy), MP3/Opus → AAC conversion (FFmpeg's built-in `aac` encoder, LGPL), probing, and **one GPL-dependent feature**: re-encoding merged Short Drama episodes with `libx264` when they don't share a format.
- Options for an installer:
  1. **LGPL build** without libx264; re-encode merges with platform encoders that LGPL builds can use (`h264_videotoolbox` on macOS, `h264_mf` on Windows). Keeps the whole bundle permissive-plus-LGPL. Requires code changes and quality testing.
  2. **GPL build** shipped as a *separate executable* invoked as a subprocess, with its licence, source (or a written offer) and build configuration published alongside each release. Commonly treated as aggregation that doesn't change MediaLab's MIT licence; **to verify with counsel**.
- Either way: ship FFmpeg's licence, state the build configuration, and provide the matching source.

### 4.5 Test fixtures and third-party material

- Test media is generated at test time with FFmpeg (`testsrc`, `sine`, `anullsrc`); no third-party media is committed.
- Provider fixtures are hand-written JSON shaped like real responses; they contain no copied page content beyond short titles and IDs (see CR-13 about replacing real names).
- No copied third-party source code was found. `docs/` text is original.

## 5. Copyright notices

- `LICENSE`: "Copyright (c) 2026 MediaLab contributors". Valid for MIT. If the owner wants to be named, use their name or handle; "contributors" is a common choice for community projects. **Owner decision.**
- `backend/pyproject.toml` (`license = "MIT"`) and `frontend/package.json` (`"license": "MIT"`) match.
- Recommended for situation C: a generated `THIRD_PARTY_NOTICES` file in each installer (Python packages, React, fonts, curl-impersonate components, FFmpeg).

## 6. Open questions

1. Treat the MediaLab logo and name as MIT, or reserve them (trademark-style) so forks rebrand?
2. FFmpeg build for the installer: LGPL with platform encoders, or GPL as a separate executable? (Counsel recommended.)
3. Exact notice requirements for the libraries statically linked into `curl_cffi`.
