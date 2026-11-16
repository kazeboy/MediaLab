# Open-source maintainer guide

*Written for MediaLab's owner as a practical introduction to running the project on GitHub. Plain English first; the exact commands are there when you need them.*

## Part 1: the main ideas, with MediaLab examples

### Repository
The project folder plus its full history. Today MediaLab's repository lives only on your Mac. Publishing means creating a copy on GitHub (the **remote**, usually called `origin`) and **pushing** to it.

### Commit
A saved snapshot of changes with a message, for example `feat(ui): add Bulk mode and integrate batches into the Downloads drawer`. Commits form the history; each has an ID (hash) like `9670474`.

### Main branch
`main` is the line of history everyone treats as "the current version". MediaLab's `main` holds released versions: v1.9.0 is the latest.

### Feature branches
Separate lines of work that start from `main`, such as `feature/v1.9-download-workflows`. You work and commit there without disturbing `main`, then **merge** the branch back when it's finished and tested. `chore/open-source-readiness` (this review) is one too.

### Tags
Permanent names for specific commits, such as `v1.9.0`. MediaLab uses annotated tags (they carry a message and date). Tags are how people find exact released versions.

### Releases
GitHub pages built from tags: release notes (from `CHANGELOG.md`), source downloads, and later perhaps installers. A tag is the Git part; a Release is the GitHub presentation of it.

### Forks
A contributor's own copy of MediaLab on GitHub. They can't push to your repository, so they push to their fork and ask you to take the changes.

### Pull requests (PRs)
A request to merge a branch (often from a fork) into `main`. GitHub shows the changes, runs CI, and lets you comment, ask for changes and finally merge. Example: someone sends a PR titled "fix(storage): avoid Windows reserved file names" that fixes CR-04.

### Issues
Tracked tasks and bug reports: "Bulk ZIP fails when a title is only emoji". The issue forms in `.github/ISSUE_TEMPLATE/` ask reporters for the version, steps and a privacy check.

### Discussions
A forum inside the repository for questions, ideas and longer conversations that aren't (yet) tasks, such as the desktop-app proposal.

### GitHub Actions
Automation that runs on GitHub's machines when something happens, for example running `make test` on every pull request (CI). Drafts are in [GITHUB_PUBLICATION_PLAN.md](GITHUB_PUBLICATION_PLAN.md#5-draft-github-actions).

### Branch protection (rulesets)
Rules on `main`, such as "changes must come through a pull request and the tests must pass" and "no force pushes". They stop accidents, including your own.

## Part 2: accepting a community contribution, step by step

1. **A pull request arrives.** GitHub notifies you. CI runs automatically (for first-time contributors from forks, GitHub may ask you to approve the run first; check the changes look harmless, especially workflow files).
2. **Read the description and the diff** (Files changed tab). Ask: does it fit MediaLab's scope? Does it touch cookies, subprocesses, file paths or network code (look extra carefully)? Are there tests? Did they update docs and `CHANGELOG.md`?
3. **Try it locally if it's non-trivial:**
   ```bash
   git fetch origin pull/123/head:pr-123   # 123 = the PR number
   git switch pr-123
   make test
   make dev                                 # try the feature
   git switch main
   ```
4. **Review.** Leave comments on lines; choose "Request changes" or "Approve". Be specific and kind ("Could this use `ensure_free_space` like the single download does?").
5. **Merge** when CI is green and you're happy. Prefer **Squash and merge** for small outside contributions (one tidy commit on `main`), and edit the commit message into MediaLab's style.
6. **Thank the contributor**, close the related issue (writing "Fixes #45" in the PR does it automatically), and note the change under "Unreleased" in `CHANGELOG.md` if they didn't.
7. **It's fine to decline.** Close with a short, friendly reason ("This bypasses TikTok's unlock flow, which MediaLab doesn't do").

## Part 3: maintainer guidelines

- **Scope guard:** MediaLab saves content the user may save. Decline anything that bypasses DRM, paywalls, region or age gates, private accounts or request signing.
- **Security first:** never ask anyone for cookies; delete comments that contain cookies or signed links and tell the person to sign out of TikTok sessions; handle vulnerability reports privately ([SECURITY.md](../../SECURITY.md)).
- **Pace yourself:** a weekly look at issues is enough. Use labels and the "good first issue" label to invite help.
- **Keep the bar consistent:** tests pass, docs updated, no em dashes in copy, accessible UI, no new dependency without a reason.
- **Dependencies:** merge yt-dlp updates promptly after CI passes; platforms break old versions.

## Release process

1. Make sure `main` contains everything for the release and CI is green.
2. Create a branch `chore/release-X.Y.Z`; update the version in `backend/app/__init__.py`, `backend/pyproject.toml`, `frontend/package.json` and `frontend/package-lock.json` (the two project entries); `backend/tests/test_version.py` checks they match.
3. In `CHANGELOG.md`, rename "Unreleased" to `[X.Y.Z] (date)` and add a fresh empty "Unreleased".
4. Run the full checks: `make test`, `cd frontend && npm run build`, `npm audit`, `pip-audit -r backend/requirements.lock`, plus the live checks in [docs/TESTING.md](../TESTING.md#live-checks) when providers or the media pipeline changed.
5. Merge the branch, then tag: `git tag -a vX.Y.Z -m "MediaLab vX.Y.Z: summary"` and `git push origin main vX.Y.Z`.
6. On GitHub: **Releases → Draft a new release**, choose the tag, paste the changelog section, publish.
7. Patch releases (`X.Y.Z+1`) for urgent fixes such as a yt-dlp update follow the same steps.

## Useful Git commands

| Task | Command |
|---|---|
| See where you are | `git status`, `git branch --show-current`, `git log --oneline --graph -15` |
| Start work | `git switch main && git pull && git switch -c fix/short-description` |
| Save work | `git add <files> && git commit` (check `git diff --cached` first) |
| Publish a branch | `git push -u origin fix/short-description` |
| Update a branch from main | `git switch fix/… && git merge main` |
| List tags | `git tag -n1` |

Never commit `.env`, cookies, `settings.json` or media: `.gitignore` covers them, but `git status` before every commit is the habit that protects you.
