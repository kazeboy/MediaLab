# Open-source readiness audit

*2026-11-14, MediaLab v1.9.0 (tag `v1.9.0`, commit `e9005e8`). Summary of the detailed reports in this folder.*

## Verdict

**MediaLab is technically ready to be published as a source project after four owner decisions.** No critical or high-severity defects were found, no secrets are in the history, and dependency licences are compatible with MIT. The remaining items are decisions only the owner can make, plus some recommended clean-up.

## Publication blockers (owner decisions)

| # | Blocker | Details |
|---|---|---|
| B1 | Personal email address in all commit metadata | **Resolved (2026-11-16):** the public repository starts from a clean snapshot without the development history ([CR-14](CODE_REVIEW_V1_9.md#cr-14-medium-publication-decision-commit-metadata-contains-a-personal-email-address)) |
| B2 | Placeholders in community files | Maintainer contact in `CODE_OF_CONDUCT.md` and `SECURITY.md`; `OWNER/REPO` in `.github/ISSUE_TEMPLATE/config.yml` |
| B3 | Licence details | **Decided (2026-11-16):** MIT for code; MediaLab brand assets reserved ([BRAND_ASSETS.md](../../BRAND_ASSETS.md)). Still open: the copyright holder line and an optional legal review of the brand wording |
| B4 | Owner review of the public snapshot | Replaces merging: the reviewed files are exported to a separate folder without Git history |

## Strongly recommended before publication

- ~~Replace real creator and series names in fixtures and docs (CR-13).~~ Done (2026-11-16).
- Enable private vulnerability reporting, secret scanning and push protection as soon as the repository exists.

## Findings at a glance

| Area | Result | Report |
|---|---|---|
| Code review | 0 Critical, 0 High, 5 Medium, 9 Low | [CODE_REVIEW_V1_9.md](CODE_REVIEW_V1_9.md) |
| Security and history | No secrets, cookies, tokens, signed URLs or media in history; personal email in commit metadata; API has no authentication (documented) | [SECURITY_AUDIT.md](SECURITY_AUDIT.md) |
| Dependencies and licences | All runtime dependencies permissive (MIT/BSD/Apache/PSF/ISC/Unlicense) or MPL-2.0 unmodified; fonts OFL with notices; no known vulnerabilities; FFmpeg licensing matters only for a future installer | [DEPENDENCY_LICENSE_AUDIT.md](DEPENDENCY_LICENSE_AUDIT.md) |
| Documentation | Accurate after 10 fixes on this branch; 0 broken links | [DOCUMENTATION_AUDIT.md](DOCUMENTATION_AUDIT.md) |
| Community files | Drafted | `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `.github/` forms and templates |
| Tests | Backend 571 passed, frontend 84 passed, typecheck and build clean (2026-11-14) | [TESTING.md](../TESTING.md) |

## Medium findings to schedule (not blockers)

- CR-01 delivery completion race with early-closing clients.
- CR-02 no API authentication on the loopback port (documented; per-launch token proposed).
- CR-03 extraction concurrency not bounded globally.
- CR-04 Windows incompatibilities (blocks a Windows build only).

## What was verified versus assumed

- **Verified:** test runs, audits, history and file scans, link checks, licence metadata, code locations cited in each finding, and the live behaviour recorded on 2026-11-13.
- **Not verified:** Linux and Windows behaviour (no machines or CI); legal conclusions on FFmpeg and bundled native libraries (marked "to verify"); desktop sizes and startup times (estimates).
