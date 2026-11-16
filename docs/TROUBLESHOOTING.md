# Troubleshooting

Every error in MediaLab shows a message, a suggested action and a **code** (small text under the message). Find the code below. The backend terminal (`make dev`) logs each error as `METHOD path -> code (status): message | cause: …`. The *cause* part is the original reason (e.g. yt-dlp's message).

## Links and analysis

| Code | Meaning | What to do |
|---|---|---|
| `invalid_url` | Not an X/TikTok link MediaLab recognises | Copy the full link from the address bar or the app's Share → Copy link |
| `unsupported_url` | A recognised site but not a single video (profile, photo slideshow, Live, playlist) | Open the individual video and copy its link |
| `unsupported_episode_url` | A `/shortdrama/…` address that isn't `/shortdrama/episode/<series>/<n>` | Use the episode's share link or its episode address |
| `wrong_platform` | The link belongs to another tab | Click **Switch** in the message |
| `short_link_expired` | The `vm.tiktok.com/…` link no longer leads to a video | Get a fresh share link |
| `not_found` | Deleted, private, or (Short Drama) TikTok's internal record `203008` | Check the link opens in a browser; for Short Drama use the share link |
| `no_video` | The post has no downloadable video (X may also return this for posts it hides from logged-out visitors) | Check the post has a video; for X, consider enabling the FxTwitter fallback in Settings |
| `region_restricted` | TikTok/X blocks the video for your location/IP | Nothing MediaLab can do |
| `rate_limited` | The platform is throttling requests | Wait a few minutes |
| `network_error`, `timeout` | Connection problem (retried automatically up to 3 times) | Check the connection; Try again |
| `extraction_failed` | The extractor failed for another reason (message includes it) | `make update-ytdlp`, restart, try again |
| `media_host_blocked` | The video exists but is served from a host outside MediaLab's allowlist | Not downloadable by design |
| `busy` | Too many analyses at once | Try again in a moment |

### TikTok-specific
- **"TikTok refused the request … impersonation"** (`extraction_failed`): yt-dlp's `curl-cffi` extra is missing. Run `make setup` or `make update-ytdlp`.
- **A video lists only "No audio track" options above the best one:** TikTok offered those resolutions only as video-only streams, and MediaLab doesn't attach TikTok's separate music track to ordinary videos (it can be a song rather than the video's audio). Choose the Best Available option.

## TikTok Short Drama and the account

| Code | Meaning | What to do |
|---|---|---|
| `login_required` | No TikTok account is linked; TikTok shows a locked preview | Settings → TikTok account → choose a `cookies.txt` export from a browser where you're signed in to tiktok.com |
| `auth_expired` | The linked cookies' session has expired | Sign in to tiktok.com again, export the cookies again, re-link |
| `account_access_unavailable` | Still no stream with your account | Check the episode plays for you on tiktok.com (it may need unlocking); if it does, re-export and re-link the cookies |
| `episode_not_in_series` | That episode number doesn't exist | Check the number (`details.episode_count` says how many exist) |
| `episode_resolution_failed`, `series_metadata_unavailable` | TikTok didn't return the series (message includes TikTok's status) | Try again later; share links keep working even when direct links don't |
| `validation_error` when linking | The file isn't a Netscape `cookies.txt`, or has no signed-in tiktok.com session | Export again with the "current site" option while signed in |

Removing the account in Settings deletes MediaLab's copy of the cookies but **does not sign you out at TikTok**. Sign out on tiktok.com to end the session.

## Downloads

| Code | Meaning | What to do |
|---|---|---|
| `file_too_large` | Over the per-file limit | Raise **Maximum file size** in Settings, or choose a lower resolution |
| `insufficient_space` | Not enough free disk space in the temp folder (needs ~2× the file + 512 MB) | Free space, or set `MEDIALAB_TEMP_DIR` to a larger disk |
| `too_many_jobs` | Too many downloads queued | Wait for some to finish |
| `cdn_url_expired` | The CDN refused the link even after fresh links were fetched | Try again |
| `download_interrupted` | The transfer stopped (retried automatically) | Try again |
| `format_unavailable` | The chosen format is no longer offered | Analyse again |
| `analysis_expired` | The analysis is older than its TTL | Click Analyse again |
| `ffmpeg_missing` | FFmpeg/FFprobe not found | `brew install ffmpeg`, restart MediaLab |
| `incompatible_format` | The video codec can't go into MP4 without re-encoding | Choose another resolution |
| `already_downloading` | The same video in the same quality is already downloading (double click, another tab, a bulk item) | Nothing: the page follows the running download; see Downloads |
| `download_cancelled` | You cancelled the download (state `cancelled`) | Retry from Downloads, or Download MP4 again |

## Bulk downloads (X and TikTok)

| Code / symptom | Meaning | What to do |
|---|---|---|
| "That's N different links; a bulk download can hold at most 50" | Over the link limit (duplicates and invalid lines don't count) | Split the list, or raise `MEDIALAB_MAX_BULK_URLS` (at most 100) |
| A line marked **Not used** / `wrong_platform` | A link for another tab (MediaLab never mixes platforms) | **Open in …** sends that link to its tab |
| A line marked **Duplicate** | The same post as an earlier line (x.com and twitter.com count as the same) | Nothing: it's downloaded once |
| `bulk_not_found` | The analysis expired (an hour after it ended) or MediaLab restarted | Paste the links and analyse again |
| `busy` | Two bulk analyses are already running | Wait, or stop one |
| `item_not_found` | The item number isn't in the batch | Refresh the list |
| A ZIP batch says **Stopped** | You cancelled it after some videos finished | **Build ZIP from finished videos**, or **Discard them** |
| Some videos used another resolution | The chosen quality isn't offered; MediaLab used the next lower one (or the closest higher one) | Shown per video before you start; choose Best available for each video's best |

## Missing or wrong audio

| Code / symptom | Meaning | What to do |
|---|---|---|
| `audio_missing` | The source promised audio but the file has none (and no trustworthy separate track was available), or a merged episode segment is silent | Try again; if it repeats, choose another resolution |
| `audio_conversion_failed` | Converting audio to AAC failed or produced silence | Try again; choose a resolution whose audio is already AAC (e.g. TikTok's H.264 option) |
| `av_sync_failed` | Audio and video lengths/starts don't match | Try again or choose another resolution |
| `mp4_compatibility` | The result wouldn't play in QuickTime/Safari | Choose another resolution |
| A file plays silently in QuickTime but with sound in VLC | MP3 audio inside MP4 (MediaLab v1.3/v1.4 files) | Download it again with v1.5 or later (audio is converted to AAC) |
| "Source audio is silent" note | The source itself is silent; MediaLab kept it as is | Nothing to fix |

## Saving in the browser

- **Nothing happens on Save Video:** check the browser's download bar/permissions. If the file was saved already, MediaLab has deleted its copy (`file_not_found`). Download again.
- **`delivery_in_progress`:** the same file is already being saved; wait.
- **Transfer interrupted:** the file goes back to "ready"; click Save again before it expires (30 minutes by default).
- **Batch "Separate files" stops after a few episodes:** the page must stay open; Chrome may ask to allow multiple downloads; allow it. MediaLab keeps at most two unsaved episodes and waits for you to save them.
- **No "Choose folder…" button:** folder saving needs a Chromium browser (Chrome, Edge, Arc, Brave). Safari/Firefox save into Downloads.

## Batch ZIP and merged MP4

| Code / state | Meaning | What to do |
|---|---|---|
| `needs_decision` / `batch_partial` | Some episodes failed; nothing was packaged | Retry those episodes, or click **Continue without the failed episodes** |
| `batch_output_too_large` | The episodes exceed the batch output limit | Raise **Maximum batch output size** in Settings, select fewer episodes, or pick a lower quality |
| `insufficient_space` (packaging) | Not enough space for the ZIP/merged file | Free space, then **Retry packaging** |
| `zip_failed` | Writing or verifying the archive failed | **Retry packaging**; check disk space |
| `merge_failed` | Joining failed verification (duration, decode errors) | **Retry packaging**; if it repeats, use ZIP |
| `transcode_failed` | Re-encoding failed, e.g. FFmpeg lacks `libx264` (message says so) | `brew reinstall ffmpeg`, or choose one quality for all episodes / ZIP |
| `merge_incompatible` | An episode file can't be read for merging | Retry that episode |
| `batch_in_progress` | An identical batch is already running | Use the existing batch, or cancel it |
| `batch_cancelled` | Cancelled (or waited too long for a decision) | Start a new batch |
| `batch_not_found` | The backend restarted or forgot the batch | Start the batch again: downloads can't be resumed after a restart (temporary files from before it are deleted) |

A merge that re-encodes (the plan note says so) takes CPU time: roughly 4 s per minute of 720p on Apple silicon.

## Startup and environment

| Symptom | Cause / fix |
|---|---|
| `make dev`: "port 8000 (or 5173) is already in use" | Another process (often an earlier MediaLab) holds the port; the message shows its PID. Stop it |
| Backend exits: "Cannot use the temporary/settings folder … Operation not permitted" | macOS privacy protection for that folder; grant your terminal "Files and Folders" access or set `MEDIALAB_TEMP_DIR`/`MEDIALAB_CONFIG_DIR` elsewhere |
| Backend refuses to start on a non-loopback host | Intentional; set `MEDIALAB_ALLOW_NON_LOCAL=true` only if you understand the risk (no authentication) |
| UI: "MediaLab cannot connect to its local backend" | The backend isn't running; check the `make dev` terminal |
| `403 forbidden` "Cross-origin requests are not allowed" | A request came from another website or origin; use the MediaLab page itself (http://127.0.0.1:5173 or :8000) |
| Settings changes don't stick | `settings.json` couldn't be written; check permissions of `~/Library/Application Support/MediaLab` |
