# Open-source readiness and desktop planning

Review and planning documents prepared for MediaLab v1.9.0 (2026-11-14). Start with the readiness audit; it summarises the others and lists what the owner needs to decide before anything is published.

| Document | What it covers |
|---|---|
| [READINESS_AUDIT.md](READINESS_AUDIT.md) | **Start here.** Verdict, publication blockers, summary of all findings |
| [CODE_REVIEW_V1_9.md](CODE_REVIEW_V1_9.md) | Independent source review: architecture, security, download correctness, frontend, tests (findings CR-01 to CR-14) |
| [SECURITY_AUDIT.md](SECURITY_AUDIT.md) | History and file scan for secrets and personal data; application security summary; recommended secret scanning |
| [DEPENDENCY_LICENSE_AUDIT.md](DEPENDENCY_LICENSE_AUDIT.md) | Licences of every dependency, fonts and assets; source vs installer obligations; FFmpeg question |
| [DOCUMENTATION_AUDIT.md](DOCUMENTATION_AUDIT.md) | Accuracy review of all docs; what was fixed |
| [GITHUB_PUBLICATION_PLAN.md](GITHUB_PUBLICATION_PLAN.md) | Step-by-step publication checklist; draft CI, secret scanning and Dependabot configuration |
| [OPEN_SOURCE_MAINTAINER_GUIDE.md](OPEN_SOURCE_MAINTAINER_GUIDE.md) | GitHub concepts explained with MediaLab examples; reviewing pull requests; release process |
| [DESKTOP_PACKAGING_OPTIONS.md](DESKTOP_PACKAGING_OPTIONS.md) | Tauri, PyInstaller + pywebview and Electron compared; recommendation |
| [DESKTOP_ARCHITECTURE_PROPOSAL.md](DESKTOP_ARCHITECTURE_PROPOSAL.md) | Proposed desktop architecture, local communication security, lifecycle, phased migration |
| [DESKTOP_APP_DISCUSSION_DRAFT.md](DESKTOP_APP_DISCUSSION_DRAFT.md) | Draft GitHub Discussion inviting community feedback (not posted) |

Community files prepared alongside: [CONTRIBUTING.md](../../CONTRIBUTING.md), [CODE_OF_CONDUCT.md](../../CODE_OF_CONDUCT.md), [SECURITY.md](../../SECURITY.md), issue forms in `.github/ISSUE_TEMPLATE/`, discussion forms in `.github/DISCUSSION_TEMPLATE/` and `.github/pull_request_template.md`.

Nothing in this folder has been published, and no GitHub repository, remote, release, issue or Discussion has been created.
