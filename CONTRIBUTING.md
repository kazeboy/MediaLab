# Contributing to MediaLab

Thanks for your interest in MediaLab. It's a small project with one maintainer, so the process is light: open an issue or a pull request, be clear about what you changed and how you tested it, and keep personal data out of everything you post.

## Before you start

- **Bugs:** open a [bug report](.github/ISSUE_TEMPLATE/bug_report.yml). Search existing issues first.
- **Ideas and bigger changes:** open a [feature request](.github/ISSUE_TEMPLATE/feature_request.yml) or start a Discussion before writing a lot of code, so we can agree on the approach.
- **Questions:** use Discussions (Q&A) rather than issues.
- **Security problems:** don't open a public issue. Follow [SECURITY.md](SECURITY.md).
- **Scope:** MediaLab downloads content its users may save. It doesn't bypass DRM, paywalls, region blocks, private accounts or platform request signing, and pull requests that do will be declined (see [docs/SECURITY.md](docs/SECURITY.md#scope-and-non-goals)).

> **Never post** cookies, `cookies.txt` exports, `settings.json`, signed media URLs (links containing `x-expires`, `signature` or similar), or downloaded media in issues, pull requests or screenshots.

## Development setup

Requirements: macOS (the supported platform today), Python 3.11 or later, Node.js 20.19+ or 22.12+, FFmpeg with FFprobe.

```bash
brew install python node ffmpeg
git clone <your fork> MediaLab && cd MediaLab
make setup          # Python venv + npm install
make dev            # backend on 127.0.0.1:8000, UI on http://127.0.0.1:5173
```

More detail: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). The architecture is explained in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Running the tests

```bash
make test           # backend (pytest) + frontend type-check and Vitest
make test-backend   # backend only
make test-frontend  # frontend only
cd frontend && npm run build   # production build
```

No test needs the internet or a TikTok account; FFmpeg tests are skipped if FFmpeg is missing. Every pull request should keep all tests passing and add tests for new behaviour or fixed bugs. [docs/TESTING.md](docs/TESTING.md) explains the suites and the manual live checks.

## Coding conventions

- **Python:** follow the style of the surrounding code (type hints, short docstrings that explain *why*, `AppError` with a specific `ErrorCode` for anything the user can see). Never call a shell; pass argument lists to subprocesses.
- **TypeScript/React:** use the shared components in `frontend/src/components/ui` and the semantic colour tokens; keep job and batch state in the activity registry (`lib/activity.tsx`). Check dark and light themes, a 375 px width and keyboard use for UI changes.
- **Copy and docs:** clear, plain English. MediaLab's own text doesn't use em dashes (a test checks this); use full stops, commas, colons or parentheses instead.
- **Dependencies:** add one only when it clearly pays for itself, and say why in the pull request.

## Branches and commits

- Branch from `main` with a short descriptive name: `fix/delivery-early-close`, `feat/bulk-retry-all`, `docs/troubleshooting-ffmpeg`, `chore/ci`.
- Write commit messages in the imperative mood with a type prefix, as the history does: `fix(api): …`, `feat(ui): …`, `docs: …`, `test: …`, `chore: …`. A short body that explains *why* helps a lot.
- Keep pull requests focused: one fix or feature per pull request.

## Pull requests

1. Fork the repository and create a branch.
2. Make your change with tests and documentation updates (README, `docs/`, `CHANGELOG.md` under "Unreleased").
3. Run `make test` and the frontend build.
4. Open a pull request and fill in the template. Screenshots help for UI changes (with no personal data visible).
5. The maintainer reviews, may ask for changes, and merges when it's ready. Please be patient: this is maintained in spare time.

By contributing you agree that your contribution is licensed under the project's [MIT licence](LICENSE).

## Community standards

Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
