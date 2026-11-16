# Documentation audit

*Audit date: 2026-11-14, tag `v1.9.0`. Every Markdown file in the repository was read against the v1.9.0 source. Links were checked with a script (all relative links and in-page anchors in all tracked `.md` files).*

## Result

- **Link check:** 0 broken links or anchors before and after the changes on this branch.
- **No em dashes** in project-authored text (enforced by `copy-punctuation.test.ts` and `test_copy_punctuation.py`; both pass).
- The current reference docs (README, ARCHITECTURE, API, MEDIA_PIPELINE, SECURITY, DEVELOPMENT, TESTING, TROUBLESHOOTING, FRONTEND_DESIGN_SYSTEM, DESIGN_DECISIONS) describe v1.9.0 accurately, apart from the items below.

## Issues found and fixed on this branch

| ID | File | Issue | Fix |
|---|---|---|---|
| DOC-01 | `docs/SECURITY.md` | Said only processes "running as the same user" can reach the API; any local account can (CR-02) | Rewritten with the real exposure and advice for shared Macs |
| DOC-02 | `docs/SECURITY.md` | Vulnerability reporting instructions lived only here | Now points to the root `SECURITY.md` policy |
| DOC-03 | `README.md` | "Linux works for the backend" stated as fact; not tested regularly; Windows not mentioned | Reworded: macOS supported, Linux run but not tested regularly, Windows not yet supported (CR-04) |
| DOC-04 | `README.md` | Documentation table still described the changelog as v1.6 to v1.8 and the readiness checklist as current | Updated; historical documents labelled; links to `docs/open-source/`, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT |
| DOC-05 | `README.md` | No contributing or security section | Added "Contributing and security" |
| DOC-06 | `docs/DESIGN_DECISIONS.md` | D21 described the pre-v1.9 cancellation mechanism as if current | Marked superseded by D27 |
| DOC-07 | `docs/FRONTEND_DESIGN_SYSTEM.md` | Activity table said Cancel applies to "queued or downloading" jobs | Now "queued, downloading or processing" |
| DOC-08 | `docs/CODE_REVIEW_REPORT.md` | Historical v1.6 review not marked as such | "Historical document" banner linking the v1.9 review |
| DOC-09 | `docs/GITHUB_READINESS.md` | v1.6 checklist ("not yet a Git repository") read as current | "Historical, superseded" banner linking `docs/open-source/` |
| DOC-10 | `docs/DEVELOPMENT.md` | Same Linux claim as DOC-03 | Same rewording |

## Issues found, not changed (recommendations)

| ID | File | Issue | Recommendation |
|---|---|---|---|
| DOC-11 | `backend/requirements.lock` | Header says "MediaLab v1.6"; mixes runtime and test packages (CR-08) | Regenerate and split when touching dependencies |
| DOC-12 | `docs/UI_UX_REVIEW.md` | Mixes historical findings (v1.6) with later implementation notes; headings say which version each part is from | Acceptable; consider splitting historical findings into an appendix |
| DOC-13 | `docs/DEVELOPMENT.md`, `docs/CODE_REVIEW_REPORT.md`, `docs/API.md` | Name real creators and a real Short Drama series (CR-13) | Replace with placeholders before publication |
| DOC-14 | `README.md` | Install step `git clone <this repository>` | Replace with the real URL after publication |
| DOC-15 | `docs/TESTING.md` | Live checks are manual and depend on public posts that can disappear | Keep a short list of maintainer-chosen test links outside the repository |
| DOC-16 | (none) | No CI documentation yet | Add once the CI workflow is adopted |

## Coverage of required topics

| Topic | Where | Status |
|---|---|---|
| Installation and requirements | README, DEVELOPMENT | Accurate for macOS |
| Supported platforms | README | Corrected (DOC-03) |
| Authentication requirements | README (Short Drama sign-in), SECURITY, TROUBLESHOOTING | Accurate |
| Security warnings | README, root SECURITY.md, docs/SECURITY.md | Accurate after DOC-01 |
| Download limitations | README "Known limitations", TROUBLESHOOTING | Accurate, includes bulk limits |
| Testing instructions | README, TESTING, CONTRIBUTING | Accurate (571 + 84 tests) |
| Known issues | README, CODE_REVIEW_V1_9 | Present |
| Contribution guidance | CONTRIBUTING (new) | Added |
| Licensing statements | README, LICENSE, fonts, licence audit | Accurate |
