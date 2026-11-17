# GitHub publication plan

*Prepared 2026-11-14. Nothing here has been done on GitHub: no repository, remote, push, release, issue or Discussion exists. The plan assumes a personal GitHub account (no organisation) on the free plan; everything listed is available to public repositories on that plan.*

## 1. Before publishing (essential)

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | Decide what history to publish (author email, CR-14) | **Decided: clean snapshot** | The public repository starts from a reviewed snapshot with a new first commit; development history stays private ([CR-14](CODE_REVIEW_V1_9.md#cr-14-medium-publication-decision-commit-metadata-contains-a-personal-email-address)). Make that first commit with your GitHub `noreply` address |
| 2 | Confirm the MIT licence and copyright line | **MIT decided**; copyright line still to confirm | `LICENSE` says "MediaLab contributors" ([licence audit](DEPENDENCY_LICENSE_AUDIT.md#5-copyright-notices)) |
| 3 | Decide whether the logo/name are MIT or reserved | **Decided: reserved** | Documented in [BRAND_ASSETS.md](../../BRAND_ASSETS.md); legal review of the wording recommended |
| 4 | Fill in placeholders | **Done** | Contacts point to the maintainer's GitHub profile and to Private Vulnerability Reporting; `.github/ISSUE_TEMPLATE/config.yml` uses `kazeboy/MediaLab` |
| 5 | Replace real creator/series names in fixtures and docs | **Done** | CR-13 |
| 6 | README reviewed for first-time visitors | Done on this branch | Requirements, setup, limitations, contributing and security links |
| 7 | Community files | Drafted on this branch | `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue forms, PR template, discussion forms |
| 8 | Final secrets scan | Done 2026-11-14 | [SECURITY_AUDIT.md](SECURITY_AUDIT.md); repeat right before the first push |
| 9 | Review the public snapshot | Owner review | The snapshot is a separate folder without Git history; nothing is merged in the private repository |

## 2. Creating the repository (when ready)

1. On GitHub: **New repository**. Name `MediaLab` (check it's free); description: "Save X, TikTok and TikTok Short Drama videos as MP4 locally, in original quality. FastAPI + yt-dlp + FFmpeg, React UI." Visibility **Public**. Don't add a README, licence or `.gitignore` there (the repository already has them).
2. Locally, **in the reviewed snapshot folder** (not the private development repository): `git init -b main`, set `user.name` and your GitHub `noreply` address for this repository, add and commit the files as the first commit, optionally tag it `v1.9.0`, then `git remote add origin git@github.com:<you>/MediaLab.git` and `git push -u origin main --tags`. The private repository is never pushed.
3. Immediately in **Settings → Code security**: enable **private vulnerability reporting**, **secret scanning**, **push protection**, **Dependabot alerts** and **Dependabot security updates**.
4. **Settings → General → Features:** enable **Discussions**; create categories (section 4); keep Issues on; consider turning Wiki off (docs live in the repository).
5. **Settings → Rules:** add a ruleset for `main` (section 6).

## 3. Soon after publishing (can follow)

| Item | Why |
|---|---|
| CI workflow (section 5) | Runs the tests on every pull request |
| Dependabot version updates (section 5) | Keeps yt-dlp and other dependencies current |
| Code scanning with CodeQL (default setup) | Free static analysis for Python and JavaScript |
| A first GitHub Release for `v1.9.0` | Release notes from `CHANGELOG.md`; **source only, no binaries** |
| Topics and social preview image | Discoverability (`yt-dlp`, `fastapi`, `react`, `video-downloader`, `macos`) |
| Post the desktop proposal | [DESKTOP_APP_DISCUSSION_DRAFT.md](DESKTOP_APP_DISCUSSION_DRAFT.md) |

## 4. Discussion categories (proposal)

| Category | Format | Purpose |
|---|---|---|
| Announcements | Announcement (maintainer posts only) | Releases and important notices |
| Q&A | Question/answer | Setup and usage questions (form: `.github/DISCUSSION_TEMPLATE/q-a.yml`) |
| Ideas | Open discussion | Feature ideas before they become issues (form: `ideas.yml`) |
| Desktop app | Open discussion | Packaging, signing, platform feedback (form: `desktop-app.yml`; the category slug must be `desktop-app`) |
| Show and tell | Open discussion | How people use MediaLab |

## 5. Draft GitHub Actions

These are **drafts to copy into `.github/workflows/` and `.github/dependabot.yml` after review**. They are kept here as text so nothing runs before you decide. Pin action versions to commit SHAs when you adopt them.

### CI: tests on every push and pull request

```yaml
# .github/workflows/ci.yml
name: CI
on:
  push:
    branches: [main]
  pull_request:
permissions:
  contents: read
jobs:
  backend:
    runs-on: macos-latest          # the supported platform; FFmpeg tests run too
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: brew install ffmpeg
      - run: python -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.lock
      - run: cd backend && .venv/bin/python -m pytest
  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "22", cache: npm, cache-dependency-path: frontend/package-lock.json }
      - run: cd frontend && npm ci && npm run typecheck && npm test && npm run build
      - run: cd frontend && npm audit --omit=dev
```

### Secret scanning on pull requests

```yaml
# .github/workflows/secrets.yml
name: Secret scan
on: [push, pull_request]
permissions:
  contents: read
jobs:
  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

Add a `.gitleaks.toml` with a custom rule for TikTok cookie names (`sessionid`, `sid_tt`, `sid_guard`, `msToken`, `tt_csrf_token`), since generic rules don't recognise them. (Check gitleaks-action's licence terms: it is free for personal accounts.)

### Dependabot

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: pip
    directory: /backend
    schedule: { interval: weekly }
  - package-ecosystem: npm
    directory: /frontend
    schedule: { interval: weekly }
    groups:
      dev-tools: { dependency-type: development }
  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: monthly }
```

yt-dlp changes often; weekly pull requests for it are expected and worth merging promptly after the tests pass.

## 6. Branch protection (ruleset for `main`)

For a single maintainer, keep it light:

- Require a pull request before merging, with **0 required approvals** (you can merge your own PRs, but outside contributions always go through review).
- Require status checks to pass (`backend`, `frontend`, `gitleaks`) once CI exists.
- Block force pushes and deletion of `main`.
- Optionally require linear history if you prefer squash merges.

## 7. Releases

- Tag format stays `vMAJOR.MINOR.PATCH` (annotated tags, as today).
- Create a GitHub Release from each tag with the `CHANGELOG.md` section as notes. GitHub attaches source archives automatically.
- **No binaries** until the desktop work is signed and reviewed.

## 8. After publication: first weeks

- Answer issues and Discussions when you can; it's fine to say "not planned".
- Label new issues (`bug`, `enhancement`, `documentation`, `question`, `good first issue`).
- Watch Dependabot and secret-scanning alerts.
- Revisit the [readiness audit](READINESS_AUDIT.md) items marked "after publication".
