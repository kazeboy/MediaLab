# Development guide

## Local environment

| Tool | Version used for v1.8 | Notes |
|---|---|---|
| macOS | 26.6 (Apple silicon) | The backend has run on Linux but isn't tested there regularly; Windows isn't supported yet. QuickTime/AVFoundation checks need macOS |
| Python | 3.12.3 (≥ 3.11 required) | `backend/.venv` |
| Node.js / npm | 26.8 / 11.19 | `frontend/node_modules` |
| FFmpeg / FFprobe | 9.0.1 (Homebrew, with `libx264`, `libx265`, `libmp3lame`) | `brew install ffmpeg` |

## Setup

```bash
make setup          # venv + pip install -r backend/requirements-dev.txt + npm install
make setup-locked   # same, but exact tested versions: backend/requirements.lock + npm ci
```

`requirements.txt` keeps lower bounds (yt-dlp must be updated often); `requirements.lock` pins what v1.6–v1.8 were tested with (unchanged since v1.6); `frontend/package-lock.json` pins the frontend.

## Running

```bash
make dev        # backend (127.0.0.1:8000, auto-reload) + Vite (127.0.0.1:5173); open http://127.0.0.1:5173
make backend    # API only
make frontend   # Vite only
make start      # build the UI and serve everything from FastAPI on :8000
```

`scripts/dev.sh` checks both ports first (and names the process holding a port), starts both servers, and stops both if either exits. Stop with Ctrl+C.

Configuration: copy `.env.example` to `.env` (all values optional). GUI preferences live in `~/Library/Application Support/MediaLab/settings.json`.

## Project structure

```
backend/
  app/                 FastAPI app (see docs/ARCHITECTURE.md §2.3 for the module map)
    api/               routes.py (endpoints), delivery.py (streaming responses)
    providers/         base, router, chain, ytdlp_provider, ytdlp_normalise, fxtwitter_provider, tiktok_shortdrama
  tests/               pytest suite (fakes in conftest.py / fixtures.py)
  requirements*.txt, requirements.lock, pyproject.toml
frontend/
  src/App.tsx, main.tsx, index.css
  src/components/      Workspace, DownloadPanel, ResolutionPicker, … (single-video flow)
    shortdrama/        ShortDramaWorkspace, SeriesView, EpisodeList, BatchActionBar, BatchProgress
    downloads/         DownloadsDrawer
    settings/          SettingsDialog
    ui/                design-system kit (primitives.tsx, interactive.tsx; see docs/FRONTEND_DESIGN_SYSTEM.md)
    __tests__/         component tests (Vitest + Testing Library, jsdom)
  src/lib/             activity.tsx, api.ts, types.ts, platform.ts, format.ts, save.ts, selection.ts (+ __tests__)
  src/test/            setup.ts (jest-dom matchers, cleanup), fixtures.ts (API response builders)
docs/                  this documentation
scripts/dev.sh, Makefile, .env.example
```

## Debugging

- **Backend logs** (the `make dev` terminal): every API error is logged as `METHOD path -> code (status): message | cause: <exception chain>`; yt-dlp warnings appear as `yt-dlp warning: …`. Logging is configured at INFO in `app/__main__.py`; yt-dlp's own debug output is routed to the `app.providers.ytdlp_provider` logger at DEBUG level (change the level there temporarily when investigating; it never contains cookie values).
- **OpenAPI:** `http://127.0.0.1:8000/docs` to call endpoints by hand.
- **A provider in isolation:**
  ```bash
  cd backend && .venv/bin/python -c "
  from app.config import Settings; from app.providers.ytdlp_provider import YtDlpProvider
  from app.validation import validate_post_url
  p = YtDlpProvider(Settings.from_env(), 'tiktok')
  print(p.extract(validate_post_url('https://www.tiktok.com/@<creator>/video/<video id>')))"
  ```
- **Media problems:** `ffprobe -v error -show_streams -show_format file.mp4`; for Apple playback see [TESTING.md](TESTING.md#audio-verification).
- **Temporary files:** `<system temp>/medialab/` (`job-*`, `job-batch-*`, `ready/`). Settings → "Temporary storage in use" shows the total.

## Testing

```bash
make test           # backend pytest + frontend type-check + vitest
make test-backend
make test-frontend
```
Frontend only, from `frontend/`: `npm test` (Vitest, once), `npx vitest` (watch), `npm run typecheck`, `npm run build`.

**Component tests** render real components in jsdom (`// @vitest-environment jsdom` at the top of the file) and mock the network at the `lib/api` module boundary (`vi.mock("../../lib/api", …)`), never `fetch`. Use `src/test/fixtures.ts` for response shapes and drive the UI with `@testing-library/user-event` (keyboard included). Mocks are restored between tests (`restoreMocks` in `vite.config.ts`).

**Bulk mode and cancellation** (v1.9): backend tests in `tests/test_bulk.py` hold downloads with per-post `threading.Event` gates (`BulkProvider`) to observe the queue mid-run; use the same pattern for new queue or cancellation tests rather than sleeps. `MEDIALAB_MAX_BULK_URLS` (default 50, at most 100) sets the link limit.

**UI changes:** use the `components/ui` kit and the semantic colour tokens ([FRONTEND_DESIGN_SYSTEM.md](FRONTEND_DESIGN_SYSTEM.md)); check light and dark, 375 px and desktop, and keyboard focus before committing.

Details in [TESTING.md](TESTING.md).

## Updating dependencies

- **yt-dlp** (often): `make update-ytdlp`, then `make test` and the live checks in [TESTING.md](TESTING.md#live-checks). The Short Drama provider uses two private yt-dlp methods; if they disappear, its tests fail with a clear `extraction_failed`.
- **Other Python packages:** `backend/.venv/bin/pip install -U <pkg>`, run tests, then refresh the lock: `backend/.venv/bin/pip freeze > backend/requirements.lock` (keep the two header comment lines).
- **Frontend:** `cd frontend && npm update` (or `npm install <pkg>@<version>`), then `npm run build && npm test`.
- **FFmpeg:** `brew upgrade ffmpeg`; run `make test-backend` (FFmpeg integration tests).

## Adding an API route

1. Define request/response models in `schemas.py` (`ConfigDict(extra="forbid")` for requests; strict types and bounds).
2. Add the route in `api/routes.py`. Use `def` for quick sync work, or `async def` + `run_in_executor` for anything slow (network, FFmpeg). Never block the event loop.
3. Raise `AppError` with an `ErrorCode` (add a new code in `errors.py` with status, default action and retryability if needed).
4. State-changing routes are automatically CSRF-guarded by `same_origin_guard`; don't add CORS.
5. Mirror the types in `frontend/src/lib/types.ts`, add a function in `lib/api.ts`.
6. Tests in `tests/test_api.py` (happy path, validation, cross-site refusal if relevant); document in [API.md](API.md).

## Adding a provider

See [PROVIDERS.md](PROVIDERS.md#adding-a-provider).

## Working with FFmpeg

- Build commands as **lists** and pass absolute paths; never use `shell=True`.
- Single-file work goes through `MediaProcessor.run` (timeout = `MEDIALAB_FFMPEG_TIMEOUT_SECONDS`); long, cancellable work through `packaging.run_ffmpeg` (progress + watchdog).
- Never re-encode video in the single-file path; audio conversion rules live in `media.py` (`APPLE_MP4_AUDIO`, `CONVERTIBLE_AUDIO`).
- After changing a command, add or update a real-FFmpeg test in `tests/test_audio.py` / `tests/test_packaging.py` (generated fixtures) and do an Apple playback check.

## Troubleshooting development issues

| Symptom | Cause / fix |
|---|---|
| `make dev`: "port 8000 is already in use" | An earlier backend still runs; the script prints the PID. Stop it (`kill <pid>`). |
| UI shows "MediaLab cannot connect to its local backend" | The backend isn't running or crashed at startup; check the `make dev` terminal. |
| Startup error about the temporary/settings folder (EPERM) | macOS privacy protection; choose another folder or grant your terminal "Files and Folders" access. |
| TikTok tests pass but live TikTok fails with "impersonation" | `yt-dlp[curl-cffi]` missing: `make setup` / `make update-ytdlp`. |
| FFmpeg tests are skipped | FFmpeg not on `PATH`; `brew install ffmpeg`. |

More user-facing problems: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
