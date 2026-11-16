# Security and repository hygiene audit

*Audit date: 2026-11-14, tag `v1.9.0`. Scope: the running code's security properties and everything a public repository would expose (tracked files, full history, tags). Code-level security findings are cross-referenced from [CODE_REVIEW_V1_9.md](CODE_REVIEW_V1_9.md).*

## Verdict

- **No credentials, cookies, tokens, signed URLs or downloaded media are in the repository or its history.**
- **One publication decision:** every commit's author metadata contains a personal email address (CR-14). Resolve before publishing.
- The local-only security model is sound for a single-user machine; its limits (no API authentication; any local account can reach the port) are now documented accurately (CR-02).

## 1. Repository and history scan (verified)

What was scanned: all 152 tracked files, every commit on every branch (`git log --all -p`, 27,080 added lines) and the 5 annotated tags. No dedicated scanner (gitleaks, trufflehog, detect-secrets) is installed locally, so a pattern scan was used; the recommended automated setup for the future is in section 5.

| Pattern | Result |
|---|---|
| TikTok session cookies (`sessionid`, `sid_tt`, `sid_guard`, `uid_tt`, `msToken`, `tt_csrf_token`, `ttwid` with a value) | none |
| Netscape `cookies.txt` lines for tiktok.com | none |
| AWS, GitHub, OpenAI/Anthropic-style API keys; bearer tokens; private keys | none |
| Signed media URLs (`x-expires`, `X-Amz-Signature`, `Signature=`, `tk=`) | one hit, which is documentation text describing this very check |
| Email addresses in file content | none; the matches are Python decorators (`@pytest.fixture`) and `user@host` strings in URL-rejection tests |
| Machine-specific paths (`/Users/<name>`, `C:\Users`) | one, an intentionally fake `/Users/me/path` in a test of error redaction |
| Personal data in commit metadata | **all 29 commits use a personal author address** (not shown here); see CR-14 |

Tracked-file categories checked: no `.env`, `settings.json`, `cookies*.txt`, `tiktok-cookies.txt`, `*.mp4`/`*.zip`/media, logs, keys, virtual environments, `node_modules` or build output. The only binary files are the brand PNGs, `favicon.ico` and the 10 WOFF2 font files.

### Ignore rules (verified with `git check-ignore`)

`.env` (but not `.env.example`), `backend/.venv`, `frontend/node_modules`, `frontend/dist`, `cookies.txt`, `tiktok-cookies.txt`, `settings.json`, `*.mp4`, `*.zip`, logs and editor folders are all ignored. Present-but-ignored locally: `.env`, `.claude/`, caches, `backend/.venv`, `frontend/node_modules`, `frontend/dist`.

### Local personal data stays outside Git (verified)

The TikTok cookie file and `settings.json` live in `~/Library/Application Support/MediaLab/` (the cookie file is owner-only, `-rw-------`; its contents were **not read**). Temporary media lives under the system temporary folder. Neither path is inside the repository.

## 2. Third-party names in public test data (recommendation)

No secrets, but the v1.9.0 repository named real creators (two TikTok handles in docs), a real Short Drama series title with its IDs (tests, frontend fixtures, API examples) and a real X post ID under placeholder handles. Replace with neutral placeholders before publication (CR-13). **Done for the public snapshot (2026-11-16).** Fixture media URLs are truncated paths without signatures or expiry parameters.

## 3. Application security review (summary)

| Area | Status | Evidence |
|---|---|---|
| Binding | Loopback only; non-local binding refused unless `MEDIALAB_ALLOW_NON_LOCAL` | `config.py`, `main.py` |
| Cross-origin / DNS rebinding | Host allowlist; `Origin`/`Sec-Fetch-Site` guard on every state-changing route, including the v1.9 routes | `main.py`; `test_api.py`, `test_bulk.py` |
| API authentication | **None** (any local account can call it) | CR-02 |
| SSRF and redirects | Per-platform media-host allowlists; https only; every redirect hop validated | `validation.py`, `net.py`, `resolve.py` |
| Path traversal | IDs are 32-hex and validated; delivery paths must stay under the delivery root | `storage.py` `is_valid_id`, `DeliveryStore.begin` |
| ZIP entries | `/`, `\` and leading `.` refused; names sanitised; CRC verified | `packaging.build_zip`; Windows reserved names not handled (CR-04) |
| Subprocesses | Argument lists, absolute paths, no shell; FFmpeg killed on cancel/timeout | `media.py`, `packaging.py` |
| TikTok cookies | Only tiktok.com cookies kept; file 0600; loaded into memory for the Short Drama provider only; never returned by the API | `tiktok_account.py`; tests |
| Temporary files | Folders 0700; per-job cleanup; retention expiry; startup sweep | `storage.py`, `jobs.py` |
| Logs | Method, path, error code and cause; may include a signed CDN URL from yt-dlp; never cookie values | CR-11 |
| Untrusted metadata | Titles/descriptions are sanitised for filenames and rendered as text by React (no `dangerouslySetInnerHTML`; the only `innerHTML` in `frontend/src` sets a fixed string in a theme test) | `storage.py`; grep |
| Dependencies | `pip-audit -r backend/requirements.lock`: no known vulnerabilities; `npm audit`: 0 | run 2026-11-14 |

## 4. Before publication

1. Decide how to handle commit author metadata (CR-14).
2. Replace third-party names in fixtures and docs (CR-13). Recommended, not mandatory.
3. Enable GitHub **private vulnerability reporting** on the repository right after creating it (the security policy relies on it).
4. Enable GitHub **secret scanning** and **push protection** (free for public repositories).

## 5. Recommended automated secret scanning

- **GitHub's own:** secret scanning and push protection on the public repository (Settings → Code security). Push protection blocks pushes containing recognised tokens.
- **In CI:** a gitleaks step on every pull request (full history on the first run). Draft in [GITHUB_PUBLICATION_PLAN.md](GITHUB_PUBLICATION_PLAN.md#5-draft-github-actions). Add a custom rule for TikTok cookie names (`sessionid`, `sid_tt`, `sid_guard`, `msToken`) because generic scanners don't know them.
- **Locally (optional):** a pre-commit hook running the same gitleaks configuration.

If a scan ever finds a real secret in history: stop, revoke or rotate the credential first (for TikTok cookies: sign out of all sessions on tiktok.com), then agree a remediation plan before any history rewrite.
