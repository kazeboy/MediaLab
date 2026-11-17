# Security policy

## Supported versions

MediaLab is maintained by one person. Security fixes are made for the **latest release** only (currently 1.9.x). Please update before reporting.

| Version | Supported |
|---|---|
| 1.9.x | Yes |
| < 1.9 | No |

## Reporting a vulnerability

Please **don't open a public issue** for a security problem.

Report it privately with GitHub's **Private Vulnerability Reporting**:

1. Open the repository's [Security tab](https://github.com/kazeboy/MediaLab/security).
2. Choose **Report a vulnerability** (or go straight to [the private report form](https://github.com/kazeboy/MediaLab/security/advisories/new)).
3. Describe the problem. Only you and the maintainer can see the report.

Include the MediaLab version, your operating system, what you did, what happened, and why it's a security problem. A minimal reproduction helps a lot.

MediaLab is a spare-time project with one maintainer, so response and fix times vary. You'll be kept informed in the report and credited (if you wish) when a fix is released.

## What never to include

In reports, issues, logs and screenshots, never include:

- TikTok cookies, `cookies.txt` exports or the `tiktok-cookies.txt` file;
- `settings.json` or anything from `~/Library/Application Support/MediaLab/`;
- signed media links (URLs with `x-expires`, `signature`, `tk=` or similar);
- downloaded media, or account names and IDs you don't want public.

If you posted any of these by mistake, delete the post and, for TikTok cookies, sign out of all sessions on tiktok.com so the cookies stop working.

## Protecting your TikTok session

The Short Drama tab uses cookies you export from your own browser. Anyone with those cookies can act as your TikTok account. MediaLab stores them in a file only your user account can read, never shows their values, and uses them only for the Short Drama tab. Keep the export file private, delete it after linking, remove the account in Settings when you no longer need it, and sign out on tiktok.com to end the session.

## Scope

MediaLab runs locally and is not designed to be exposed to a network. Its threat model, known limitations (for example, no API authentication on the loopback port) and non-goals are documented in [docs/SECURITY.md](docs/SECURITY.md).
