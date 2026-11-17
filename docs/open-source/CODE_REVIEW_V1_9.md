# Code review: MediaLab v1.9.0

*Review date: 2026-11-14. Reviewed: tag `v1.9.0` (`e9005e8`). Reviewer: an AI assistant (Claude) working in the project owner's local repository. This is an independent, source-based review: earlier internal reports ([CODE_REVIEW_REPORT.md](../CODE_REVIEW_REPORT.md), v1.6) were treated as claims to check, not as evidence.*

## How to read this report

- **Verified** findings were confirmed in the source and, where stated, by running code. **Risks** are plausible problems that weren't demonstrated. **Open questions** need a decision from the owner.
- Severity: **Critical** (exploitable or data-destroying now), **High** (serious, should be fixed soon), **Medium** (real defect or gap with limited impact), **Low** (minor, hardening or polish).
- "Blocks publication" means the item should be resolved or consciously accepted before the repository is made public.

## Method

1. Read the backend modules end to end (`jobs.py`, `batches.py`, `bulk.py`, `media.py`, `packaging.py`, `storage.py`, `api/routes.py`, `api/delivery.py`, `validation.py`, `tiktok_account.py`, `config.py`, the providers) and the frontend state code (`lib/activity.tsx`, `Workspace.tsx`, `bulk/*`, `DownloadsDrawer.tsx`).
2. Targeted greps for risky patterns: shell execution, `eval`, deserialisation, logging of URLs/cookies/headers, permissions, platform-specific calls.
3. Ran the automated suites (backend 571 passed, frontend 84 passed), `pip-audit` (no known vulnerabilities in `requirements.lock`), `npm audit` (0 vulnerabilities), ruff (style findings only, see CR-09).
4. Used results of the live checks run on 2026-11-13 (recorded in [TESTING.md](../TESTING.md#release-verification-v19-work-2026-11-13-featurev19-download-workflows)).

## Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 0 | |
| High | 0 | |
| Medium | 5 | CR-01, CR-02, CR-03, CR-04, CR-14 |
| Low | 9 | CR-05 to CR-13 |

No finding is a security vulnerability that is exploitable from the network or from a web page in the current loopback-only design. One item (CR-14) is a **publication decision** rather than a code defect. Nothing found here blocks keeping the code as it is for local use.

## Findings

### CR-01 Medium: a file can stay "ready to save" after a complete transfer
- **Where:** `backend/app/api/delivery.py`, `DeliveryResponse.stream_response` and `__call__`.
- **Evidence:** completion is recorded only after `super().stream_response()` returns, i.e. after Starlette has sent the final empty body frame. Starlette also listens for client disconnects while streaming; a client that closes the connection as soon as it has read `Content-Length` bytes can win that race, so `completed` stays `False` and `DeliveryStore.finish(file_id, False)` returns the file to `ready`. Observed live on 2026-11-13: a Python `urllib` client read the whole ZIP (valid, `testzip()` passed), yet batch `a89daae1…` stayed `ready` at 97% until curl fetched it again.
- **Reproduce:** start any download, then fetch `/api/files/<id>` with `urllib.request.urlopen(...).read()` and close immediately; `GET /api/jobs/<id>` still shows `delivery_state: "ready"`.
- **Impact:** no data loss and no security effect. The file occupies temporary storage until the retention period (30 min) and the UI shows "Ready to save" for something already saved. Browsers and curl don't trigger it in testing.
- **Fix:** treat `sent_bytes == size_bytes` as complete even when the final frame raced with the disconnect (the file handle is closed by then), and add a regression test with an early-closing client.
- **Blocks publication:** no.

### CR-02 Medium: the local API has no authentication, and the docs understate who can reach it
- **Where:** `backend/app/main.py` (Host/Origin guards only); `docs/SECURITY.md` "Known security limitations" said "any process running as the same user".
- **Evidence:** the server binds to `127.0.0.1` and refuses foreign `Host` and cross-site `Origin` headers (verified by `test_api.py`), which stops web pages and DNS rebinding. It has no per-session secret. A loopback port is reachable by **every local account** on the machine, not only the owner's processes.
- **Impact:** on a shared Mac, another local user could call the API while MediaLab runs: start downloads, read the account *status* (never cookie values) and use the owner's linked TikTok session for Short Drama lookups and downloads. File IDs are 128-bit random, so reading the owner's finished files requires guessing an ID (infeasible). Single-user Macs are unaffected.
- **Fix:** correct the documentation now (done on this branch). For the desktop application, add a per-launch secret (see [DESKTOP_ARCHITECTURE_PROPOSAL.md](DESKTOP_ARCHITECTURE_PROPOSAL.md#4-local-communication-between-the-ui-and-the-backend)); optionally offer the same opt-in token for the source version.
- **Blocks publication:** no, provided the limitation is documented accurately.

### CR-03 Medium: extraction concurrency isn't bounded globally
- **Where:** `api/routes.py` `analyse` (asyncio semaphore, 4); `bulk.py` `BulkAnalysisManager` (own pool, 2); `batches.py` `_episode_plan` and `_url_plan` (extraction on each batch worker thread).
- **Evidence:** the three paths use separate limits, so in the worst case 4 single analyses + 2 bulk extractions + 2 batch workers extract at once.
- **Impact:** more simultaneous requests to X and TikTok than any single limit suggests; raises the chance of rate limiting (`rate_limited`). No correctness issue.
- **Fix:** one process-wide `threading.BoundedSemaphore` for all extractions, sized by `MEDIALAB_MAX_CONCURRENT_ANALYSES`.
- **Blocks publication:** no.

### CR-04 Medium: the backend doesn't run on Windows as written
- **Where:** `tiktok_account.py` `TikTokAccountStore.save` (`os.fchmod`, which doesn't exist on Windows); `config.py` `_default_config_dir` (no `%APPDATA%` branch); `storage.py` `sanitise_filename_part` (doesn't avoid reserved names such as `CON`, `NUL`, `COM1`); `scripts/dev.sh` and `Makefile` (bash/make only); `0o700`/`0o600` modes have no effect on Windows.
- **Impact:** linking a TikTok account would raise `AttributeError` on Windows; settings would go to `~/.config`; a video titled "CON" would produce an unusable name inside ZIPs extracted on Windows. Not a problem today because the README lists macOS (and the backend on Linux) as supported.
- **Fix:** platform-specific branches, ACLs or DPAPI/Credential Manager for the cookie file on Windows, reserved-name handling in `sanitise_filename_part`, a cross-platform dev script. Required before any Windows desktop build.
- **Blocks publication:** no (blocks a Windows release).

### CR-05 Low: a bulk extraction has no overall time limit
- **Where:** `bulk.py` `BulkAnalysisManager._analyse`.
- **Evidence:** single analyses are wrapped in `asyncio.wait_for(..., analysis_timeout_seconds)`; bulk items rely only on provider socket timeouts and retries.
- **Impact:** a hanging extraction keeps one of the two bulk workers busy; the bulk analysis stays `running`.
- **Fix:** record a deadline per item and mark it `failed` (`timeout`) when exceeded, discarding a late result as cancellation already does.

### CR-06 Low: batches waiting for a decision count against the two-batch limit
- **Where:** `batches.py` `ACTIVE_BATCH` (includes `needs_decision` and `failed`), `create` and `create_from_urls`.
- **Impact:** two stopped or partially failed batches block new batches (`too_many_jobs`) until the user continues, discards or the retention period expires.
- **Fix:** exclude decision-waiting batches from the limit, or name the blocking batches in the error action.

### CR-07 Low: cancelling a "separate files" link batch still hands finished videos to the browser
- **Where:** `batches.py` `_stop_keeping_finished`; `lib/activity.tsx` auto-save effect.
- **Evidence:** intended by D29 ("preserve completed outputs until their normal delivery"), and documented in API.md.
- **Impact:** a user who clicks Cancel may be surprised that one or two finished videos still download.
- **Fix:** design decision: keep, or pause auto-saving after a stop and show explicit Save buttons.

### CR-08 Low: the lock file mixes runtime and test packages and is labelled v1.6
- **Where:** `backend/requirements.lock`.
- **Evidence:** contains `pytest`, `httpx`, `Pygments`, `iniconfig`, `pluggy`; header says "Exact versions MediaLab v1.6 was tested with".
- **Impact:** a future desktop bundle built from it would include test tools; the header misleads.
- **Fix:** split into `requirements.lock` (runtime) and `requirements-dev.lock`, regenerate with hashes (`pip-compile --generate-hashes`) and update the header.

### CR-09 Low: no continuous integration or frontend linter
- **Where:** repository root (no `.github/workflows`); `frontend/package.json` (no ESLint); no `[tool.ruff]` in `backend/pyproject.toml`.
- **Evidence:** an ad hoc ruff run reports 86 style findings (import order, unused `noqa`, FastAPI `Depends` defaults); none is a defect.
- **Fix:** add the CI workflow drafted in [GITHUB_PUBLICATION_PLAN.md](GITHUB_PUBLICATION_PLAN.md#5-draft-github-actions) before accepting outside contributions; add a ruff configuration matching the current style.

### CR-10 Low: a few tests rely on short sleeps
- **Where:** `backend/tests/test_bulk.py` (for example `time.sleep(0.3)` after releasing a gate), `test_api.py::test_cancel_a_running_job`.
- **Impact:** possible flakes on slow shared CI runners.
- **Fix:** replace fixed sleeps with polling helpers (`wait(...)`), as most of the file already does.

### CR-11 Low: server logs can contain signed media URLs
- **Where:** request logging in `main.py` (exception cause chains from yt-dlp); documented in `docs/SECURITY.md`.
- **Impact:** logs stay in the user's terminal today. A desktop build that writes log files would persist short-lived signed CDN URLs.
- **Fix:** redact query strings from URLs in log records before adding file logging.

### CR-12 Low: activity is per browser tab
- **Where:** `lib/activity.tsx` (in-memory registry).
- **Impact:** a second browser tab shows an empty Downloads list while the first tab's downloads run; a reload forgets them (the backend keeps running them). Documented in the drawer footer.
- **Fix:** optional `GET /api/activity` listing recent jobs and batches; relevant for the desktop app.

### CR-13 Low: test fixtures and docs named real creators and a real series (resolved for the public snapshot)
- **Where (at v1.9.0):** `docs/DEVELOPMENT.md` and `docs/CODE_REVIEW_REPORT.md` (two real TikTok creator handles); `backend/tests/test_shortdrama.py`, `frontend/src/test/fixtures.ts`, `docs/API.md` (the Short Drama series title and IDs used in live testing); several tests use a real X post ID under a placeholder handle.
- **Evidence:** no signed URLs, cookies or downloaded media: CDN paths in fixtures are truncated and have no `x-expires`/signature parameters.
- **Impact:** not a secret or licence problem, but a public repository would name third parties and a commercial title in test data.
- **Fix:** replace with neutral placeholders before publication.
- **Status (2026-11-16, `chore/public-snapshot-preparation`):** done. Handles, display names, the series title, post/video/series/episode IDs, a real share link and CDN path fragments were replaced with synthetic values of the same format; all 571 backend and 84 frontend tests still pass.

### CR-14 Medium (publication decision): commit metadata contains a personal email address
- **Where:** Git history: all 29 commits record a personal, non-`noreply` author address (the address itself is not repeated in this report).
- **Impact:** publishing the history makes the address public and permanently associated with the project.
- **Options:** (a) accept it; (b) publish a fresh repository from a single snapshot commit of v1.9.0 made with a GitHub `noreply` address, keeping the full history private; (c) rewrite authorship in the existing history (needs explicit approval; changes every commit hash and tag). Option (b) avoids rewriting history.
- **Blocks publication:** yes, until the owner chooses.
- **Status (2026-11-16):** the owner chose a **clean snapshot** (option b). The public preview contains no Git history or author metadata; the private repository keeps its full history unchanged.
- **Status (2026-11-17):** the public repository's initial commit (`deefe99`) was made with the personal address rather than the `noreply` address, so the address is still visible in that one commit's author metadata. Later commits use the GitHub `noreply` address. Fixing `deefe99` would require rewriting the public history and is left as an open owner decision.

## Earlier conclusions re-checked

| Earlier claim | Status in v1.9.0 |
|---|---|
| "Any process running as the same user can call the API" (SECURITY.md) | **Inaccurate**: any local user (CR-02). Corrected on this branch. |
| "ZIP name checks: no issues found" (v1.6 review, SEC-4) | Still true for path traversal (`/`, `\`, leading `.` are refused); Windows reserved names not covered (CR-04). |
| "A job already in FFmpeg processing finishes that step" (v1.6 to v1.8 API docs) | **Fixed in v1.9**: processing is cancellable (`media.py` `MediaProcessor.run`), verified by `test_bulk.py::test_cancellation_kills_a_running_subprocess` and `test_cancel_during_processing_never_completes`. |
| SSRF, redirect validation, DNS rebinding | Re-checked: media hosts validated per platform (`validation.py`), `net.py` validates every redirect hop, TrustedHost and Origin guards are global middleware and also cover the new v1.9 routes (`test_bulk.py::test_bulk_analysis_request_validation_and_origin`). |
| Subprocesses never use a shell | Re-checked: no `shell=True`, `os.system`, `eval` or `pickle` in `backend/app`. |
| Cookie file is 0600 and never returned | Re-checked: `tiktok_account.py` writes with `0o600` (POSIX); API returns status only (`test_shortdrama.py::test_account_api_never_returns_cookie_values`). File contents were not read for this review. |

## Areas reviewed without findings

- **Download correctness:** option building and Best Available prefer audio (`selection.apply_size_limit`); bulk fallback never upscales (`choose_option(above="closest")`, tested); audio validation after every mux; ordered ZIP entries; batch output limit enforced server-side; cancellation races (completion re-checks state under the lock).
- **Temporary files:** per-job folders removed in `finally`; collected batch videos removed only after verified packaging; startup cleanup; retention expiry. Verified live (temp storage back to 0 after the 2026-11-13 runs).
- **Frontend:** generation counters prevent stale analysis responses after New Download; one polling loop; drawer actions use the same backend IDs as inline controls; theme persistence tested; WCAG AA contrast and target sizes measured at four widths in both themes.
