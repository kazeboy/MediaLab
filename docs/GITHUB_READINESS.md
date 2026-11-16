# GitHub readiness (v1.6)

> **Historical document, superseded.** Kept as the record of the v1.6 to v1.9.0 checks. The current assessment, publication plan and community files are in [open-source/](open-source/README.md).

> **v1.9.0 update (2026-11-14):** `main` holds v1.9.0 (tag `v1.9.0`: bulk X/TikTok downloads, immediate cancellation, New Download). Still **no remote, nothing pushed**. Tests: 571 backend + 84 frontend.
>
> **v1.8.1 update (2026-11-13):** `main` holds v1.8.1 (tag `v1.8.1`: favicon fix, Manrope and DM Sans typography, punctuation clean-up). Still **no remote, nothing pushed**. Tests: 539 backend + 67 frontend.
>
> **v1.8 update (2026-11-13):** `main` now holds v1.8.0 (tags `v1.6.0`, `v1.7.0`, `v1.8.0`; feature branches kept). Still **no remote, nothing pushed**. Tests: 538 backend + 56 frontend. Versions aligned at 1.8.0; `CHANGELOG.md` added. A final history-wide secrets scan found only fake test fixtures and documentation text.
>
> **v1.7 update (2026-11-13):** the project is now a local Git repository: `main` holds the audited v1.6 baseline (tag `v1.6.0`); the v1.7 redesign is on `feature/v1.7-frontend-redesign`, not yet merged. **No remote is configured and nothing has been pushed.** Tests: 536 backend + 47 frontend (unit and component). The checklist below is the v1.6 assessment; the secrets/ignore checks were repeated before each v1.7 commit.

Assessment of whether the working tree can be published as a public repository. Nothing has been committed or pushed; the directory is **not yet a Git repository**.

## Verdict

**Almost ready.** No secrets or private data were found in the working tree, ignore rules cover credentials, settings and media, dependencies are permissively licensed and locked, the documentation set is complete, and the project is licensed under **MIT**. Before publishing, the owner must **initialise Git with a reviewed first commit**; the remaining items below are recommended rather than blocking.

## Checklist

### Secrets and private data
| Item | Status | Evidence |
|---|---|---|
| TikTok cookie file not in the tree | ✅ | Stored outside the repo (`~/Library/Application Support/MediaLab/tiktok-cookies.txt`); `.gitignore` also excludes `tiktok-cookies.txt`, `cookies.txt`, `cookies*.txt` |
| `.env` excluded | ✅ | `.gitignore`: `.env`, `.env.*` (except `.env.example`); the local `.env` contains only two non-secret settings |
| `settings.json` excluded | ✅ | `.gitignore` (and it lives outside the repo) |
| Pattern scan for credentials | ✅ | Scanned for session cookie names, tokens, signed-URL parameters (`x-signature=`), private keys, API keys, passwords and e-mail addresses (outside `.venv`, `node_modules`, `dist`). Matches were only test fixtures with fake values (`SECRET-SESSION`), cookie-name constants in code, and documentation |
| Signed media URLs | ✅ | None; test CDN paths are truncated, without `x-expires`/`x-signature` |
| Local tool settings | ✅ | `.claude/` is ignored |
| Downloaded media | ✅ | No media files in the tree; `.gitignore` excludes `*.mp4`, `*.m4a`, `*.m4v`, `*.mkv`, `*.webm`, `*.zip`, partial files |
| Public identifiers | ⚠️ | Tests and docs name a real public TikTok series, item IDs and creator handles used during verification. Not private, but consider replacing them with synthetic IDs before publishing |

### Build and reproducibility
| Item | Status | Notes |
|---|---|---|
| Python dependency lock | ✅ (new) | `backend/requirements.lock` (exact tested versions); `make setup-locked` |
| Node dependency lock | ✅ | `frontend/package-lock.json`; `npm ci` |
| Package metadata | ✅ (updated) | `pyproject.toml`, `package.json`, FastAPI app all at **1.6.0** with current descriptions |
| One-command setup / run / test | ✅ | `make setup`, `make dev`, `make test` |
| Tests reliable | ✅ | 535 backend + 17 frontend tests pass; batch tests poll with timeouts and passed repeatedly; FFmpeg tests skip cleanly without FFmpeg |
| Tests need no network/accounts | ✅ | All providers faked |
| CI | ❌ | No CI workflow. Recommended: GitHub Actions on macOS running `make setup-locked && make test` (FFmpeg via Homebrew) |

### Licensing
| Item | Status | Notes |
|---|---|---|
| Project licence | ✅ | **MIT**, chosen by the owner (`LICENSE`; copyright line "MediaLab contributors"; replace with your name if you prefer); declared in `pyproject.toml` and `package.json` |
| Python dependencies | ✅ | MIT/BSD/Apache-2.0/PSF; `certifi` MPL-2.0 (used unmodified); `yt-dlp` Unlicense |
| Node dependencies | ✅ | React, Vite, Tailwind, Vitest: MIT; TypeScript: Apache-2.0 |
| FFmpeg | ✅ | Not bundled; users install it (its LGPL/GPL terms apply to their install, not this repo) |
| Platform terms | ⚠️ | The README and SECURITY.md state that users must respect copyright and platform terms; publishing a downloader may attract platform scrutiny (owner's decision) |

### Documentation
| Item | Status |
|---|---|
| README (overview, setup, usage, limitations, doc index) | ✅ rewritten |
| Architecture, design decisions, providers, media pipeline, API, security, development, testing, troubleshooting | ✅ in `docs/` |
| Security policy discoverable by GitHub | ✅ `docs/SECURITY.md` (GitHub reads `SECURITY.md` in the root, `docs/` or `.github/`) |
| CONTRIBUTING / CODE_OF_CONDUCT / issue templates | ❌ recommended |
| CHANGELOG | ❌ recommended (version history currently lives in the release briefs and these docs) |

## Recommended release structure

```
LICENSE                      (MIT)
README.md
CHANGELOG.md                 ← recommended (v1.0 … v1.6)
CONTRIBUTING.md              ← recommended (setup, tests, no media/cookies in issues)
docs/…
backend/  frontend/  scripts/  Makefile  .env.example  .gitignore
.github/workflows/ci.yml     ← recommended
```

## Steps to publish (for the owner)

1. Optionally put your name in the `LICENSE` copyright line.
2. Optionally replace real TikTok IDs/handles in tests and docs with synthetic ones.
3. `git init`, then review `git status` and `git add -n .` output and confirm no `.env`, cookies, settings, media or `node_modules` are listed.
4. Make the first commit; create the repository; push.
5. Enable private vulnerability reporting (Security → Advisories) to match `docs/SECURITY.md`.
