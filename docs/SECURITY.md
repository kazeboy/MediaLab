# Security

MediaLab is a single-user application that runs on the user's own Mac and listens only on the loopback interface. This document describes its threat model, trust boundaries, the protections in the code and the risks that remain. It reflects v1.6.

## Reporting a vulnerability

See the repository's [security policy](../SECURITY.md): report privately through the repository's Security tab (Report a vulnerability) rather than a public issue, with reproduction steps and the affected version. Never include cookies, `settings.json` or downloaded media in a report.

## Scope and non-goals

- **X and TikTok Videos tabs:** publicly accessible posts and videos only. No login, no cookies.
- **TikTok Short Drama tab:** episodes the user's own, explicitly linked TikTok account can play.
- MediaLab does **not** bypass DRM, paywalls, coin/ad unlocks, geo/IP blocks, private or protected-account controls, and does not reproduce TikTok's request signing (`X-Bogus`, `X-Gnarly`).
- It never asks for passwords, never reads a browser's cookie store, and doesn't use `.netrc`.
- It is not designed to be exposed to a network. There is no user authentication on the API.

## Threat model

| Asset | Threat | Primary controls |
|---|---|---|
| The user's TikTok session (cookie file) | Disclosure via API, logs, errors, Git, other local users, third parties | Filtered on upload, `0600` file, never returned/logged, Short Drama provider only, `.gitignore` |
| The user's machine | SSRF / arbitrary fetches; command injection; path traversal; disk/CPU exhaustion | URL allowlists rebuilt from IDs, per-hop redirect validation, argument-list subprocesses, ID-only file access, size/space/concurrency/time limits |
| The local API | Malicious websites in the user's browser (CSRF, DNS rebinding, cross-site side effects) | Loopback bind, `TrustedHostMiddleware`, same-origin guard on every `/api` request, no CORS |
| Downloaded media | Exposure to other local users; leftovers | Owner-only working folders, random IDs, deletion after delivery/expiry, startup wipe |
| Third-party metadata (FxTwitter) | Untrusted responses steering downloads | Opt-in, X only, only the numeric post ID sent, size cap, media URLs must be on X's CDN |

Out of scope: an attacker who already runs code as the same macOS user (they can read the cookie file regardless), and a compromised yt-dlp/FFmpeg installation.

## Trust boundaries

```
 Browser tab (MediaLab UI, same origin)  ──►  Local API (127.0.0.1)  ──►  yt-dlp / FFmpeg (local processes)
 Other websites in the same browser      ─╳─►  (refused: Host/Origin/Sec-Fetch-Site)
 Local API  ──►  tiktok.com, x.com, CDNs (allowlisted), api.fxtwitter.com (opt-in)
```

- **Trusted:** the user, the local machine, the MediaLab code, yt-dlp and FFmpeg binaries.
- **Untrusted input:** pasted URLs, every byte returned by X, TikTok, FxTwitter and the CDNs (metadata, redirects, media), uploaded cookie files (parsed, not executed), request bodies.

## TikTok account

The optional sign-in for the Short Drama tab (`tiktok_account.py`).

- **How it arrives:** the user exports their own tiktok.com cookies (Netscape `cookies.txt`) and chooses the file in Settings → TikTok account. The browser reads the file and sends its text in `PUT /api/tiktok-account` (≤ 1 MB, strict schema, same-origin only).
- **Minimisation:** only cookies whose domain is `tiktok.com` or a subdomain are kept; everything else in the file is discarded before writing. Files without a signed-in session cookie (`sessionid`, `sessionid_ss` or `sid_tt`) are rejected.
- **Storage:** fixed path `<config dir>/tiktok-cookies.txt` (`~/Library/Application Support/MediaLab/` on macOS), written atomically with mode `0600`. No path is ever accepted from a client.
- **Exposure:** cookie values are never returned (the API exposes only `linked`, `cookie_count`, `session_expires_at`, `expired`, `saved_at`), never logged (a damaged file is logged by exception type only), and never included in error messages. Tests assert this.
- **Use:** loaded into an **in-memory** cookie jar of the Short Drama provider for each request; `cookiefile` stays `None`, so yt-dlp never writes the file back. The X chain, the FxTwitter fallback, the TikTok Videos tab and its anonymous wrong-tab probe never see it.
- **What it does with the session:** fetches the episode's ordinary item page and two web-app endpoints (`/api/drama/detail/`, `/api/drama/episode/item_list/`) with plain requests, as a signed-in browser would. No request signatures are generated. Locked episodes are reported (`account_access_unavailable`), never unlocked.
- **Expiry:** `auth_expired` is reported when the stored session cookie's expiry date has passed. TikTok can end a session earlier (for example after a password change); that shows up as locked episodes or login errors.
- **Removal:** **Remove** in Settings deletes the local file. **This does not sign the session out at TikTok**: anyone who copied the file could still use the session until it expires. To revoke it, sign out of tiktok.com in the browser the cookies came from (or end the session in TikTok's security settings), and delete the exported file from Downloads.
- **Git:** `.gitignore` excludes `tiktok-cookies.txt`, `cookies.txt`, `cookies*.txt`, `.env*` and `settings.json`.

## Network security

### Binding and local API access
- The backend binds to `127.0.0.1` and refuses a non-loopback host unless `MEDIALAB_ALLOW_NON_LOCAL=true`. The Vite dev server also binds to `127.0.0.1`.
- `TrustedHostMiddleware` only answers requests addressed to `127.0.0.1`, `localhost` or `::1` (DNS-rebinding protection).
- **Same-origin guard (all `/api` requests, v1.6):** refused with `403 forbidden` if the browser marks the request `Sec-Fetch-Site: cross-site` or sends a non-loopback `Origin`; state-changing methods also refuse `Origin: null`. Before v1.6, cross-site `GET`s were served: a page couldn't read the responses (no CORS), but it could trigger side effects such as a series lookup on TikTok with the linked session. Non-browser clients that send neither header (curl, scripts) still work.
- No CORS headers are ever sent; request bodies must be JSON matching strict schemas (`extra="forbid"`).

### SSRF and redirects
- **Input URLs** must be on an allowlist (`x.com`, `twitter.com` and their `www.`/`m.`/`mobile.` forms; `tiktok.com`, `www.`/`m.`, `vm.`/`vt.` short-link hosts) with a strict path pattern. Credentials, non-default ports and IP addresses are rejected. Accepted URLs are **rebuilt** from parsed IDs, so query strings and fragments never reach an extractor.
- **Short links** are resolved with `HEAD` and automatic redirects disabled; each `Location` is validated before it is requested (https, TikTok page/short-link hosts only, ≤ 5 hops).
- **`net.py`** (FxTwitter, short links) is https-only and validates every redirect hop and the final URL.
- **yt-dlp** runs with only the platform's extractor (`allowed_extractors`); the generic extractor is never available. URL-type results are rejected.
- **Media hosts:** every format URL (and manifest) must be https on the platform's allowlist before yt-dlp may fetch it. X: `*.twimg.com` (configurable); TikTok: `*.tiktokcdn.com`, `*.tiktokcdn-eu.com`, `*.tiktokcdn-us.com` and edge nodes matching `v<digits>…​.tiktok.com`. Thumbnails and series covers are filtered the same way.
- **Short Drama series requests** go only to fixed `https://www.tiktok.com/api/drama/…` paths with a numeric series ID; the response's final URL must still be `https://www.tiktok.com`. Responses are capped at 16 MB and pagination at 500 episodes.
- **Residual risk:** yt-dlp follows HTTP redirects while downloading media; MediaLab can't vet each hop inside yt-dlp, but every initial URL is on the platform's CDN and only the final, verified MP4 reaches the client.

### External services
| Service | When | What is sent |
|---|---|---|
| x.com / twimg.com | X analysis and downloads | The canonical post URL; no cookies |
| tiktok.com / TikTok CDNs | TikTok analysis and downloads | The canonical item URL; TikTok's own anonymous cookies set during the request; for Short Drama only, the linked session cookies |
| api.fxtwitter.com | Only if the user enables the fallback and yt-dlp finds no X video | The numeric post ID only |

## Filesystem security

- **Fixed locations:** MediaLab writes only to its temp folder (`MEDIALAB_TEMP_DIR`) and config folder (`MEDIALAB_CONFIG_DIR`).
- **Permissions (v1.6):** MediaLab's working subfolders (`ready/`, `job-<id>/`, `job-batch-<id>/`) are created `0700`; the temp and config folders are created `0700` when MediaLab creates them. An existing, shared base folder is not changed (a note is logged). The cookie file and `settings.json` are `0600`.
- **No user-controlled paths:** finished files live at `ready/<random 128-bit id>.mp4|.zip`; `/api/files/{id}` accepts only 32-hex IDs from an in-memory registry and re-checks that the resolved path is inside `ready/`. Display names appear only in `Content-Disposition` (sanitised, RFC 5987-encoded).
- **Filename sanitisation:** Unicode normalisation; control/format characters (incl. bidi overrides), path separators, reserved characters and leading dots removed; length-limited.
- **ZIP safety:** entry names are MediaLab's own episode filenames; names containing `/`, `\`, a leading dot or nothing are refused. Entries are stored (not compressed), so there is no decompression-bomb shape; every archive is CRC-verified before delivery.
- **Deletion:** `remove_tree_within` only deletes paths strictly inside the expected root (symlinks resolved first). Files are never deleted while a response is streaming them.
- **Symlinks:** MediaLab never follows a user-supplied path; it creates all files itself under random names.
- **Concurrency:** each job has its own folder; each batch its own folder; delivery state changes happen under a lock; one transfer per file (`409` for duplicates).

## Command execution

FFmpeg and FFprobe always run as argument lists (`subprocess.run` / `Popen`, never a shell), with absolute input paths. The concat list for merging contains only MediaLab's own temp paths. Merge FFmpeg runs are watched by a thread that kills the process on cancel or timeout even if it produces no output (v1.6 fix).

## Resource limits

| Limit | Setting | Default |
|---|---|---|
| Concurrent downloads (others queue) | `MEDIALAB_MAX_CONCURRENT_DOWNLOADS` | 2 |
| Active + queued jobs | `MEDIALAB_MAX_QUEUED_JOBS` | 10 |
| Concurrent analyses / series lookups | `MEDIALAB_MAX_CONCURRENT_ANALYSES` | 4 |
| Max file size per download/episode (frozen per job) | Settings | 8 GB (256 MB–64 GB) |
| Max batch output (ZIP / merged MP4) | Settings | 32 GB (256 MB–256 GB) |
| Free space reserve | `MEDIALAB_MIN_FREE_SPACE_MB` | 512 MB |
| Analysis timeout | `MEDIALAB_ANALYSIS_TIMEOUT_SECONDS` | 45 s |
| Whole-download timeout | `MEDIALAB_DOWNLOAD_TIMEOUT_SECONDS` | 3 h |
| FFmpeg/FFprobe per step / per merge | `MEDIALAB_FFMPEG_TIMEOUT_SECONDS` / fixed | 600 s / 6 h |
| Batches | fixed | 2 active (Short Drama and link batches together), 500 episodes, no duplicates |
| Batch parallelism | request, capped | Short Drama ≤ 2; links ≤ 4 and ≤ `MEDIALAB_MAX_CONCURRENT_DOWNLOADS` |
| Links per bulk download | `MEDIALAB_MAX_BULK_URLS` | 50 distinct links (at most 100); 500 pasted lines of ≤ 4 KB each |
| Bulk analyses | fixed | 2 at once, 2 extractions at a time |
| Identical jobs | fixed | one active download per video and quality (`already_downloading`) |
| Unsaved file retention | `MEDIALAB_DELIVERY_RETENTION_MINUTES` | 30 min |
| Upload sizes | fixed | cookies ≤ 1 MB; series response ≤ 16 MB |

Video is re-encoded only for a merged MP4 whose episodes don't share a format (user-initiated, bounded, cancellable).

Bulk downloads (v1.9) add no new trust boundary: every pasted line is validated server-side with the same allowlists as a single analysis (no redirects to other platforms, no mixing), links for other tabs are reported rather than followed, and every item downloads as an ordinary job with the same media-host checks, size limits and free-space checks. The new routes sit behind the same Host, Origin and cross-site guards. The TikTok account is still used by the Short Drama provider only: bulk TikTok downloads go through the anonymous TikTok Videos provider. ZIP manifests contain titles and reasons only, never links, signed media URLs or account data.

## Sensitive data handling

- Error responses carry a stable `code`, a message, an action and small `details`, never stack traces, local paths, cookies or signed media URLs.
- Server logs contain method, path, error code and the exception cause chain (which may include a CDN URL from yt-dlp, but never cookie values).
- Delivered files are sent with `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`; the UI loads thumbnails with `Referrer-Policy: no-referrer`.

## Known security limitations

1. **No API authentication.** Any local process can call the API while MediaLab runs, including processes of **other user accounts on the same Mac**: a loopback port isn't limited to its owner. Web pages can't (Host and Origin checks). On a shared computer, another local user could start downloads or use your linked TikTok session for Short Drama lookups while MediaLab is running (they can't read the cookie values, and finished files have unguessable IDs). Run MediaLab only while you use it on shared machines. A per-launch secret is planned for the desktop application ([proposal](open-source/DESKTOP_ARCHITECTURE_PROPOSAL.md)).
2. **The cookie file is a bearer credential** protected only by file permissions on this Mac, and removing it doesn't revoke the session at TikTok.
3. **Same-origin guard relies on browser headers.** Modern browsers send `Sec-Fetch-Site`/`Origin`; very old browsers might not, in which case cross-site `GET`s would be served as before (responses still unreadable cross-origin).
4. **yt-dlp follows media redirects internally** (see SSRF residual risk).
5. **Public identifiers in the repository:** tests and docs mention real, public TikTok series/item IDs and creator handles used during verification; no private data or credentials.

## Copyright and platform terms

Videos are owned by their creators. Downloading may be restricted by copyright law and by each platform's terms of service; using an account with a downloader may conflict with TikTok's terms. MediaLab is intended for personal use with content you are entitled to save.

## Hygiene for contributors

- Never commit `.env`, `settings.json`, `tiktok-cookies.txt`, cookie exports or downloaded media.
- Keep `yt-dlp` current (`make update-ytdlp`).
- Security-relevant tests live in `test_api.py` (host/origin), `test_validation.py`, `test_shortdrama.py` (account), `test_storage.py`, `test_packaging.py` (ZIP names). Run `make test` before changes land.
